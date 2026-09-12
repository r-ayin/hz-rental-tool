"""租房本地服务：接收浏览器扩展采集的贝壳房源、提供服务端在线检索、
以 SQLite + JSONL 双写存储，并托管前端画廊页面。

启动：python server.py（或 run.cmd / run.sh）
监听：http://127.0.0.1:8765
"""

from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse
import json
import mimetypes
import os
import re
import sqlite3
import threading
import time

import crawler
import vision

HOST = "127.0.0.1"
PORT = int(os.environ.get("RENTAL_PORT") or 8765)
ROOT_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT_DIR / "data"
DB_PATH = DATA_DIR / "houses.db"
JSONL_PATH = DATA_DIR / "houses.jsonl"
COOKIE_PATH = DATA_DIR / "cookie.txt"
PUBLIC_DIR = Path(__file__).resolve().parent / "public"
MAX_CRAWL_PAGES = 30
MIN_CRAWL_INTERVAL = 5.0  # 两次检索启动的最小间隔（秒），防风控
_crawl_lock = threading.Lock()
_last_crawl_start = 0.0

SORT_SQL = {
    "updated": "updated_at DESC, id DESC",
    "rent_asc": "(rent_monthly IS NULL), rent_monthly ASC, id DESC",
    "rent_desc": "rent_monthly DESC, id DESC",
    "area_desc": "area_sqm DESC, id DESC",
    "area_asc": "(area_sqm IS NULL), area_sqm ASC, id DESC",
}


def now_iso():
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def ensure_storage():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS houses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL DEFAULT 'ke',
                url TEXT NOT NULL UNIQUE,
                house_code TEXT,
                title TEXT,
                rent_type TEXT,
                community TEXT,
                district TEXT,
                bizcircle TEXT,
                area_sqm REAL,
                orientation TEXT,
                layout TEXT,
                floor_desc TEXT,
                rent_monthly INTEGER,
                rent_text TEXT,
                deposit TEXT,
                tags TEXT,
                brand TEXT,
                image TEXT,
                images TEXT,
                maintain_time TEXT,
                description TEXT,
                captured_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        columns = [row[1] for row in conn.execute("PRAGMA table_info(houses)").fetchall()]
        if "vision_report" not in columns:
            conn.execute("ALTER TABLE houses ADD COLUMN vision_report TEXT")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_houses_district ON houses(district)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_houses_community ON houses(community)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_houses_rent ON houses(rent_monthly)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_houses_layout ON houses(layout)")


def normalize_house(payload):
    """把扩展/爬虫两种来源的房源 payload 归一化为数据库行 dict。"""
    url = str(payload.get("url") or "").strip()
    if not url:
        raise ValueError("missing url")

    tags = payload.get("tags") or []
    if isinstance(tags, str):
        tags = [tag.strip() for tag in re.split(r"[,，;；\s]+", tags) if tag.strip()]

    images = payload.get("images") or []
    if isinstance(images, str):
        images = [images] if images.strip() else []

    def pick(*keys):
        for key in keys:
            value = payload.get(key)
            if value not in (None, ""):
                return value
        return ""

    area = pick("area_sqm", "areaSqm", "area")
    try:
        area = float(str(area).replace("㎡", "").strip()) if area not in (None, "") else None
    except ValueError:
        area = None

    rent = pick("rent_monthly", "rentMonthly", "rent")
    try:
        rent = int(float(str(rent).replace(",", "").strip())) if rent not in (None, "") else None
    except ValueError:
        rent = None

    title = str(pick("title") or "未命名房源")
    rent_type = str(pick("rent_type", "rentType") or "")
    if not rent_type and "·" in title:
        prefix = title.split("·", 1)[0].strip()
        if prefix in ("整租", "合租", "独栋", "公寓"):
            rent_type = prefix

    return {
        "source": str(pick("source") or "ke"),
        "url": url,
        "house_code": str(pick("house_code", "houseCode") or ""),
        "title": title,
        "rent_type": rent_type,
        "community": str(pick("community") or ""),
        "district": str(pick("district") or ""),
        "bizcircle": str(pick("bizcircle") or ""),
        "area_sqm": area,
        "orientation": str(pick("orientation") or ""),
        "layout": str(pick("layout") or ""),
        "floor_desc": str(pick("floor_desc", "floorDesc", "floor") or ""),
        "rent_monthly": rent,
        "rent_text": str(pick("rent_text", "rentText") or (str(rent) if rent else "")),
        "deposit": str(pick("deposit") or ""),
        "tags": json.dumps(tags, ensure_ascii=False),
        "brand": str(pick("brand") or ""),
        "image": str(pick("image") or ""),
        "images": json.dumps(images, ensure_ascii=False),
        "maintain_time": str(pick("maintain_time", "maintainTime") or ""),
        "description": str(pick("description") or ""),
        "captured_at": str(pick("captured_at", "capturedAt") or ""),
    }


UPSERT_SQL = """
    INSERT INTO houses (
        source, url, house_code, title, rent_type, community, district, bizcircle,
        area_sqm, orientation, layout, floor_desc, rent_monthly, rent_text,
        deposit, tags, brand, image, images, maintain_time, description,
        captured_at, created_at, updated_at
    ) VALUES (
        :source, :url, :house_code, :title, :rent_type, :community, :district, :bizcircle,
        :area_sqm, :orientation, :layout, :floor_desc, :rent_monthly, :rent_text,
        :deposit, :tags, :brand, :image, :images, :maintain_time, :description,
        :captured_at, :created_at, :updated_at
    )
    ON CONFLICT(url) DO UPDATE SET
        source=excluded.source,
        house_code=excluded.house_code,
        title=excluded.title,
        rent_type=excluded.rent_type,
        community=excluded.community,
        district=excluded.district,
        bizcircle=excluded.bizcircle,
        area_sqm=COALESCE(excluded.area_sqm, houses.area_sqm),
        orientation=excluded.orientation,
        layout=excluded.layout,
        floor_desc=excluded.floor_desc,
        rent_monthly=COALESCE(excluded.rent_monthly, houses.rent_monthly),
        rent_text=excluded.rent_text,
        deposit=excluded.deposit,
        tags=excluded.tags,
        brand=excluded.brand,
        image=COALESCE(NULLIF(excluded.image, ''), houses.image),
        images=CASE WHEN excluded.images != '[]' THEN excluded.images ELSE houses.images END,
        maintain_time=excluded.maintain_time,
        description=CASE WHEN excluded.description != '' THEN excluded.description ELSE houses.description END,
        captured_at=excluded.captured_at,
        updated_at=excluded.updated_at
"""


def save_houses(payloads):
    """批量 upsert 房源，返回 (saved_count, records)。"""
    ensure_storage()
    timestamp = now_iso()
    records = []
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        for payload in payloads:
            house = normalize_house(payload)
            if not house["captured_at"]:
                house["captured_at"] = timestamp
            conn.execute(UPSERT_SQL, {**house, "created_at": timestamp, "updated_at": timestamp})
            row = conn.execute("SELECT * FROM houses WHERE url = ?", (house["url"],)).fetchone()
            records.append(dict(row))
    with JSONL_PATH.open("a", encoding="utf-8") as file:
        for record in records:
            file.write(json.dumps(record, ensure_ascii=False) + "\n")
    return len(records), records


def list_houses(params):
    """按查询参数筛选房源列表。"""
    ensure_storage()

    def first(key, default=""):
        values = params.get(key)
        return values[0] if values else default

    query = first("q").strip().lower()
    district = first("district").strip()
    rent_type = first("rentType").strip()
    rooms = first("rooms").strip()
    min_rent = first("minRent").strip()
    max_rent = first("maxRent").strip()
    sort = first("sort", "updated")
    order = SORT_SQL.get(sort, SORT_SQL["updated"])

    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = [dict(row) for row in conn.execute(f"SELECT * FROM houses ORDER BY {order}").fetchall()]

    result = []
    for row in rows:
        if district and district != row.get("district"):
            continue
        if rent_type and rent_type != row.get("rent_type"):
            continue
        if rooms:
            match = re.match(r"^(\d+)室", row.get("layout") or "")
            if not match:
                continue
            room_count = int(match.group(1))
            if rooms == "3":
                if room_count != 3:
                    continue
            elif rooms == "4":
                if room_count < 4:
                    continue
            elif room_count != int(rooms):
                continue
        rent = row.get("rent_monthly")
        if min_rent and (rent is None or rent < int(min_rent)):
            continue
        if max_rent and (rent is None or rent > int(max_rent)):
            continue
        if query:
            haystack = " ".join(
                str(row.get(key) or "")
                for key in ("title", "community", "district", "bizcircle", "layout",
                            "orientation", "floor_desc", "deposit", "tags", "brand",
                            "description", "rent_text")
            ).lower()
            if query not in haystack:
                continue
        result.append(row)
    return result


def stats():
    ensure_storage()
    with sqlite3.connect(DB_PATH) as conn:
        total = conn.execute("SELECT COUNT(*) FROM houses").fetchone()[0]
        avg_rent = conn.execute("SELECT AVG(rent_monthly) FROM houses WHERE rent_monthly IS NOT NULL").fetchone()[0]
        by_district = conn.execute(
            "SELECT district, COUNT(*) AS count, AVG(rent_monthly) AS avg_rent "
            "FROM houses WHERE district != '' GROUP BY district ORDER BY count DESC"
        ).fetchall()
    return {
        "total": total,
        "avg_rent": round(avg_rent) if avg_rent else None,
        "by_district": [
            {"district": row[0], "count": row[1], "avg_rent": round(row[2]) if row[2] else None}
            for row in by_district
        ],
    }


def read_saved_cookie():
    if COOKIE_PATH.is_file():
        return COOKIE_PATH.read_text(encoding="utf-8").strip()
    return ""


def run_crawl(payload):
    """服务端在线检索：抓取 hz.zu.ke.com 列表页并入库。

    防护：同一时刻只允许一个检索任务（锁），两次启动间隔 >= MIN_CRAWL_INTERVAL；
    登录墙/人机验证/限流分别返回可操作的错误码，绝不静默重试硬撞。
    """
    global _last_crawl_start
    if not _crawl_lock.acquire(blocking=False):
        return {"ok": False, "error": "busy", "message": "已有检索任务在执行，请等它结束再试。"}
    try:
        now = time.monotonic()
        wait = MIN_CRAWL_INTERVAL - (now - _last_crawl_start)
        if wait > 0:
            return {"ok": False, "error": "too_soon",
                    "message": f"检索过于频繁，请 {int(wait) + 1} 秒后再试（防风控间隔）。"}
        _last_crawl_start = now
        return _run_crawl_locked(payload)
    finally:
        _crawl_lock.release()


def _run_crawl_locked(payload):
    filters = {
        "district": str(payload.get("district") or ""),
        "priceTier": payload.get("priceTier") or None,
        "rooms": payload.get("rooms") if payload.get("rooms") not in (None, "") else None,
        "rentType": str(payload.get("rentType") or ""),
        "keyword": str(payload.get("keyword") or ""),
        "sort": str(payload.get("sort") or ""),
    }
    pages = max(1, min(int(payload.get("pages") or 1), MAX_CRAWL_PAGES))
    cookie = str(payload.get("cookie") or "").strip() or read_saved_cookie()

    saved_urls = []

    def on_page(page, result):
        if result["houses"]:
            save_houses(result["houses"])
            saved_urls.extend(house["url"] for house in result["houses"])

    try:
        summary = crawler.crawl(
            filters=filters,
            pages=pages,
            cookie=cookie,
            on_page=on_page,
        )
    except crawler.LoginRequiredError as error:
        return {"ok": False, "error": "login_required", "message": str(error),
                "first_url": crawler.build_list_url(
                    district=filters["district"], page=1, price_tier=filters["priceTier"],
                    rooms=filters["rooms"], rent_type=filters["rentType"],
                    keyword=filters["keyword"], sort=filters["sort"])}
    except crawler.CaptchaError as error:
        return {"ok": False, "error": "captcha", "message": str(error)}
    except crawler.RiskControlError as error:
        return {"ok": False, "error": "risk_control", "message": str(error)}
    except Exception as error:
        return {"ok": False, "error": "crawl_failed", "message": f"{type(error).__name__}: {error}"}

    return {
        "ok": True,
        "fetched": summary["fetched"],
        "saved": len(saved_urls),
        "pages": summary["pages"],
    }


def read_public_file(path):
    if path == "/":
        target = PUBLIC_DIR / "index.html"
    else:
        relative = unquote(path).lstrip("/")
        target = PUBLIC_DIR / relative

    resolved = target.resolve()
    if not str(resolved).startswith(str(PUBLIC_DIR.resolve())) or not resolved.is_file():
        return None, None

    content_type = mimetypes.guess_type(resolved.name)[0] or "application/octet-stream"
    if content_type.startswith("text/") or content_type in ("application/javascript", "application/json"):
        content_type = f"{content_type}; charset=utf-8"
    return resolved.read_bytes(), content_type


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        print("[%s] %s" % (self.log_date_time_string(), format % args))

    def send_cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def send_json(self, status, data):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_cors_headers()
        self.end_headers()
        self.wfile.write(body)

    def send_static(self, status, body, content_type):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_cors_headers()
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_cors_headers()
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/api/houses":
            self.send_json(200, {"ok": True, "houses": list_houses(parse_qs(parsed.query))})
            return
        if path == "/api/stats":
            self.send_json(200, {"ok": True, **stats()})
            return
        if path == "/api/meta":
            self.send_json(200, {
                "ok": True,
                "districts": crawler.DISTRICTS,
                "priceTiers": crawler.PRICE_TIERS,
                "roomsOptions": crawler.ROOMS_OPTIONS,
                "rentTypes": [
                    {"value": "", "label": "不限"},
                    {"value": "whole", "label": "整租"},
                    {"value": "shared", "label": "合租"},
                ],
                "sorts": [{"value": key, "label": value} for key, value in crawler.SORTS.items()],
                "hasCookie": bool(read_saved_cookie()),
            })
            return
        if path == "/health":
            self.send_json(200, {"ok": True, "db": str(DB_PATH), "jsonl": str(JSONL_PATH)})
            return

        body, content_type = read_public_file(path)
        if body is not None:
            self.send_static(200, body, content_type)
            return

        self.send_json(404, {"ok": False, "error": "not found"})

    def do_POST(self):
        path = urlparse(self.path).path
        if path not in ("/api/houses", "/api/crawl", "/api/vision"):
            self.send_json(404, {"ok": False, "error": "not found"})
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
        except Exception as error:
            self.send_json(400, {"ok": False, "error": f"invalid json: {error}"})
            return

        try:
            if path == "/api/houses":
                if isinstance(payload, list):
                    payloads = payload
                elif isinstance(payload.get("houses"), list):
                    payloads = payload["houses"]
                elif isinstance(payload.get("house"), dict):
                    payloads = [payload["house"]]
                else:
                    payloads = [payload]
                saved, records = save_houses(payloads)
                self.send_json(200, {"ok": True, "saved": saved, "houses": records})
            elif path == "/api/crawl":
                result = run_crawl(payload if isinstance(payload, dict) else {})
                self.send_json(200 if result.get("ok") else 409, result)
            else:
                self.handle_vision(payload if isinstance(payload, dict) else {})
        except Exception as error:
            self.send_json(400, {"ok": False, "error": str(error)})


    def handle_vision(self, payload):
        """视觉评估：取房源照片（库内或抓详情页）→ 视觉模型打分标注 → 存 vision_report。"""
        url = str(payload.get("url") or "")
        house_id = payload.get("house_id")
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            if url:
                row = conn.execute("SELECT * FROM houses WHERE url = ?", (url,)).fetchone()
            else:
                row = conn.execute("SELECT * FROM houses WHERE id = ?", (house_id,)).fetchone()
        if not row:
            self.send_json(404, {"ok": False, "error": "house not found"})
            return
        row = dict(row)
        images = json.loads(row.get("images") or "[]")
        if not images:
            cookie = read_saved_cookie()
            if not cookie:
                self.send_json(409, {"ok": False, "error": "no_images",
                                     "message": "库内无详情页照片，且无 Cookie 可抓详情页"})
                return
            try:
                html_text = crawler.fetch(row["url"], cookie=cookie,
                                          referer="https://hz.zu.ke.com/zufang/")
            except Exception as error:
                self.send_json(409, {"ok": False, "error": "detail_fetch_failed",
                                     "message": str(error)[:200]})
                return
            images = crawler.parse_detail_images(html_text)
            with sqlite3.connect(DB_PATH) as conn:
                conn.execute("UPDATE houses SET images = ? WHERE id = ?",
                             (json.dumps(images, ensure_ascii=False), row["id"]))
        if not images:
            self.send_json(409, {"ok": False, "error": "no_images",
                                 "message": "详情页未解析到照片"})
            return
        try:
            report = vision.analyze_images(images)
        except Exception as error:
            self.send_json(502, {"ok": False, "error": "vision_failed",
                                 "message": str(error)[:200]})
            return
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("UPDATE houses SET vision_report = ? WHERE id = ?",
                         (json.dumps(report, ensure_ascii=False), row["id"]))
        self.send_json(200, {"ok": True, "report": report, "images": len(images)})


def main():
    ensure_storage()
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"租房本地服务已启动: http://{HOST}:{PORT}")
    print(f"SQLite: {DB_PATH}")
    print(f"JSONL:  {JSONL_PATH}")
    server.serve_forever()


if __name__ == "__main__":
    main()
