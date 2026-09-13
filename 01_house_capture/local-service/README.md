# 一秒选房 · 本地服务

接收扩展采集的房源、提供服务端在线检索与视觉评估，数据双写到：

- `../data/houses.db`（SQLite）
- `../data/houses.jsonl`（追加日志）

## 启动

```bash
python3 server.py            # 或 run.cmd / run.sh；端口 RENTAL_PORT 可覆盖（默认 8765）
```

## 配置（零硬编码）

城市/站点/通勤点/区域见 `site_config.py`：环境变量 > `../data/site.json` > 默认。
示例预设：`cp ../docs/site.example.json ../data/site.json`。

## 端点

- `GET /api/houses?q=&district=&rooms=&minRent=&maxRent=&rentType=&sort=` 筛选列表
- `POST /api/houses` 入库（url upsert）
- `POST /api/crawl` 在线检索（护栏：60s 间隔/30 页日/10 页次）
- `GET /api/discover` 动态发现当前城市的区域筛选与总量
- `POST /api/vision` 视觉评估（模型端点 VISION_* 可配）
- `GET /api/meta` `/api/stats` `/health`
