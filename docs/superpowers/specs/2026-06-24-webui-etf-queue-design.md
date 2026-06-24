# WebUI ETF 队列分析 — 设计文档

- 日期：2026-06-24
- 范围：仅 WebUI（`api/` + `webui/`），CLI 不在本次范围
- 目标：一次输入多个 ETF（或股票）代码，保存为持久化队列，由后端串行依次分析

## 1. 背景与现状

当前单次运行流程（见 `api/routes/analysis.py:28`）：

1. `POST /api/analysis` 收到单个 `AnalysisRequest`；
2. `store.has_running_run()` 为真时直接 `409`（单用户不变量）；
3. `store.insert_run(...)` 写入一行 `status='running'`；
4. `graph_factory(req)` **即时构建** `TradingAgentsGraph`（会解析标的、可能触网）；
5. 建 `queue.Queue` + `threading.Event`，起后台线程跑 `AnalysisRunner.run()`；
6. 前端拿到 `run_id` 立即订阅 `GET /api/analysis/{run_id}/stream`。

历史与状态存于 SQLite（`api/store.py`，表 `analysis_runs`），状态仅四种：
`running | completed | error | cancelled`。运行状态全在前端 React `useState`，不持久化。

**痛点**：一次只能跑一个，忙时报 409；要分析多个标的需人工逐个发起、逐个等待。

## 2. 需求（已与用户确认）

- 仅 WebUI。
- 一次输入多个代码（逗号/空格/换行分隔），整批共用同一份配置。
- 队列状态持久化在**后端 SQLite**，刷新页面/重启服务后仍在。
- 后端**串行**调度：跑完一个自动启动下一个 pending。
- 某项**出错或被取消 → 跳过，继续下一个**。
- 队列管理：移除单个 pending、清空整个队列、取消当前并推进、调整 pending 顺序。

## 3. 架构总览（方案 C：独立调度器 + 统一入口）

所有运行（含单个标的）统一走 **「入队 → 调度器拉起」** 一条路径，单个即长度为 1 的队列。
新增一个进程内 `QueueScheduler`：当「无 running 且有 pending」时，按顺序启动下一个 pending。

```
POST /api/queue  ─┐
POST /api/analysis ┤─→ store.enqueue_run() (status=pending) ─→ scheduler.advance()
                  ─┘                                              │
                                              ┌───────────────────┘
                                              ▼
        scheduler.advance() (持锁，串行保证):
            if has_running_run(): return
            run = store.next_pending()           # queue_position 最小
            if run is None: return
            _start(run):                         # pending → running
                req = AnalysisRequest(**config_json)
                graph,... = graph_factory(req)   # 此刻才构建 graph
                建 queue.Queue + cancel Event + telemetry
                起线程: runner.run(); finally → scheduler.advance()
```

关键点：

- **graph 延迟到 `_start` 才构建**：入队时只存配置（`config_json`），轮到才 `graph_factory`，避免排队项提前触网/占用资源。
- **统一 `_start`**：把 `routes/analysis.py:48-75` 现有「建 queue / cancel / telemetry / 起线程」逻辑抽进调度器的 `_start(run)`，入队路径与调度路径共用。
- **完成即推进**：runner 线程结束（complete / error / cancelled 任意分支）后，在其 `finally` 触发 `scheduler.advance()` 启动下一个。出错/取消天然「跳过继续」。
- **推进发生在线程真正结束后**：避免在被取消项线程仍在流式时就启动下一个而出现两个 running。

## 4. 数据模型与状态机

复用 `analysis_runs` 表，**新增一列**：

```sql
ALTER TABLE analysis_runs ADD COLUMN queue_position INTEGER;  -- 仅 pending 用，排序依据；running/终态为 NULL
```

迁移：`Store.__init__` 在 `executescript(_SCHEMA)` 后，用 `PRAGMA table_info(analysis_runs)`
检测列是否存在，缺失则 `ALTER TABLE ADD COLUMN`（兼容已存在的旧库）。

状态机新增 `pending`：

```
pending ──(scheduler._start)──▶ running ──▶ completed | error | cancelled
   │                                              ▲
   └── 仅 pending 可被移除/重排/清空 ───────────────┘ 终态进入历史列表
```

`api/schemas.py`：

- `RunStatus = Literal["pending", "running", "completed", "error", "cancelled"]`
- 新增 `EnqueueRequest`（批量入队）：
  - `tickers: list[str]`（≥1，非空、去重、转大写）
  - 共享配置字段与 `AnalysisRequest` 一致：`trade_date / asset_type / analysts / research_depth / output_language / llm_provider / deep_think_llm / quick_think_llm`
  - 校验器：tickers 至少 1 个、analysts 至少 1 个（复用现有规则）
- 新增 `QueueItem`：`run_id / ticker / status / queue_position / created_at`
- 新增 `QueueState`：`running: QueueItem | None`、`pending: list[QueueItem]`
- 新增 `ReorderRequest`：`ordered_run_ids: list[str]`

## 5. Store 改动（`api/store.py`）

- 迁移：在 `__init__` 内追加 `queue_position` 列（见 §4）。
- `enqueue_run(run_id, ticker, trade_date, asset_type, config) -> None`
  插入 `status='pending'`，`queue_position = (当前 pending 最大值 or 0) + 1`。
- `start_run(run_id) -> bool`
  `UPDATE ... SET status='running', queue_position=NULL WHERE run_id=? AND status='pending'`（行数>0 表示抢占成功）。
- `next_pending() -> RunResult | None`
  `status='pending' ORDER BY queue_position ASC LIMIT 1`。
- `list_queue() -> QueueState`
  running 项（最多一条）+ pending 项按 `queue_position ASC`。
- `remove_pending(run_id) -> bool`
  仅当 `status='pending'` 时删除（已 running/终态返回 False）。
- `clear_pending() -> int`
  删除所有 `status='pending'`，返回删除数。
- `reorder_pending(ordered_run_ids) -> None`
  按给定顺序重写这些 pending 行的 `queue_position`；忽略其中非 pending 的 id。
- `reset_orphaned_runs() -> int`
  启动时把残留 `status='running'` 复位为 `error`（result_json 标注「服务重启中断」），返回条数。
- 现有 `insert_run` 保留（向后兼容/测试），新代码改用 `enqueue_run` + `start_run`。
  `complete_run / mark_error / cancel_run / update_partial_result` 仍以 `status='running'` 为前提，
  `start_run` 翻转状态后即满足。

## 6. 调度器（`api/scheduler.py`，新增）

`QueueScheduler` 持有：`store`、`graph_factory` 取值方式、`app.state`（queues / cancellations / telemetry / starting_telemetry）。

- `advance()`：
  - 持一把 `threading.Lock`（与现有 `app.state.run_lock` 复用或新建），保证不会并发启动两个；
  - `if store.has_running_run(): return`；
  - `run = store.next_pending()`；`None` 则返回；
  - 调 `start_run(run_id)` 抢占（失败说明被并发抢走，重试一次 `advance`）；
  - `_start(run)`。
- `_start(run)`：
  - `req = AnalysisRequest(**run.config)`；
  - `telemetry = RunTelemetry(run_id)`；登记 `app.state.telemetry[run_id]`；
  - 设 `app.state.starting_telemetry = telemetry`，`graph,... = graph_factory(req)`，`finally` 复位（沿用现有侧信道约定，见 `api/main.py:136`）；
  - 建 `queue.Queue` 与 `cancel Event`，登记入 `app.state`；
  - 起 daemon 线程：`runner.run(...)`；线程目标包一层 `try/finally`，`finally: self.advance()`。
- 启动恢复：`api/main.py` 启动钩子里先 `store.reset_orphaned_runs()`，再 `scheduler.advance()`（接管上次遗留 pending）。

并发模型：单写者（调度器）串行启动；`advance` 由三处事件驱动调用——入队后、runner 线程结束后、取消后——不做忙轮询。

## 7. API 接口（`api/routes/queue.py` 新增 + `analysis.py` 微调）

新增 `api/routes/queue.py`（`prefix="/api/queue"`）：

| 方法 | 路径 | 行为 |
|---|---|---|
| `POST` | `/api/queue` | `EnqueueRequest` → 逐个 `enqueue_run`（共享配置）→ `scheduler.advance()` → 返回 `{run_ids, running_run_id, queue}` |
| `GET` | `/api/queue` | 返回 `QueueState`（running + 有序 pending） |
| `DELETE` | `/api/queue/{run_id}` | `remove_pending`；非 pending → `409` |
| `DELETE` | `/api/queue` | `clear_pending`；返回 `{removed: n}` |
| `PATCH` | `/api/queue/order` | `ReorderRequest` → `reorder_pending` → 返回新的 `QueueState` |

`api/routes/analysis.py` 微调：

- `POST /api/analysis`：去掉「忙时 409」拦截；改为 `enqueue_run([ticker]) + scheduler.advance()`，返回 `{run_id}`（向后兼容）。
- `cancel`：保留设置 cancel_event + `cancel_run` + 推送 `cancelled`/`None` 关闭 SSE 的逻辑；
  **推进交给 runner 线程的 `finally`**（线程检测到 cancel 后真正退出再 `advance`），cancel 路由本身不直接 `advance`，避免两个 running 重叠。
- `stream` / `status` / `report`：不变。

`scheduler` 实例的获取：在 `api/main.py` 创建并挂到 `app.state.scheduler`（测试可注入），路由通过 `request.app.state.scheduler` 取用。

## 8. 前端（`webui/`）

> 改动前先读 `webui/node_modules/next/dist/docs/`，遵守 `webui/AGENTS.md`（Next.js 16 破坏性差异）。

- `components/ConfigCard.tsx`
  - ticker 输入支持多个代码（逗号/空格/换行分隔）；解析为列表：转大写、trim、去空、去重。
  - 提交一律调 `POST /api/queue`（单个=长度 1）。按钮文案随数量变化（如「分析 3 个标的」）。
  - 共享配置控件沿用现有，整批共用。
- `components/QueuePanel.tsx`（新增，挂右侧 aside）
  - 展示 running 项（高亮 + 取消按钮 → `POST /api/analysis/{id}/cancel`）与有序 pending 项。
  - 每个 pending：移除（`DELETE /api/queue/{id}`）、上移/下移（`PATCH /api/queue/order`，按钮式，不做拖拽）。
  - 顶部：清空队列（`DELETE /api/queue`）。
- `app/page.tsx`
  - 新增 `queue` state，按现有轮询节奏拉 `GET /api/queue`。
  - SSE「跟随当前 running」：订阅 running run 的 stream；`onClose` 时刷新 queue，
    若出现新的 running `run_id` 则自动订阅其流，直到队列跑空。
  - 现有进度/报告/决策展示逻辑不变，仅「当前展示的 run」随队列推进切换。
- `lib/api.ts` / `lib/sse.ts`：新增 `enqueue() / getQueue() / removePending() / clearQueue() / reorderQueue()`。

## 9. 测试与验证

遵循 `AGENTS.md`：测试用 `app.state.graph_factory` 注入假 graph，无需真实 key/服务。
同时需注入/复位 `app.state.scheduler`（用真实 `QueueScheduler` + fake graph_factory）。

API 测试（`tests/webui/`）：

- 入队一批 → 第一个 running、其余 pending，`queue_position` 递增。
- 调度推进：fake graph 跑完一个 → 自动启动下一个 pending（断言状态流转，需等待线程，用轮询/事件同步）。
- 出错跳过：fake graph 对某 ticker 抛错 → 该项 `error` → 队列继续下一个。
- 取消推进：取消 running → `cancelled` → 自动推进下一个。
- `DELETE /api/queue/{id}` 仅删 pending、删 running 返回 409；`DELETE /api/queue` 清空 pending 不动 running；`PATCH order` 重排生效。
- 重启恢复：构造残留 running 行 → `reset_orphaned_runs` 复位为 error → `advance` 接管 pending。
- smoke：新路由注册（扩展 `tests/webui/test_smoke.py`）。
- 迁移：旧库（无 `queue_position` 列）打开后自动补列、不丢数据。

收尾手动验证（无 CI，CLAUDE.md 要求）：

- `.venv/bin/python -m ruff check .`
- `.venv/bin/python -m pytest -m "not integration"`

前端无测试框架，靠 `./dev.sh` 起服务手动验证：多代码入队、排队展示、移除/清空/重排、出错跳过、取消推进、刷新后队列仍在。

## 10. 影响面与兼容

- DB 自动迁移加列，旧库无损。
- `POST /api/analysis` 行为对前端兼容（仍返回 `run_id`），但语义从「立即跑/忙时 409」变为「入队后由调度器拉起」；忙时不再 409 而是排队。
- 单用户串行不变量保持（同一时刻至多一个 running）。
- 文档：更新 `CHANGELOG.md`（Keep a Changelog）与必要的 `AGENTS.md` WebUI 段落说明队列与调度器。

## 11. 非目标（YAGNI）

- 不做 CLI 队列。
- 不做并行运行（仍严格串行，符合单用户不变量）。
- 不做拖拽排序（按钮上移/下移即可）。
- 不做跨用户/多租户、优先级权重、定时调度。
