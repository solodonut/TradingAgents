# Watchlist 批量分析 TUI —— 设计文档

- 日期：2026-07-02
- 状态：已批准，待写实现计划

## 背景与目标

用户希望有一个终端 TUI，能把 webUI 里配置好的**自选股列表（watchlist）**按顺序逐个跑完整分析，功能与 webUI 一致，且跑完的结果能在 webUI 历史页里看到。

现状要点（已核对代码）：

- webUI 用 `~/.tradingagents/webui.db`（`api/store.py`）。`analysis_runs` 表既是队列
  （`status='pending'`）也是历史；`watchlist` 表持久化自选股（仅 `ticker` + `name`，按 `position` 排序）。
- `api/scheduler.py::QueueScheduler` 串行启动 pending 任务；`api/runner.py::AnalysisRunner`
  跑 LangGraph 流并把结果写回同一个 store。单用户不变量：一次只跑一个。
- **分析设置（分析师/模型/研究深度/语言/日期/asset_type）不持久化到服务端**——webUI 前端
  持有这些设置，每次入队时随 `EnqueueRequest` 发送。所以 TUI 没有现成的“当前设置”可读，
  需要自己采集这批任务的设置。
- 现有 REST 接口已覆盖所需能力：`GET /api/watchlist`、`POST /api/queue`、`GET /api/queue`、
  `GET /api/analysis/{run_id}/status`、`GET /api/analysis/{run_id}/stream`（SSE）、`GET /api/history`。

## 决策（brainstorming 已确认）

1. **列表来源**：webUI 自选股 watchlist（读 `GET /api/watchlist`，保持 web 里的顺序）。
2. **运行架构**：方案 A —— TUI 做 **API 服务的瘦客户端**。通过 HTTP 入队、SSE 看进度，
   复用现有 scheduler/runner/store，零代码重复、无双调度器冲突。需要 API 服务先跑着
   （与 webUI 相同前提）。性能与“独立进程直跑”无差别（耗时由 LLM 主导、串行执行）。
3. **设置来源**：TUI 里交互选一次，复用 `cli/utils` 现有 questionary 选择器，选完对整个
   watchlist 应用同一套共享设置。
4. **实时看板**：混合看板（批次表 + 当前 run 的详情）。当前 run 详情**用轮询
   `GET /api/analysis/{run_id}/status`（telemetry 快照）**驱动，不订阅 SSE——避免
   单消费者 drain 抢占、连接时序 404、与 webUI 并存抢事件、以及后台线程的复杂度。
   代价：看不到辩论轮次细粒度（那只在 SSE 里），但换来纯轮询的健壮与简单。

## 整体流程

新增 Typer 子命令 `tradingagents batch`（名字可在实现时微调）。流程：

1. **探活**：`GET /api/watchlist` 探测服务可达。连不上则打印提示（“请先启动 `./dev.sh`
   或 `.venv/bin/python -m uvicorn api.main:app --port 8000`”）并退出（非零码）。
2. **拉列表**：取 watchlist（`[{ticker, name}]`，已按 web 顺序）。为空则提示去 webUI 添加后退出。
3. **交互选设置（一次）**：复用 `cli/utils`：
   - `select_analysts` / `select_research_depth` / `select_llm_provider` /
     `select_deep_thinking_agent` / `select_shallow_thinking_agent` / `ask_output_language` /
     `get_analysis_date`。
   - asset_type：对每个 ticker 用 `detect_asset_type(ticker)` 自动判定（不额外询问）。
4. **批量入队**：按 watchlist 顺序**逐个 ticker 入队**（见下）。复用 `POST /api/queue`。
5. **实时看板**：rich `Live` 面板显示批次进度，直到队列清空且无 running。

结果写入同一个 `webui.db`，webUI 历史页天然可见。

## 组件与文件

- **`cli/api_client.py`（新）**：用 `requests`（已是运行时依赖）封装：
  - `get_watchlist() -> list[dict]`
  - `enqueue(tickers, ticker_names, trade_date, asset_type, analysts, research_depth,
    output_language, llm_provider, deep_think_llm, quick_think_llm) -> dict`
  - `get_queue() -> dict`
  - `get_history() -> list[dict]`（用于取已完成 run 的 decision）
  - `get_status(run_id) -> dict`（telemetry 快照，驱动当前 run 详情面板）
  - base_url 来源：`--api-url` flag > `TRADINGAGENTS_API_URL` 环境变量 > 默认 `http://localhost:8000`。
  - 网络错误统一抛一个 `ApiError`，由命令层转成友好提示。
- **`cli/batch.py`（新）**：TUI 主逻辑——探活、选设置、分组入队、驱动 Live 看板、收尾汇总。
- **`cli/main.py`**：新增 `@app.command("batch")` 注册入口，转调 `cli/batch.py`。
- **不改动** `api/`、`tradingagents/`、`webui/`。纯新增客户端，复用现有 REST 接口。

## 顺序与 asset_type 处理

- 按 watchlist 顺序**逐个 ticker 入队**：每个 ticker 单独 `POST /api/queue`，`tickers=[t]`、
  `asset_type=detect_asset_type(t)`。现有端点每批只接受一个 asset_type，逐个入队天然规避。
- `store.enqueue_run` 的 `queue_position = max(pending)+1`，顺序调用严格递增，
  **完全保持 watchlist 顺序**（混合 stock/crypto 也不会被重排）。
- 入队是 N 次 localhost POST（每次数毫秒；相比每个分析数分钟可忽略）。
- ticker→run_id 映射：`POST /api/queue` 返回 `run_ids`（单元素），逐个记录 `{ticker: run_id}`
  与 `{run_id: ticker}`。ticker 用 `t.strip().upper()`（与 server 端 `EnqueueRequest` 校验器
  的规范化一致）。
- A 股 `.SS/.SZ` 由 runner 靠后缀自动路由，与 asset_type 无关，不受影响。

## 实时看板（纯轮询混合看板）

rich `Live` 布局，单一轮询循环（每 1–2s），无 SSE、无后台线程：

- **上半：批次表**，每行 `标的（ticker + name） | 状态 | 决策`。
  - 状态图标：⏳ 待跑（pending） / ▶ 运行中（running） / ✓ 完成（completed） / ✗ 错误（error）
    / ⊘ 取消（cancelled）。
  - 决策列在 run 完成后填入（Buy/Overweight/Hold/Underweight/Sell）。
- **下半：当前运行详情**。对 `GET /api/queue` 报告的 running run，轮询
  `GET /api/analysis/{run_id}/status`（telemetry 快照），展示：
  - `last_report_section` → 当前/最近产出的报告章节（映射成中文名）。
  - `llm_active` / `active_llm_calls` / `last_llm_model` → LLM 活动指示。
  - `last_llm_error` → 若有错误则显示。
- **驱动方式**：单个轮询循环——每 1–2s 依次 `GET /api/queue`（拿 running/pending 快照）、
  对 running run 调 `GET /api/analysis/{run_id}/status`（拿详情）、`GET /api/history`
  （给已结束的 run 补 decision + 终态）。用这三份快照刷新看板状态机并 `live.update()`。
  队列清空且无 running → 退出 Live，打印批次汇总（每个标的的最终状态 + 决策）。
- **status 404 容错**：run 已完成/未注册 telemetry 时 status 可能 404 或字段全空，
  当作“暂无详情”处理，最终态仍以 `GET /api/history` / `GET /api/queue` 为准。

## 边界与错误处理

- **服务未启动**：探活失败 → 友好提示如何启动 + 非零退出码。
- **watchlist 为空**：提示去 webUI 添加后退出（0 码）。
- **入队时服务忙**：无需特殊处理——`POST /api/queue` 忙时也是排队（不再 409）。
- **单个 run 出错/取消**：看板照常标记 ✗/⊘，继续下一个，不中断整批。
- **status 请求失败/404**：单次轮询里 status 抛错时吞掉当次详情（显示“暂无详情”），
  不影响 queue/history 推进的最终态判定（结果以 DB 为准）。
- **用户 Ctrl-C**：停止看板并退出；**已入队的任务保留在服务端队列继续跑**（不主动清队列，
  与 webUI 语义一致）。汇总里说明“已退出看板，队列仍在后台运行”。

## 测试策略

- 遵循项目约定：`pytest -m unit`，mock 掉 HTTP。
- **`cli/api_client.py`**：用 `unittest.mock` patch `requests.get/post` 验证：URL 组装、
  各方法的 JSON 解析、`get_status` 的 404 处理、`ApiError` 转换。
- **`cli/batch.py`**：把 `ApiClient` 注入为 fake，验证：探活失败路径、空 watchlist 路径、
  asset_type 分组与保序、看板状态机（pending→running→completed、错误/取消、status 缺失时的
  详情降级）。不起真实服务、不起真实 graph（与 webUI 测试同款“注入 fake”思路）。
- Lint：`ruff check .`。

## 非目标（YAGNI）

- 不在 TUI 里做 watchlist 的增删改（那是 webUI 的职责）。
- 不做并行跑多个 run（保持单用户不变量）。
- 不做每个 ticker 单独设置（整批共享一套设置）。
- 不改动服务端任何代码或新增端点。
- 不显示报告全文（只显示章节进度，避免刷屏；全文去 webUI 看）。
