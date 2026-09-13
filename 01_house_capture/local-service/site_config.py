"""站点与城市配置层：零硬编码。

优先级：环境变量 > data/site.json > 内置默认（仅为可运行的示例默认，均可覆盖）。

环境变量：
  RENTAL_CITY_SLUG          城市 slug（用于 source_url_pattern 的 {city}）
  RENTAL_CITY_NAME          城市名（用于 Overpass 地铁站/地理编码查询）
  RENTAL_SOURCE_URL_PATTERN 站点根 URL 模式，含 {city} 占位符
  RENTAL_LIST_PATH          列表页路径
  RENTAL_COMMUTE_DEST       通勤终点："lat,lon" 或站点/园区名称（运行时 geocode）
  RENTAL_AMAP_CITY_CODE     高德城市码（geocode 兜底通道，可选）

data/site.json 示例见 docs/site.example.json（cp 到 data/site.json 启用城市预设）。
"""

import json
import os
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
_CACHE = None

DEFAULTS = {
    "city_slug": "hz",
    "city_name": "",
    "source_url_pattern": "https://{city}.zu.ke.com",
    "list_path": "/zufang/",
    "commute_destination": "",
    "city_bbox": None,
    "amap_city_code": "",
    "districts": [],
}


def _load():
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    cfg = dict(DEFAULTS)
    path = DATA_DIR / "site.json"
    if path.is_file():
        try:
            cfg.update(json.loads(path.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            pass
    env = os.environ
    mapping = {
        "city_slug": "RENTAL_CITY_SLUG",
        "city_name": "RENTAL_CITY_NAME",
        "source_url_pattern": "RENTAL_SOURCE_URL_PATTERN",
        "list_path": "RENTAL_LIST_PATH",
        "commute_destination": "RENTAL_COMMUTE_DEST",
        "amap_city_code": "RENTAL_AMAP_CITY_CODE",
    }
    for key, env_key in mapping.items():
        if env.get(env_key):
            cfg[key] = env[env_key]
    _CACHE = cfg
    return cfg


def reload():
    """site.json 或环境变量变更后调用。"""
    global _CACHE
    _CACHE = None
    return _load()


def base_url():
    return _load()["source_url_pattern"].format(city=_load()["city_slug"])


def list_path():
    return _load()["list_path"]


def referer():
    return base_url() + list_path()


def districts():
    """静态区域表（可选预设）；为空时前端/服务端走 /api/discover 动态发现。"""
    return _load()["districts"] or []


def city_name():
    return _load()["city_name"]


def city_bbox():
    return _load()["city_bbox"]


def commute_destination():
    return _load()["commute_destination"]


def amap_city_code():
    return _load()["amap_city_code"]
