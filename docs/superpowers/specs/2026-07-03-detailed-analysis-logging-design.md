# 详细分析日志功能 — 设计文档

- 日期：2026-07-03
- 状态：设计已确认，待写实现计划
- 相关模块：`tradingagents/`(核心)、`api/`、`webui/`

## 1. 目标

为每一次 ETF（及任意标的）分析产生一份**尽可能详尽**的结构化日志，覆盖分析过程中的每一个动作：
LangGraph 节点进出、每次 LLM 调用、每次工具调用、每次数据源 endpoint 调用、辩论每一轮、
报告产出、memory 读写、checkpoint 存取、以及所有异常。

- **一个分析 = 一个文件**，文件名含 ETF 代码 + 时间戳。
- **Web UI 可实时看到日志生成**，并支持刷新/历史回看、按类型过滤、关键字搜索、单条展开。

## 2. 关键决策（已与用户确认）

| 编号 | 决策 | 选择 |
|---|---|---|
| 范围 | 覆盖哪些运行入口 | **所有入口**（WebUI + CLI + `main.py` 代码调用）；埋点下沉核心层 |
| 格式 | 日志文件格式 | **JSONL**（每行一个结构化事件） |
| 实时机制 | UI 如何实时读取 | **复用现有 SSE + 新增 `log` 事件** + **文件回读接口**（组合） |
| LLM 详细度 | 每次 LLM 记多细 | **完整记录、超长截断**（阈值可配，默认 8000 字符），密钥脱敏 |
| 事件类型 | 记哪些动作 | 全部（含 memory 读写、checkpoint 存取） |
| 文件位置 | 存哪、怎么命名 | `~/.tradingagents/logs/<TICKER>_<YYYYMMDD-HHMMSS>_<run8>.jsonl` |
| UI 形态 | 查看器功能 | **进阶**：实时着色流 + 过滤/搜索 + 单条展开 |
| 埋点机制 | 核心层如何拿到 logger | **ContextVar 环境式日志器**（零侵入函数签名） |
| 子包命名 | 新代码放哪 | `tradingagents/obs/`（observability） |

## 3. 架构与数据流

```
propagate(ticker, date)
  └─ RunLogger 创建 (打开 <TICKER>_<ts>_<run8>.jsonl)
     set_current_run_logger(logger)      ← contextvar，在 runner 线程内 set
        │
        ├─ graph 各节点 node_enter/node_exit  ← graph 包装
        ├─ LLM 回调 (RunLogger 版 CallbackHandler)  → llm_call / tool_call
        ├─ route_to_vendor()  → vendor_call        ← get_current_run_logger()
        ├─ memory.py          → memory_op          ← get_current_run_logger()
        ├─ checkpoint         → checkpoint_op       ← get_current_run_logger()
        └─ 每条事件:  logger.emit(event)
              ├─ 追加写入 .jsonl (flush)
              └─ 若存在 SSE 队列 sink → 推 {"event":"log","data":event}
     clear_current_run_logger()          (finally)
```

一次 `emit()` 同时：**写文件**（所有入口都写）+ **推 SSE 队列**（仅当该 run 绑定了 WebUI 队列）。
这即是「实时 SSE + 文件回读」组合方案的实时侧；回读侧由新增接口读文件回放。

## 4. 核心组件（`tradingagents/obs/`）

### 4.1 `run_logger.py`

- `RunLogger(run_id, ticker, log_dir, sink=None, truncate_chars=8000)`
  - 持有打开的文件句柄 + `threading.Lock`（后台线程多处 emit 安全）。
  - `sink`：可选回调 `Callable[[dict], None]`，WebUI 注入「往该 run 队列推事件」的函数；CLI 为 `None`。
- `emit(event_type: str, *, elapsed_ms: float | None = None, **payload)`
  - 组装 `{ts, seq, run_id, event_type, elapsed_ms?, **payload}`。
  - 加锁：写一行 `json.dumps(event, ensure_ascii=False)` + `\n` + `flush()`；随后 `sink(event)`（sink 异常被吞并记 stderr，绝不影响分析）。
  - `seq` 单调自增，前端用于排序/去重。
- `_truncate(value, limit)`：字符串超长 → `{"text": value[:limit], "truncated": True, "full_chars": len(value)}`；否则原样。
- `_redact(obj)`：递归对键名匹配 `api_key`/`authorization`/`*_key`/`token`/`secret` 的字段打码为 `"***"`。
- `close()`：关文件。由 `propagate` 的 finally 调用。

### 4.2 contextvar 管理（同文件或 `context.py`）

- `_current: ContextVar[RunLogger | None] = ContextVar("run_logger", default=None)`
- `set_current_run_logger(logger)` / `get_current_run_logger() -> RunLogger | None` / `clear_current_run_logger()`
- 各埋点处：`logger = get_current_run_logger(); if logger: logger.emit(...)`。
  无上下文时静默跳过 → 对不在分析上下文的调用零副作用，不破坏现有测试。
- **线程注意**：LangGraph 在后台线程运行（WebUI 经 `AnalysisRunner` 线程），因此 `set_current_run_logger`
  必须在**执行分析的那个线程内**调用（`propagate`/graph 执行处），而非请求线程。

## 5. 事件模型（JSONL 每行 schema）

统一外层字段：`ts`(ISO8601)、`seq`(int)、`run_id`、`event_type`、`elapsed_ms`(可选)。

| event_type | 触发点 | payload 关键字段 |
|---|---|---|
| `run_start` | 分析开始 | ticker, trade_date, config(脱敏快照) |
| `run_end` | 分析结束 | decision, duration_ms |
| `node_enter` / `node_exit` | 每个 LangGraph 节点 | node, elapsed_ms |
| `llm_call` | 每次 LLM 调用 | model, prompt(截断结构), response(截断结构), tokens{in,out}, elapsed_ms, tool_calls |
| `tool_call` | ReAct agent 工具调用 | name, args(截断), result(截断), elapsed_ms |
| `vendor_call` | `route_to_vendor` 每次调用 | method, vendor, args, ok, no_data(bool), fallback(bool), elapsed_ms, error |
| `debate_round` | 多空/风险辩论每一轮 | team, round, total, speaker, content |
| `report_section` | 每份报告产出 | section, content(截断) |
| `memory_op` | trading_memory.md 操作 | op(append/reflect/inject), ticker, detail |
| `checkpoint_op` | checkpoint 存取 | op(save/load/resume), node, ok |
| `error` | 任何异常 | error_type, message, traceback |

## 6. 埋点位置（方案 1：ContextVar）

- **run_start / run_end / close**：`TradingAgentsGraph.propagate`（`tradingagents/graph/trading_graph.py`）——
  创建 `RunLogger`、`set_current_run_logger`、结尾 `run_end` + `clear` + `close`（`try/finally`）。
- **node_enter / node_exit**：LangGraph 节点包装（在 graph 构建处包一层，记节点名与耗时）。
- **llm_call / tool_call**：新增 `RunLogger` 版 `BaseCallbackHandler`（参考现有 `api/telemetry.py::RunTelemetryCallback`），
  在 `on_(chat_model|llm)_start/end/error`、`on_tool_start/end` 里 `emit`。该 handler 通过 contextvar 拿 logger，
  并与现有 telemetry callback 并存（两者都挂到 callbacks 列表）。
- **vendor_call**：`tradingagents/dataflows/interface.py::route_to_vendor` 内，围绕每个 vendor 尝试记录
  成功/失败/降级/NO_DATA/耗时。函数签名不变，内部取 contextvar logger。
- **memory_op**：`tradingagents/agents/utils/memory.py`（pending 追加 / 反思 / 注入 PM prompt 处）。
- **checkpoint_op**：checkpoint 存取处（`tradingagents/graph/` 内 checkpoint 相关代码）。

> 埋点一律「取 contextvar logger，无则跳过」，不改被调函数签名，符合仓库「Surgical Changes / 最小改动」约定。

## 7. API（`api/`）

### 7.1 实时侧
- `AnalysisRunner`/route 创建 `RunLogger` 时把 `sink` 设为「往该 run 的 `queue.Queue` 推 `{"event":"log","data":event}`」。
- 现有 `GET /api/analysis/{run_id}/stream` SSE 无需改造，`log` 事件随现有管道自动流出。

### 7.2 回读侧（新增）
- `GET /api/analysis/{run_id}/logs` → 逐行解析该 run 的 `.jsonl`，返回 `list[event]`；文件不存在 → 404。
- run_id → 文件路径：`RunLogger` 创建时把 `log_path` 写入 `api/store.py` 的 run 行（**新增列 `log_path`**），
  回读接口据此定位，不靠扫目录猜文件名。

## 8. 前端（`webui/`，UI 方案 B）

分析页新增**可折叠日志面板**：
- EventSource 现有监听里加 `log` 事件 → push 进 `logs` state；页面加载/刷新先 `fetch(/logs)` 回填历史。
- 渲染：虚拟滚动行列表，按 `event_type` 着色（vendor=蓝 / llm=紫 / error=红 / node=灰 等）；
  自动滚到底，用户上滑时暂停自动滚。
- 过滤/搜索：顶部 event_type 多选 chips + 关键字输入（前端内存过滤）。
- 单条展开：点行展开完整 payload；长 prompt/response 折叠；`truncated` 时提示「已截断，完整 N 字符见文件」。
- **约束**：遵守 `webui/AGENTS.md`——改前端前先读 `webui/node_modules/next/dist/docs/`（Next.js 16 / React 19）。

## 9. 配置与脱敏

- `default_config.py` 新增（均可被 `TRADINGAGENTS_*` 环境变量覆盖，沿用现有类型感知机制）：
  - `log_enabled`：默认 `True`。
  - `log_dir`：默认 `~/.tradingagents/logs/`，`TRADINGAGENTS_LOG_DIR` 覆盖。
  - `log_truncate_chars`：默认 `8000`。
- 脱敏：config 快照、vendor args 中的密钥字段统一过 `_redact()`。

## 10. 测试（`pytest -m unit`，全程 mock、无网络、无真实 key）

- `RunLogger.emit`：写出合法 JSONL、`seq` 单调递增、截断/脱敏生效、`sink` 被调用且异常不冒泡。
- contextvar：set/get/clear 正确；无上下文时埋点静默跳过、不报错。
- `route_to_vendor`：在有 logger 上下文时产生 `vendor_call` 事件（含 NO_DATA / fallback 分支）。
- `/api/analysis/{run_id}/logs`：有文件返回解析结果、无文件 404。
- runner：`log` 事件确实进队列（用 fake graph，复用现有 `app.state.graph_factory` 测试夹具）。
- 前端：日志面板挂载、`log` 事件追加、类型过滤/关键字过滤生效（有前端测试框架则加，否则手测记录）。

## 11. 非目标（YAGNI）

- 不做独立的「历史所有分析日志浏览页」（UI 方案 C）——历史文件在磁盘上，后续需要再加。
- 不做日志轮转/清理/压缩策略（首版按文件堆积，容量策略后续再议）。
- 不改动现有 `api/telemetry.py` 的聚合遥测行为——新日志与其并存，各司其职。

## 12. 兼容性与风险

- **线程上下文**：contextvar 必须在执行分析的线程内 set（见 4.2），否则埋点取不到 logger。写实现计划时明确该点。
- **性能**：每条 emit 做一次带锁的 `write+flush`；LLM/vendor 调用本就是慢操作，flush 开销可忽略。
- **单一数据源**：文件是权威来源；SSE 只是实时镜像。刷新/断线一律回落到 `/logs` 文件回读。
- **`log_enabled=False`**：`propagate` 不创建 logger、不 set contextvar，全链路等价于现状（零开销）。
