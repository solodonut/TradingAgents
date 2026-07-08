# 启动时模型健康检查与自动选型 — 设计文档

- 日期：2026-06-23
- 状态：已批准设计，待写实现计划

## 背景与目标

服务启动时，配置里的模型（`llm_provider` / `deep_think_llm` / `quick_think_llm`）不一定真的可用——
provider 临时故障、模型下线、key 权限不足等都会让后续分析在第一次 LLM 调用时才暴露问题。

本功能在服务启动阶段对**当前 provider** 的候选模型做一轮轻量探测，全部测一遍并产出报告，
然后为 `deep_think_llm` / `quick_think_llm` 各自挑选一个可用模型写回配置，使后续分析直接使用可用模型。

### 已确定的需求边界（来自需求澄清）

1. **形态**：做成独立可复用模块，不依赖 FastAPI；WebUI 启动调用它，CLI 以后可复用。
2. **回退范围**：只在**同一个 provider 内**换模型（不切换 provider）。
3. **终止条件**：把该 provider 的所有候选**全部测一遍并报告**（不在第一个可用处提前停止）。
4. **选型策略**：**原配置优先**——当前配置的模型测通就保留它，否则取候选清单里第一个测通的。
5. **全挂处理**：该槽位保留原配置不变，**记 error 日志但不阻断启动**。
6. **报告去向**：打日志 + 存到 `app.state.model_health`。

### 本次范围

- 交付：健康检查模块 + WebUI 启动接线 + 单元测试。
- 不含：CLI 接线（模块可复用，留待以后）；不切换 provider；不引入新的 HTTP 端点（仅存 `app.state`）。

## 架构

新增模块 `tradingagents/llm_clients/health_check.py`，对外暴露两个函数和两个数据类。

### 数据结构

```python
@dataclass
class ProbeResult:
    model: str
    ok: bool
    error: str | None      # 异常的简短字符串；ok 时为 None
    latency_ms: int

@dataclass
class SlotReport:
    configured: str                 # 进来时配置的模型
    selected: str                   # 选型结果（可能 == configured）
    all_failed: bool                # 该槽位所有候选都没测通
    candidates: list[ProbeResult]   # 按测试顺序排列，含 configured

@dataclass
class HealthReport:
    provider: str
    slots: dict[str, SlotReport]    # key: "deep_think_llm" / "quick_think_llm"
    any_failed: bool                # 任一槽位 all_failed 即为 True
```

### 函数 1：`probe_model`

```python
def probe_model(provider: str, model: str, base_url: str | None, timeout: int = 20) -> ProbeResult
```

- 通过 `create_llm_client(provider, model, base_url)` 建客户端，`get_llm()` 拿 LangChain 模型。
- 用最小请求探测：`llm.invoke([HumanMessage(content="ping")])`。
- 判定：**不抛异常即 `ok=True`**；抛任何异常则 `ok=False`，`error` 存 `f"{type(e).__name__}: {e}"` 截断到合理长度。
- `latency_ms` 记录本次调用耗时。
- `timeout`：尽量为探测设置一个不长的超时，避免单个模型卡死拖慢启动；若 provider 客户端不支持注入超时，则依赖其默认值（实现计划阶段确认各客户端能力）。

### 函数 2：`check_and_select`

```python
def check_and_select(config: dict, timeout: int = 20) -> HealthReport
```

对两个槽位分别处理（`deep_think_llm` 用 catalog 的 `deep` 候选，`quick_think_llm` 用 `quick` 候选）：

1. **构造候选清单**：
   - 第一项 = `config[slot]`（当前配置的模型）。
   - 追加该 provider 在 `model_catalog.get_model_options(provider, mode)` 里的候选 `value`，
     去掉 `"custom"` 占位，去掉与配置模型重复的项。
   - 若 provider 不在 `MODEL_OPTIONS`（如 openrouter / azure 等动态/自定义 provider）或仅有 `"custom"`，
     则候选清单只含「当前配置的模型」一项。
2. **全部测一遍**：对清单里每个模型调 `probe_model`，收集 `ProbeResult`（按顺序）。
3. **选型（原配置优先）**：
   - 若 `configured` 测通 → `selected = configured`。
   - 否则 → `selected` = 候选清单里第一个 `ok=True` 的模型。
   - 若无任何候选测通 → `selected = configured`（保留原值），`all_failed = True`。
4. 汇总成 `HealthReport`。

> 注意：模块本身**不修改全局配置**，只返回 `HealthReport`。是否写回由调用方决定，保证可复用与可测。

### WebUI 启动接线（`api/main.py`）

在现有 `@app.on_event("startup")`（`_wire_graph_factory`）中追加一步（或新增一个 startup 钩子）：

1. 调 `report = check_and_select(DEFAULT_CONFIG)`。
2. 对每个槽位，把 `report.slots[slot].selected` **写回 `DEFAULT_CONFIG[slot]`**
   （这样 `real_graph_factory` / `real_chat_llm_factory` 拷贝出的就是可用模型）。
3. 用 `logging` 打印结构化报告：provider、每个槽位 configured→selected、每个候选 ok/error/latency。
4. `app.state.model_health = report`。
5. 若 `report.any_failed`：记 `logging.error(...)` 指明哪个槽位全挂，**但不抛异常、不阻断启动**。

> 启动时若 `TradingAgentsGraph` 导入失败（`TradingAgentsGraph is None`，见现有 try/except），
> 健康检查同样应安全跳过或容错，不得让 startup 崩溃。

## 数据流

```
startup
  └─ check_and_select(DEFAULT_CONFIG)
        ├─ for slot in (deep_think_llm, quick_think_llm):
        │     candidates = [configured] + catalog(provider, mode) - {custom, dup}
        │     for model in candidates: probe_model(...) → ProbeResult
        │     selected = configured if configured.ok else first ok else configured
        └─ HealthReport
  ├─ 写回 DEFAULT_CONFIG[slot] = selected
  ├─ logging（报告 + any_failed 时 error）
  └─ app.state.model_health = report
```

## 错误处理

- `probe_model` 捕获**所有**异常，绝不向上抛——它返回 `ProbeResult(ok=False, ...)`。
- `check_and_select` 不抛异常（除非编程错误，如槽位名拼错）。
- 启动接线即使 `any_failed` 也不阻断；保留原配置，让后续真实调用时再按现有错误路径报错。

## 测试策略（纯单元，无网络、无真实 key）

mock `tradingagents.llm_clients.health_check.create_llm_client`，让 fake client 的 `get_llm().invoke`
按模型名选择性抛异常或正常返回，覆盖：

1. **原配置可用** → `selected == configured`，且仍记录了全部候选的 `ProbeResult`（验证「全部测一遍」）。
2. **原配置挂、第二候选可用** → `selected` 为第一个 ok 的候选，顺序正确。
3. **全挂** → `selected == configured`，`all_failed=True`，`any_failed=True`。
4. **provider 不在 catalog / 仅 custom** → 候选清单只含配置模型，逻辑不崩。
5. **报告结构**：`HealthReport` 字段、`candidates` 含 configured 且去重、`latency_ms` 字段存在。
6. （可选）WebUI 接线：用现有「注入 fake」测试风格验证 `DEFAULT_CONFIG` 被写回、`app.state.model_health` 被设置、全挂不抛异常。

## 取舍记录

- **「全部测一遍」的代价**：启动时对 ibm_ica 约 7 次真实 LLM 调用（quick 3 + deep 4），
  启动变慢且有少量费用。已与用户确认，按此终止条件实现。
- **只接 WebUI**：CLI 复用留待以后；模块设计为无框架依赖以便复用。
- **不切 provider**：明确只在同 provider 内换模型，符合需求边界。
