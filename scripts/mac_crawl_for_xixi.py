#!/usr/bin/env python3
"""Mac 一键抓取：西溪通勤圈贝壳租房筛选页（需已登录 Cookie，Cookie 只在本机使用）。

用法：
  1) 浏览器登录 hz.zu.ke.com 后，F12 → Network → 刷新 → 点第一个文档请求 →
     复制 Request Headers 里整行 Cookie 的值，存成一行：~/Downloads/ke_cookie.txt
  2) python3 mac_crawl_for_xixi.py
  产出：~/Downloads/hz_houses_xixi.jsonl（交给 agent 做步行/通勤几何分析）
"""
import html as html_module
import json
import random
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE = "https://hz.zu.ke.com"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
COOKIE_FILE = Path.home() / "Downloads" / "ke_cookie.txt"
OUT = Path.home() / "Downloads" / "hz_houses_xixi.jsonl"

# 通勤圈：西湖/余杭/拱墅/滨江 × 两居/三居/四居+ × 前2页
TARGETS = [(d, l, pg) for d in ("xihuqu4", "yuhangqu", "gongshuqu", "binjiangqu")
           for l in (1, 2, 3) for pg in (1, 2)]


def url_for(district, rooms, page):
    tokens = (f"pg{page}" if page > 1 else "") + f"l{rooms}"
    return f"{BASE}/zufang/{district}/{tokens}/"


def fetch(url, cookie):
    headers = {"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9",
               "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
               "Sec-Fetch-Mode": "navigate", "Sec-Fetch-Dest": "document",
               "Referer": BASE + "/zufang/", "Cookie": cookie}
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=25) as resp:
        return resp.read().decode("utf-8", "replace")


def un(v):
    return html_module.unescape(v or "")


def strip_tags(s):
    return re.sub(r"<[^>]+>", "", s or "")


def norm(v):
    return re.sub(r"\s+", " ", un(v)).strip()


def parse_item(block):
    href = re.search(r'href="(/(?:zufang|apartment)/[A-Za-z0-9]+\.html)"', block)
    if not href:
        return None
    title_m = re.search(r'content__list--item--title[^>]*>\s*<a[^>]*>(.*?)</a>', block, re.S)
    title = norm(title_m.group(1)) if title_m else ""
    rent_m = re.search(r'content__list--item-price[^>]*>\s*<em>([\d.\-]+)</em>', block)
    rent = int(float(re.match(r"[\d.]+", rent_m.group(1)).group(0))) if rent_m and re.match(r"[\d.]+", rent_m.group(1)) else None
    district = bizcircle = community = ""
    area = None
    orientation = layout = floor = ""
    des = re.search(r'<p class="content__list--item--des">(.*?)</p>', block, re.S)
    if des:
        links = [norm(x) for x in re.findall(r'<a[^>]*href="/zufang/[^"]*"[^>]*>([^<]+)</a>', des.group(1)) if norm(x)]
        district, bizcircle, community = (links + ["", "", ""])[:3]
        rem = re.sub(r"<a[^>]*>.*?</a>", "", des.group(1), flags=re.S)
        rem = re.sub(r'<span class="hide">', " ", rem)
        for part in [norm(strip_tags(p)) for p in re.split(r"<i>/</i>", rem)]:
            if not part:
                continue
            m = re.search(r"([\d.]+)㎡", part)
            if m and area is None:
                area = float(m.group(1))
            elif re.match(r"^\d+室", part) and not layout:
                layout = part
            elif ("楼层" in part or re.search(r"（\d+层）", part)) and not floor:
                floor = part
            elif re.match(r"^[东南西北]{1,4}$", part) and not orientation:
                orientation = part
    if not community and "·" in title:
        community = title.split("·", 1)[1].strip().split(" ", 1)[0]
    rent_type = title.split("·", 1)[0].strip() if "·" in title else ""
    tags = [norm(t) for t in re.findall(r'content__item__tag--[a-z_0-9]+"[^>]*>([^<]+)</i>', block) if norm(t)]
    img = re.search(r'data-src="(https?://[^"]+)"', block)
    return {
        "url": BASE + href.group(1), "title": title,
        "rent_type": rent_type if rent_type in ("整租", "合租", "独栋", "公寓") else "",
        "community": community, "district": district, "bizcircle": bizcircle,
        "area_sqm": area, "orientation": orientation, "layout": layout, "floor_desc": floor,
        "rent_monthly": rent, "deposit": next((t for t in tags if t.startswith("押")), ""),
        "tags": tags, "image": img.group(1) if img else "",
        "maintain_time": norm((re.search(r'content__list--item--time[^>]*>([^<]+)<', block) or ["", ""])[1]),
    }


def parse_page(html_text):
    return [h for h in (parse_item(b) for b in re.split(r'<div\s+class="content__list--item"', html_text)[1:]) if h and h["url"]]


def main():
    if not COOKIE_FILE.is_file():
        sys.exit(f"缺少 Cookie 文件：{COOKIE_FILE}（见脚本头部说明）")
    cookie = COOKIE_FILE.read_text(encoding="utf-8").strip()
    seen, out = set(), []
    for district, rooms, page in TARGETS:
        url = url_for(district, rooms, page)
        for attempt in range(3):
            try:
                html_text = fetch(url, cookie)
                break
            except urllib.error.HTTPError as e:
                if e.code in (403, 429):
                    print(f"!! 风控 {e.code}，停止。已存 {len(out)} 条"); write(out); sys.exit(1)
                time.sleep(3 * (attempt + 1)); continue
            except Exception as e:
                time.sleep(3 * (attempt + 1)); continue
        else:
            print(f"-- 失败跳过 {url}"); continue
        if "ke-passport" in html_text[:4000] and "<title>登录</title>" in html_text[:4000]:
            print("!! Cookie 无效（仍是登录页），请重新复制。已存", len(out), "条"); write(out); sys.exit(1)
        houses = parse_page(html_text)
        new = [h for h in houses if h["url"] not in seen]
        seen.update(h["url"] for h in new)
        out.extend(new)
        print(f"ok {url} +{len(new)} (累计 {len(out)})")
        time.sleep(2 + random.random() * 2.5)
    write(out)
    print(f"\n完成：{len(out)} 条 → {OUT}")


def write(out):
    with OUT.open("w", encoding="utf-8") as f:
        for h in out:
            f.write(json.dumps(h, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
