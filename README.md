# 杭州租房工具（贝壳 hz.zu.ke.com）

> 由 [fde-job-search / FDE_JobSearch](https://github.com/Guuumiho/FDE_JobSearch)（BOSS 直聘 JD 采集 MVP）全面重构而来：
> 同样的「浏览器扩展采集 + 本地服务入库 + 画廊前端」架构，检索对象换成 **贝壳找房·杭州租房（hz.zu.ke.com/zufang）**。

![房源画廊](01_house_capture/docs/screenshot.png)

## 它能做什么

- **在线检索**：本地服务直接抓取 `hz.zu.ke.com/zufang` 列表页（区域/价格档/居室/整租合租/关键词/排序/多页），解析后入库；
- **浏览器扩展采集**：在你已登录的贝壳页面里，列表页「采集本页 / 自动翻页」、详情页「保存房源 / 导出TXT」；
- **本地房源库**：SQLite + JSONL 双写，URL 去重（重复抓取自动更新而非新增）；
- **画廊前端**：卡片墙（图片/月租/标签/户型面积朝向楼层）、五维筛选、关键词搜索、四种排序、详情弹窗、区域均价统计、双主题。

## 架构

```mermaid
graph LR
  A["Firefox 扩展<br/>content.js 浮动按钮"] -->|POST /api/houses| C
  B["服务端爬虫 crawler.py<br/>hz.zu.ke.com 列表页"] --> C["server.py :8765<br/>SQLite houses + JSONL"]
  C --> D["画廊前端<br/>筛选/搜索/排序/详情/在线检索"]
```

### 站点约束（2026-09 实测，重要）

| 页面 | 匿名访问 | 说明 |
|------|:--:|------|
| `/zufang/` 综合首页（30 条/页） | ✅ | 服务端爬虫默认入口 |
| 分页 `/zufang/pg2/`、区域/价格/居室/关键词筛选页 | ❌ 登录墙 | 需提供 Cookie（`data/cookie.txt` 或检索面板），或用扩展在已登录浏览器内采集 |
| 详情页 `/zufang/HZ*.html` | ❌ 登录页 | 仅扩展（用户浏览器内）可采集详情字段与描述 |

命中登录墙时服务端返回 `login_required` 并给出目标 URL 与建议；扩展路线不受影响。

### 筛选 URL 规则（实测）

`https://hz.zu.ke.com/zufang/[区域slug]/[pg页码][rt方式][rp价格档][l居室][排序][rs关键词]/`

- 区域：`shangchengqu` `gongshuqu` `xihuqu4`（注意西湖区 slug 带 4）`binjiangqu` `xiaoshanqu` `yuhangqu` `linpingqu` `qiantangqu` `fuyangqu` `linanqu` `jiandeshi` `tongluxian` `chunanxian` `hainingshi`
- 价格档：`rp1` ≤1000 … `rp8` ≥10000（8 档）
- 居室：`l0` 一居 / `l1` 两居 / `l2` 三居 / `l3` 四居+
- 方式：`rt200600000001` 整租 / `rt200600000002` 合租
- 排序：`rco11` 最新上架 / `rco21` 价格

## 快速开始

```bash
# 1. 启动本地服务（默认 http://127.0.0.1:8765，可用环境变量 RENTAL_PORT 改端口）
cd 01_house_capture/local-service
python3 server.py          # Windows: 双击 run.cmd 或 python server.py

# 2. 打开画廊
#    http://127.0.0.1:8765/

# 3.（可选）安装 Firefox 扩展：about:debugging → 此电脑 → 加载临时附加组件
#    选择 01_house_capture/firefox-house-capture/manifest.json
#    然后打开 hz.zu.ke.com/zufang，用浮动按钮采集
```

无第三方依赖：Python 标准库 + 原生 JS。

## API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/houses?q=&district=&rooms=&minRent=&maxRent=&rentType=&sort=` | 筛选后的房源列表（sort: updated/rent_asc/rent_desc/area_desc/area_asc） |
| POST | `/api/houses` | 入库：`{houses:[...]}` / `{house:{...}}` / 单个对象 / 数组，按 url upsert |
| POST | `/api/crawl` | 在线检索：`{district, priceTier, rooms, rentType, sort, keyword, pages, cookie?}` |
| GET | `/api/meta` | 筛选项元数据（区域/价格档/居室/方式/排序/Cookie 状态） |
| GET | `/api/stats` | 总数、均价、分区域统计 |
| GET | `/health` | 健康检查 |

## 目录结构

```text
hz-rental-tool/
└── 01_house_capture/
    ├── firefox-house-capture/      # Firefox 扩展（MV2）
    │   ├── manifest.json
    │   ├── background.js           # 转发 POST /api/houses、导出TXT下载
    │   └── content.js              # 列表页批量/翻页采集、详情页保存
    ├── local-service/
    │   ├── server.py               # HTTP 服务 + SQLite/JSONL 存储 + API
    │   ├── crawler.py              # hz.zu.ke.com 抓取/解析/URL 构造（纯标准库）
    │   ├── run.cmd / run.sh
    │   └── public/                 # 画廊前端（index.html + assets）
    ├── data/                       # houses.db / houses.jsonl / cookie.txt（gitignore）
    └── tests/
        ├── test_parser.py          # 解析器离线测试（9 用例）
        └── fixtures/               # 真实列表页样本
```

## 反检测与礼貌抓取

继承原仓库的核心思路（**在用户真实浏览器内采集**：真实登录态、真实指纹、真实 DOM 点击），
并为新增的服务端爬虫补齐防护层：

| 层 | 措施 |
|----|------|
| 请求头 | 真实桌面 UA + 完整 Sec-Fetch-* 导航头；同会话头部保持一致（不逐请求轮换，避免更可疑）；翻页携带上一页 Referer |
| 会话 | CookieJar 复用服务端下发的会话 Cookie（风控 token 等），贴近真实浏览器 |
| 节奏 | 页间隔 = 基础 1.5s + 0.5~2.5s 随机抖动；每 5 页额外"休息" 3~6s；单次上限 30 页；两次检索启动间隔 ≥5s；同一时刻仅一个检索任务（锁） |
| 失败策略 | 403/429 → `risk_control` 立即停（不硬撞）；5xx/网络错误 → 指数退避（2/4/8s+抖动）最多 3 次；登录墙 → `login_required`；人机验证 → `captcha` 立即停 |
| 扩展端 | 采集前模拟真人分段滚动阅读；翻页/提交间隔随机（humanDelay）；落到验证页自动停止自动翻页并提示；sessionStorage 跨页续采带剩余页数上限 |
| 图片/前端 | `referrerpolicy="no-referrer"` 绕过图床防盗链，且不向图床泄漏本页来源 |

原则：**被拦即停、给出可操作提示**，绝不静默重试或换端点硬撞；全量筛选检索优先走已登录浏览器扩展通道。

## 视觉评估（qwen3.8-flash）

对房源照片自动打分与标注：新旧/装修/整洁（1-5 分）、明厨/暗厨、明卫/暗卫、窗外景观（树景/城景/无视野）、亮点与问题清单、一句话总评。

- 触发：前端详情弹窗「视觉评估」区一键评分；或 `POST /api/vision {"url": ...}`；批量 `python3 scripts/vision_batch.py urls.txt`
- 照片来源：库内已有详情图，否则用已存 Cookie 抓详情页解析（`crawler.parse_detail_images`）
- 配置：`VISION_API_BASE` / `VISION_API_KEY` / `VISION_MODEL` 环境变量；默认 idealab Anthropic 网关 + `~/.idealab.env` 的 AK + `qwen3.8-flash`
- 结果存 `houses.vision_report`；模型只依据照片可见证据判断，房东传非实拍图（营业执照/二维码等）会明确标注无法评估

## 测试

```bash
cd 01_house_capture
python3 tests/test_parser.py
```

## 合规提示

- 仅供个人找房使用；抓取频率默认保守（页间隔 1.5s、单次上限 30 页）；
- 请遵守贝壳的服务条款与 robots 约定，勿用于商业再分发；
- Cookie 仅存本地 `data/cookie.txt`，不会上传任何第三方。
