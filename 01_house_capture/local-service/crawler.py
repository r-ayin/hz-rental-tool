"""贝壳租房（hz.zu.ke.com）列表页抓取与解析模块。

纯标准库实现（urllib + re），无第三方依赖。

站点约束（2026-09 实测）：
- `/zufang/` 首页可匿名访问（约 30 条/页）。
- 分页 / 区域筛选 / 关键词检索 / 详情页均要求登录态（返回 ke-passport 登录页），
  此时抛出 LoginRequiredError；调用方可提供浏览器 Cookie 后重试，
  或改用浏览器扩展在用户已登录的页面内采集。
"""

from urllib.parse import quote
from urllib.request import Request, urlopen
import html as html_module
import re

BASE_URL = "https://hz.zu.ke.com"
LIST_PATH = "/zufang/"
DEFAULT_TIMEOUT = 20
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)

# 行政区（slug 实测自站点筛选栏；注意西湖区的 slug 是 xihuqu4）
DISTRICTS = [
    {"slug": "shangchengqu", "name": "上城区"},
    {"slug": "gongshuqu", "name": "拱墅区"},
    {"slug": "xihuqu4", "name": "西湖区"},
    {"slug": "binjiangqu", "name": "滨江区"},
    {"slug": "xiaoshanqu", "name": "萧山区"},
    {"slug": "yuhangqu", "name": "余杭区"},
    {"slug": "linpingqu", "name": "临平区"},
    {"slug": "qiantangqu", "name": "钱塘区"},
    {"slug": "fuyangqu", "name": "富阳区"},
    {"slug": "linanqu", "name": "临安区"},
    {"slug": "jiandeshi", "name": "建德市"},
    {"slug": "tongluxian", "name": "桐庐县"},
    {"slug": "chunanxian", "name": "淳安县"},
    {"slug": "hainingshi", "name": "海宁市"},
]

# 价格档位（rp token 实测自站点筛选栏）
PRICE_TIERS = [
    {"tier": 1, "label": "≤1000元", "min": None, "max": 1000},
    {"tier": 2, "label": "1000-1500元", "min": 1000, "max": 1500},
    {"tier": 3, "label": "1500-2000元", "min": 1500, "max": 2000},
    {"tier": 4, "label": "2000-2500元", "min": 2000, "max": 2500},
    {"tier": 5, "label": "2500-3500元", "min": 2500, "max": 3500},
    {"tier": 6, "label": "3500-5000元", "min": 3500, "max": 5000},
    {"tier": 7, "label": "5000-10000元", "min": 5000, "max": 10000},
    {"tier": 8, "label": "≥10000元", "min": 10000, "max": None},
]

# 居室数（l token 实测自站点筛选栏：l0=一居 l1=两居 l2=三居 l3=四居+）
ROOMS_OPTIONS = [
    {"value": 0, "label": "一居"},
    {"value": 1, "label": "两居"},
    {"value": 2, "label": "三居"},
    {"value": 3, "label": "四居+"},
]

# 出租方式（rt token 实测自站点筛选栏）
RENT_TYPES = {
    "whole": {"token": "rt200600000001", "label": "整租"},
    "shared": {"token": "rt200600000002", "label": "合租"},
}

# 排序 token
SORTS = {
    "": "综合排序",
    "rco11": "最新上架",
    "rco21": "价格排序",
}


class LoginRequiredError(RuntimeError):
    """目标页面返回了贝壳登录页（匿名请求触发了登录墙/风控）。"""


def build_list_url(district="", page=1, price_tier=None, rooms=None,
                   rent_type="", keyword="", sort=""):
    """按筛选条件构造 hz.zu.ke.com 列表页 URL。

    token 拼接顺序遵循站点惯例：[区域]/[pg页码][rt方式][rp价格][l居室][排序][rs关键词]/
    """
    path = LIST_PATH
    if district:
        path += f"{district}/"

    tokens = ""
    if page and int(page) > 1:
        tokens += f"pg{int(page)}"
    if rent_type and rent_type in RENT_TYPES:
        tokens += RENT_TYPES[rent_type]["token"]
    if price_tier:
        tokens += f"rp{int(price_tier)}"
    if rooms is not None and rooms != "":
        tokens += f"l{int(rooms)}"
    if sort and sort in SORTS:
        tokens += sort
    if keyword:
        tokens += "rs" + quote(str(keyword).strip())
    if tokens:
        path += tokens + "/"
    return BASE_URL + path


def is_login_page(html_text):
    """判断响应是否为贝壳 passport 登录页。"""
    head = (html_text or "")[:4000]
    return "ke-passport" in head and "<title>登录</title>" in head


def fetch(url, cookie="", timeout=DEFAULT_TIMEOUT):
    """抓取页面 HTML；命中登录墙抛 LoginRequiredError。"""
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Referer": BASE_URL + LIST_PATH,
    }
    if cookie:
        headers["Cookie"] = cookie.strip()
    request = Request(url, headers=headers)
    with urlopen(request, timeout=timeout) as response:
        html_text = response.read().decode("utf-8", errors="replace")
    if is_login_page(html_text):
        raise LoginRequiredError(
            "页面要求登录（贝壳对分页/筛选/详情页有登录墙）。"
            "请在 local-service/data/cookie.txt 或检索面板中提供已登录浏览器的 Cookie，"
            "或改用浏览器扩展在已登录页面内采集。"
        )
    return html_text


def _unescape(text):
    return html_module.unescape(text or "")


def _strip_tags(fragment):
    return re.sub(r"<[^>]+>", "", fragment or "")


def _normalize_line(value):
    return re.sub(r"\s+", " ", _unescape(value or "")).strip()


def _search(pattern, text, group=1, default=""):
    match = re.search(pattern, text, re.S)
    return _normalize_line(match.group(group)) if match else default


def parse_list_page(html_text):
    """解析列表页 HTML，返回 {total, cur_page, total_page, houses: [...]}。"""
    total = int(_search(r'data-total="(\d+)"', html_text, default="0") or 0)
    cur_page = int(_search(r'data-curPage="?(\d+)"?', html_text, default="1") or 1)
    total_page = int(_search(r'data-totalPage="?(\d+)"?', html_text, default="0") or 0)

    blocks = re.split(r'<div\s+class="content__list--item"', html_text)[1:]
    houses = []
    for block in blocks:
        try:
            house = parse_list_item(block)
        except Exception:
            continue
        if house and house.get("url"):
            houses.append(house)
    return {
        "total": total,
        "cur_page": cur_page,
        "total_page": total_page,
        "houses": houses,
    }


def parse_list_item(block):
    """解析单个 content__list--item 块为房源 dict。"""
    href = _search(r'href="(/(?:zufang|apartment)/[A-Za-z0-9]+\.html)"', block)
    if not href:
        return None

    title = _search(
        r'content__list--item--title[^>]*>\s*<a[^>]*>(.*?)</a>', block
    )
    house_code = _search(r'data-house_code="([^"]+)"', block)
    bu_desc = _search(r'data-bu_desc="([^"]*)"', block)

    # 出租方式：标题前缀（整租·/合租·/独栋·等）
    rent_type = ""
    if "·" in title:
        prefix = title.split("·", 1)[0].strip()
        if prefix in ("整租", "合租", "独栋", "公寓"):
            rent_type = prefix
    if not title:
        title = _unescape(bu_desc)

    # 价格：普通房源 "2800"，集中式公寓可能是区间 "3960-4320"
    rent_text = _search(r'content__list--item-price[^>]*>\s*<em>([\d.\-]+)</em>', block)
    rent_monthly = None
    if rent_text:
        first_number = re.match(r"[\d.]+", rent_text)
        if first_number:
            rent_monthly = int(float(first_number.group(0)))

    district, bizcircle, community = "", "", ""
    area_sqm = None
    orientation = ""
    layout = ""
    floor_desc = ""

    des_match = re.search(
        r'<p class="content__list--item--des">(.*?)</p>', block, re.S
    )
    if des_match:
        des = des_match.group(1)
        links = re.findall(r'<a[^>]*href="/zufang/[^"]*"[^>]*>([^<]+)</a>', des)
        links = [_normalize_line(item) for item in links if _normalize_line(item)]
        if len(links) >= 1:
            district = links[0]
        if len(links) >= 2:
            bizcircle = links[1]
        if len(links) >= 3:
            community = links[2]

        # 去掉链接后按 <i>/</i> 分隔提取 面积/朝向/户型/楼层
        remainder = re.sub(r"<a[^>]*>.*?</a>", "", des, flags=re.S)
        remainder = re.sub(r'<span class="hide">', " ", remainder)
        parts = [_normalize_line(_strip_tags(part)) for part in re.split(r"<i>/</i>", remainder)]
        parts = [part for part in parts if part]
        for part in parts:
            if re.search(r"\d+(\.\d+)?㎡", part) and area_sqm is None:
                number = re.search(r"(\d+(?:\.\d+)?)㎡", part)
                area_sqm = float(number.group(1))
            elif re.match(r"^\d+室", part) and not layout:
                layout = part
            elif ("楼层" in part or re.search(r"（\d+层）|\(\d+层\)", part)) and not floor_desc:
                floor_desc = part
            elif len(part) <= 4 and re.match(r"^[东南西北]+$", part) and not orientation:
                orientation = part

    # 公寓类广告位 des 无链接，小区名回退从标题提取（整租·小区名 ...）
    if not community and "·" in title:
        remainder_title = title.split("·", 1)[1].strip()
        community = remainder_title.split(" ", 1)[0].strip()

    tags = [
        _normalize_line(tag)
        for tag in re.findall(r'content__item__tag--[a-z_0-9]+"[^>]*>([^<]+)</i>', block)
    ]
    tags = [tag for tag in tags if tag]

    deposit = ""
    for tag in tags:
        if tag.startswith("押"):
            deposit = tag
            break

    brand = _search(r'<span class="brand">\s*(.*?)\s*</span>', block)
    maintain_time = _search(r'content__list--item--time[^"]*"[^>]*>([^<]+)<', block)
    image = _search(r'data-src="(https?://[^"]+)"', block) or _search(r'<img[^>]*src="(https?://[^"]+)"', block)

    return {
        "source": "ke",
        "url": BASE_URL + href,
        "house_code": house_code,
        "title": title,
        "rent_type": rent_type,
        "community": community,
        "district": district,
        "bizcircle": bizcircle,
        "area_sqm": area_sqm,
        "orientation": orientation,
        "layout": layout,
        "floor_desc": floor_desc,
        "rent_monthly": rent_monthly,
        "rent_text": rent_text,
        "deposit": deposit,
        "tags": tags,
        "brand": brand,
        "image": image,
        "maintain_time": maintain_time,
        "description": "",
    }


def crawl(filters=None, pages=1, cookie="", timeout=DEFAULT_TIMEOUT,
          sleep_seconds=1.5, on_page=None):
    """按条件抓取多页列表并返回汇总。

    filters: {district, page(起始页), priceTier, rooms, rentType, keyword, sort}
    on_page(page_number, result): 每页回调，便于上层入库/上报进度。
    """
    filters = filters or {}
    start_page = max(1, int(filters.get("page") or 1))
    pages = max(1, min(int(pages or 1), 30))

    summary = {"fetched": 0, "houses": [], "pages": []}
    for offset in range(pages):
        page = start_page + offset
        url = build_list_url(
            district=filters.get("district") or "",
            page=page,
            price_tier=filters.get("priceTier") or filters.get("price_tier"),
            rooms=filters.get("rooms") if filters.get("rooms") not in (None, "") else None,
            rent_type=filters.get("rentType") or filters.get("rent_type") or "",
            keyword=filters.get("keyword") or "",
            sort=filters.get("sort") or "",
        )
        html_text = fetch(url, cookie=cookie, timeout=timeout)
        result = parse_list_page(html_text)
        result["url"] = url
        result["page"] = page
        summary["fetched"] += len(result["houses"])
        summary["houses"].extend(result["houses"])
        summary["pages"].append({"page": page, "count": len(result["houses"]), "url": url})
        if on_page:
            on_page(page, result)
        total_page = result.get("total_page") or 0
        if total_page and page >= min(total_page, 100):
            break
        if offset + 1 < pages and sleep_seconds:
            import time
            time.sleep(sleep_seconds)
    return summary
