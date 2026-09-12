"""视觉评估模块：用视觉模型（默认 idealab 网关 qwen3.8-flash）对房源照片打分与标注。

评估维度：新旧、装修、整洁度（1-5 分）；厨房（明厨/暗厨/未见）；卫生间（明卫/暗卫/未见）；
窗外景观（树景/城景/无视野）；亮点/问题清单；一句话总评。

配置（环境变量可覆盖）：
  VISION_API_BASE  默认 https://idealab.alibaba-inc.com/api/code/v1/messages
  VISION_API_KEY   默认读 ~/.idealab.env 的 IDEALAB_AK
  VISION_MODEL     默认 qwen3.8-flash
"""

import base64
import json
import os
import re
import ssl
import urllib.request

DEFAULT_BASE = "https://idealab.alibaba-inc.com/api/code/v1/messages"
DEFAULT_MODEL = "qwen3.8-flash"
MAX_PHOTOS = 6
REFERER = "https://hz.zu.ke.com/"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

PROMPT = """你是租房照片评估专家。观察这些房源室内照片，输出严格 JSON（不要 markdown 代码块）：
{"newness": 1-5整数(5=很新/近精装, 1=很旧/破败), "decoration": 1-5整数(装修档次),
"cleanliness": 1-5整数, "kitchen": "明厨|暗厨|未见", "bathroom": "明卫|暗卫|未见",
"window_view": ["树景","城景","无视野"] 的子集(看不到给空列表),
"highlights": ["最多4条亮点, 如: 朝南飘窗/开放式厨房/新装木地板"],
"issues": ["最多4条问题, 如: 墙面发黄/老式吊灯/无阳台"],
"summary": "一句话总评"}
只依据照片可见证据判断，看不到的一律填"未见"或空列表。"""


def load_api_key():
    key = os.environ.get("VISION_API_KEY")
    if key:
        return key
    env_path = os.path.expanduser("~/.idealab.env")
    try:
        with open(env_path) as f:
            for line in f:
                if line.startswith("IDEALAB_AK="):
                    return line.strip().split("=", 1)[1]
    except OSError:
        pass
    return ""


def _ssl_context():
    ctx = ssl.create_default_context()
    ctx.verify_flags &= ~ssl.VERIFY_X509_STRICT
    return ctx


def upgrade_image_url(url):
    """把缩略图后缀升级为 750 宽，保证视觉模型看得清。"""
    base = url.split("!")[0]
    base = re.sub(r"\.\d+x\d+\.jpg$", ".jpg", base)
    return base + "!m_fill,w_750,h_560,l_fbk,o_auto"


def download_image(url, timeout=20):
    req = urllib.request.Request(upgrade_image_url(url),
                                 headers={"User-Agent": UA, "Referer": REFERER})
    with urllib.request.urlopen(req, timeout=timeout, context=_ssl_context()) as resp:
        return resp.read()


def _extract_json(text):
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        raise ValueError("模型未返回 JSON: " + text[:200])
    return json.loads(match.group(0))


def analyze_images(image_urls, max_photos=MAX_PHOTOS):
    """下载照片并调用视觉模型，返回结构化评估 dict。"""
    blocks = []
    used = []
    for url in image_urls[:max_photos]:
        try:
            data = download_image(url)
        except Exception:
            continue
        if len(data) < 2000:
            continue
        blocks.append({"type": "image", "source": {
            "type": "base64", "media_type": "image/jpeg",
            "data": base64.b64encode(data).decode()}})
        used.append(url)
    if not blocks:
        raise ValueError("没有可下载的照片")

    payload = {
        "model": os.environ.get("VISION_MODEL") or DEFAULT_MODEL,
        "max_tokens": 800,
        "thinking": {"type": "disabled"},
        "messages": [{"role": "user", "content": blocks + [
            {"type": "text", "text": PROMPT}]}],
    }
    req = urllib.request.Request(
        os.environ.get("VISION_API_BASE") or DEFAULT_BASE,
        data=json.dumps(payload).encode(),
        headers={"x-api-key": load_api_key(), "anthropic-version": "2023-06-01",
                 "Content-Type": "application/json"})
    ctx = _ssl_context()
    try:
        with urllib.request.urlopen(req, timeout=150, context=ctx) as resp:
            result = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:300]
        if "CERTIFICATE" in body or e.code >= 500:
            ctx2 = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            ctx2.check_hostname = False
            ctx2.verify_mode = ssl.CERT_NONE
            with urllib.request.urlopen(req, timeout=150, context=ctx2) as resp:
                result = json.loads(resp.read().decode())
        else:
            raise ValueError(f"视觉网关 HTTP {e.code}: {body}")
    text = " ".join(c.get("text", "") for c in result.get("content", [])
                    if c.get("type") == "text")
    report = _extract_json(text)
    report["photos_analyzed"] = len(used)
    report["model"] = result.get("model")
    return report
