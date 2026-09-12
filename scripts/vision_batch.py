#!/usr/bin/env python3
"""批量视觉评估：参数为 urls 的 json 文件（或每行一个 url 的文本），逐个调 /api/vision。"""
import json
import os
import sys
import time
import urllib.request

API = (os.environ.get("RENTAL_API_BASE") or "http://127.0.0.1:8765") + "/api/vision"


def main():
    path = sys.argv[1]
    raw = open(path, encoding="utf-8").read()
    try:
        data = json.loads(raw)
        urls = [x["url"] if isinstance(x, dict) else x for x in data]
    except json.JSONDecodeError:
        urls = [line.strip() for line in raw.splitlines() if line.strip()]
    for url in urls:
        req = urllib.request.Request(API, data=json.dumps({"url": url}).encode(),
                                     headers={"Content-Type": "application/json"})
        try:
            resp = json.loads(urllib.request.urlopen(req, timeout=180).read())
        except Exception as e:
            print(f"FAIL {url} {type(e).__name__} {e}", flush=True)
            continue
        if resp.get("ok"):
            r = resp["report"]
            print(f"OK {r.get('newness')}/{r.get('decoration')}/{r.get('cleanliness')} "
                  f"厨:{r.get('kitchen')} 卫:{r.get('bathroom')} 窗:{'/'.join(r.get('window_view') or []) or '未见'} "
                  f"| {r.get('summary')} | {url}", flush=True)
        else:
            print(f"ERR {resp.get('error')} {resp.get('message', '')[:80]} | {url}", flush=True)
        time.sleep(1)


if __name__ == "__main__":
    main()
