#!/usr/bin/env python3
"""Mac 一键抓取：登录态 Cookie 只在本机使用，不进对话/不入仓库。

城市与站点零硬编码：读取 local-service/site_config（env > data/site.json > 默认）。
区域清单优先 site.json 预设，否则匿名抓首页动态发现（parse_districts）。

用法：
  1) 浏览器登录目标站点后，F12 → Network → 刷新 → 第一个文档请求 →
     Request Headers 里整行 Cookie 的值存成一行：~/Downloads/ke_cookie.txt
  2) python3 mac_crawl.py [每区页数, 默认2] [居室token, 默认1,2,3]
"""
import json
import os
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "01_house_capture" / "local-service"))
import crawler  # noqa: E402
import site_config  # noqa: E402

COOKIE_FILE = Path(os.environ.get("RENTAL_COOKIE_FILE",
                                  str(Path.home() / "Downloads" / "ke_cookie.txt")))
OUT = Path(os.environ.get("RENTAL_OUT", str(Path.home() / "Downloads" / "houses_crawl.jsonl")))
PAGES = int(sys.argv[1]) if len(sys.argv) > 1 else 2
ROOMS = [int(x) for x in sys.argv[2].split(",")] if len(sys.argv) > 2 else [1, 2, 3]


def discover_districts():
    preset = site_config.districts()
    if preset:
        return [(d["slug"], d["name"]) for d in preset]
    html = crawler.fetch(crawler.base_url() + site_config.list_path())
    return [(d["slug"], d["name"]) for d in crawler.parse_districts(html)[:24]]


def main():
    if not COOKIE_FILE.is_file():
        sys.exit(f"缺少 Cookie 文件：{COOKIE_FILE}（见脚本头部说明）")
    cookie = COOKIE_FILE.read_text(encoding="utf-8").strip()
    districts = discover_districts()
    print("city:", site_config.city_name() or "configured",
          "| districts:", len(districts), flush=True)
    seen, out = set(), []
    for slug, name in districts:
        for rooms in ROOMS:
            for page in range(1, PAGES + 1):
                url = crawler.build_list_url(district=slug, rooms=rooms, page=page)
                try:
                    html = crawler.fetch(url, cookie=cookie,
                                         referer=crawler.base_url() + site_config.list_path())
                except Exception as e:
                    print(f"  {name} l{rooms} p{page} ERR {type(e).__name__}", flush=True)
                    continue
                houses = crawler.parse_list_page(html)["houses"]
                new = [h for h in houses if h["url"] not in seen]
                seen.update(h["url"] for h in new)
                out.extend(new)
                print(f"  {name} l{rooms} p{page}: +{len(new)} (累计 {len(out)})", flush=True)
                time.sleep(2 + random.random() * 2)
    with OUT.open("w", encoding="utf-8") as f:
        for h in out:
            f.write(json.dumps(h, ensure_ascii=False) + "\n")
    print(f"\n完成：{len(out)} 套 → {OUT}")


if __name__ == "__main__":
    main()
