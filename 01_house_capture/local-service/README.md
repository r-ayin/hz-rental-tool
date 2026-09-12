# 租房本地服务

接收 Firefox 扩展采集的贝壳房源、提供服务端在线检索，数据双写到：

- `../data/houses.db`（SQLite）
- `../data/houses.jsonl`（追加日志）

## 启动

```bash
python3 server.py            # 或双击 run.cmd（Windows）/ ./run.sh
```

监听 `http://127.0.0.1:8765`；端口冲突时：`RENTAL_PORT=18765 python3 server.py`。

## 检查

- 健康：`/health`
- 房源：`/api/houses`（支持 q/district/rooms/minRent/maxRent/rentType/sort）
- 元数据：`/api/meta`　统计：`/api/stats`
- 在线检索：`POST /api/crawl`（见根 README 的参数表）

## Cookie（可选）

贝壳对分页/筛选/详情页有登录墙。把已登录浏览器的 Cookie 存到 `../data/cookie.txt`（单行），
或在画廊「在线检索」面板里粘贴，即可解锁全量筛选检索。
