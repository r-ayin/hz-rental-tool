#!/usr/bin/env python3
"""全国通用几何硬校验管线：DB 房源 → 硬筛 → 小区 geocode → 直线预筛 → Valhalla 步行/骑行路由 → 排名。

零硬编码：城市 bbox/通勤终点/高德码全部来自 site_config（env > data/site.json）或命令行参数。

用法示例：
  python3 geo_pipeline.py --dest "30.28,120.02" --bbox 29.95,119.55,30.60,120.75 --out /tmp/final.json
  python3 geo_pipeline.py --dest "某科技园地铁站" --city-name 你的城市 --out /tmp/final.json
"""
import argparse
import json
import math
import re
import sqlite3
import sys
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "01_house_capture" / "local-service"))
import site_config  # noqa: E402

UA = {"User-Agent": "rent-radar/1.1 (personal housing search)"}
OVERPASS = "https://overpass-api.de/api/interpreter"
VALHALLA = "https://valhalla1.openstreetmap.de/route"


def hav(a, b, c, d):
    r = 6371.0
    p1, p2 = math.radians(a), math.radians(c)
    dp, dl = math.radians(c - a), math.radians(d - b)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def overpass(query):
    req = urllib.request.Request(OVERPASS, data=("data=" + urllib.parse.quote(query)).encode(), headers=UA)
    with urllib.request.urlopen(req, timeout=90) as r:
        return json.loads(r.read().decode())


def valhalla(frm, to, costing):
    body = json.dumps({"locations": [{"lat": frm[0], "lon": frm[1]}, {"lat": to[0], "lon": to[1]}],
                       "costing": costing, "units": "kilometers"}).encode()
    req = urllib.request.Request(VALHALLA, data=body, headers={"Content-Type": "application/json", **UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        leg = json.loads(r.read().decode())["trip"]["legs"][0]["summary"]
    return leg["length"], leg["time"] / 60.0


def get_bbox(args):
    if args.bbox:
        return tuple(float(x) for x in args.bbox.split(","))
    if args.city_name:
        d = overpass(f'[out:json][timeout:60];rel["name"="{args.city_name}"]["boundary"="administrative"];out bb;')
        b = d["elements"][0]["bounds"]
        return (b["minlat"], b["minlon"], b["maxlat"], b["maxlon"])
    raise SystemExit("需要 --bbox 或 --city-name（或 site.json 的 city_bbox）")


def get_dest(args, bbox):
    dest = args.dest or site_config.commute_destination()
    if not dest:
        raise SystemExit("需要 --dest 或 site.json 的 commute_destination")
    if re.match(r"^-?\d+\.\d+,\s*-?\d+\.\d+$", dest):
        lat, lon = [float(x) for x in dest.split(",")]
        return (lat, lon), dest
    s, w, n, e = bbox
    d = overpass(f'[out:json][timeout:60];nwr["name"="{dest}"]({s},{w},{n},{e});out center 5;')
    for el in d["elements"]:
        lat = el.get("lat") or (el.get("center") or {}).get("lat")
        lon = el.get("lon") or (el.get("center") or {}).get("lon")
        if lat:
            return (lat, lon), dest
    raise SystemExit(f"无法 geocode 通勤终点: {dest}")


def stations(bbox):
    s, w, n, e = bbox
    d = overpass(f"[out:json][timeout:90];(node[railway=station][station=subway]({s},{w},{n},{e});"
                 f"node[public_transport=station][subway=yes]({s},{w},{n},{e}););out;")
    out, seen = [], set()
    for el in d["elements"]:
        name = (el.get("tags") or {}).get("name")
        if name and name not in seen and el.get("lat"):
            seen.add(name)
            out.append({"name": name, "lat": el["lat"], "lon": el["lon"]})
    return out


def geocode_communities(names, bbox, cache):
    missing = [n for n in names if n not in cache]
    s, w, n, e = bbox
    for i in range(0, len(missing), 60):
        chunk = missing[i:i + 60]
        q = "[out:json][timeout:90];(" + "".join(f'nwr["name"="{x}"]({s},{w},{n},{e});' for x in chunk) + ")out center tags;"
        prio = {"landuse": 0, "place": 1, "building": 2, "amenity": 3}
        for el in overpass(q)["elements"]:
            t = el.get("tags", {})
            nm = t.get("name")
            lat = el.get("lat") or (el.get("center") or {}).get("lat")
            lon = el.get("lon") or (el.get("center") or {}).get("lon")
            if nm in chunk and lat:
                rank = prio.get(next((k for k in prio if k in t), "x"), 5)
                if nm not in cache or rank < cache[nm][2]:
                    cache[nm] = (lat, lon, rank)
        time.sleep(1)
    return {k: (v[0], v[1]) for k, v in cache.items()}


def amap_geocode(name, code):
    params = urllib.parse.urlencode({"query_type": "TQUERY", "pagesize": "5", "pagenum": "1",
                                     "qii": "true", "cluster_state": "5", "need_utd": "true",
                                     "utd_sceneid": "1000", "div": "PC1000", "addr_poi_merge": "true",
                                     "is_classify": "true", "zoom": "11", "city": code, "keywords": name})
    req = urllib.request.Request("https://www.amap.com/service/poiInfo?" + params, headers={
        "User-Agent": UA["User-Agent"], "Referer": "https://www.amap.com/"})
    with urllib.request.urlopen(req, timeout=15) as r:
        data = json.loads(r.read().decode())
    for poi in (data.get("data") or {}).get("poi_list") or []:
        try:
            return float(poi["latitude"]), float(poi["longitude"])
        except (KeyError, TypeError, ValueError):
            continue
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(Path(__file__).resolve().parents[1] / "01_house_capture" / "data" / "houses.db"))
    ap.add_argument("--out", default="/tmp/geo_final.json")
    ap.add_argument("--dest", default="")
    ap.add_argument("--bbox", default=",".join(str(x) for x in site_config.city_bbox()) if site_config.city_bbox() else "")
    ap.add_argument("--city-name", default=site_config.city_name())
    ap.add_argument("--walk-max", type=float, default=1.0)
    ap.add_argument("--ebike-max", type=float, default=60.0)
    ap.add_argument("--ebike-kmh", type=float, default=20.0)
    ap.add_argument("--min-area", type=float, default=45.0)
    ap.add_argument("--threads", type=int, default=4)
    args = ap.parse_args()

    bbox = get_bbox(args)
    dest, dest_name = get_dest(args, bbox)
    sts = stations(bbox)
    print("stations:", len(sts), "| dest:", dest_name, dest, flush=True)

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    rows = [dict(r) for r in conn.execute("SELECT * FROM houses").fetchall()]
    cands = [h for h in rows
             if re.match(r"^[2-9]室[1-9]厅", h["layout"] or "")
             and h["rent_type"] == "整租" and "/apartment/" not in h["url"]
             and (h["area_sqm"] or 0) >= args.min_area]
    print("candidates:", len(cands), flush=True)

    cache = {}
    coords = geocode_communities(sorted({h["community"] for h in cands if h["community"]}), bbox, cache)
    code = site_config.amap_city_code()
    miss = [n for n in sorted({h["community"] for h in cands if h["community"]}) if n not in coords]
    if code and miss:
        for n in miss:
            pos = amap_geocode(n, code)
            if pos:
                coords[n] = pos
            time.sleep(0.35)
    print("geocoded:", len(coords), flush=True)

    todo = []
    for h in cands:
        pos = coords.get(h["community"])
        if not pos:
            continue
        if hav(pos[0], pos[1], dest[0], dest[1]) > args.ebike_kmh * (args.ebike_max / 60.0):
            continue
        near = min(sts, key=lambda s: hav(pos[0], pos[1], s["lat"], s["lon"]))
        if hav(pos[0], pos[1], near["lat"], near["lon"]) > args.walk_max:
            continue
        todo.append((h, pos, near))
    print("prefiltered:", len(todo), flush=True)

    results, lock = [], threading.Lock()
    q = list(todo)

    def worker():
        while True:
            with lock:
                if not q:
                    break
                h, pos, near = q.pop()
            try:
                walk, _ = valhalla(pos, (near["lat"], near["lon"]), "pedestrian")
                rec = {**h, "walk_km": round(walk, 3), "walk_station": near["name"], "pos": list(pos)}
                if walk <= args.walk_max:
                    bike, _ = valhalla(pos, dest, "bicycle")
                    rec["bike_km"] = round(bike, 2)
                    rec["ebike_min"] = round(bike / args.ebike_kmh * 60 + 4)
                    rec["pass"] = rec["ebike_min"] < args.ebike_max
                with lock:
                    results.append(rec)
            except Exception as e:
                with lock:
                    results.append({**h, "route_error": str(e)[:60]})
            time.sleep(0.2)

    ts = [threading.Thread(target=worker) for _ in range(args.threads)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    ok = [r for r in results if r.get("pass")]
    ok.sort(key=lambda r: -(r["area_sqm"] or 0) / (r["rent_monthly"] or 1))
    json.dump(results, open(args.out, "w"), ensure_ascii=False, indent=1)
    print("PASS:", len(ok), "/", len(results), "→", args.out, flush=True)
    for r in ok[:10]:
        print(f"{r['community']} {r['layout']} {r['area_sqm']}㎡ {r['rent_monthly']}元 "
              f"walk{r['walk_km']}km→{r['walk_station']} ebike{r['ebike_min']}min", flush=True)


if __name__ == "__main__":
    main()
