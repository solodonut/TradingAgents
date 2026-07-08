# 设计：Chat 会话档案 Harness（锚定关键事实 + 行动前确认）

- 状态：已与用户确认，待评审
- 日期：2026-06-22
- 范围：WebUI 投顾 Chat（`api/` 后端 + `tradingagents/advisor/` + `webui/` 前端）

## 1. 背景与问题

现有 Chat 是一个投顾角色：消费已完成的分析报告 + 用户持仓 + 实时数据工具，
通过 LLM tool-call 循环作答（[engine.py](../../../tradingagents/advisor/engine.py)、
[chat.py](../../../api/routes/chat.py)）。

它**没有任何"确认需求 / 槽位填充"机制**：用户在会话里陈述的关键参数（如"可用资金池大小"）
只是混在聊天历史里，没有被结构化抽取、确认、并稳定注入到后续每轮推理。结果是用户反复纠正、
LLM 反复算错（典型：资金池被误读 / 单位币种歧义 / 心算错误）。

## 2. 目标

用一套轻量 Harness 同时解决两件事：

1. **锚定关键事实**：维护一份用户确认过的会话参数，一次确认后稳定注入每轮推理，
   LLM 不再重新推断或遗忘。
2. **行动前先确认**：缺必需参数时反问；从对话临时推断出关键事实时先复述待确认，
   而不是基于错误假设直接给操作建议。

非目标（YAGNI）：
- 不引入独立的 LangGraph 编排状态机（评估为过度工程，见"方案选择"）。
- Chat 仍不触发新的分析 run，继续消费已完成的 run 结果。

## 3. 方案选择

- **方案 A（采纳）**：轻量"会话档案 + 工具强约束"，复用现有 tool-call 循环、
  `NO_DATA_AVAILABLE` 哨兵、持仓面板三个既有模式。硬约束放在工具层（代码拦截），
  不依赖 LLM 自觉。落地风险最小。
- 方案 B（否决）：显式"理解力 Harness"状态机（LangGraph 编排层），每轮多一次 LLM
  调用判断"是否听懂"。最稳但最重，对单用户投顾场景过度工程。
- 方案 C（否决）：A + 出建议前加一道独立"理解力预检"LLM。介于 A/B 之间，仍多一次调用。

## 4. 数据模型与存储

新增一个会话级"会话档案"，与现有 portfolio 完全平行存储。

```python
# api/schemas.py
class SessionProfile(BaseModel):
    available_capital: float | None = None       # 可用资金池
    capital_currency: str = "CNY"                 # 币种
    risk_tolerance: Literal["conservative", "balanced", "aggressive"] | None = None  # 风险偏好
    max_single_position_pct: float | None = None  # 单票最大仓位 / 集中度(%)
    horizon: Literal["short", "medium", "long"] | None = None  # 投资期限
    constraints: str | None = None                # 偏好 / 禁投，自由文本
    confirmed_at: str | None = None               # 最近一次用户确认时间戳
```

存储（照搬 portfolio：`store.save_portfolio` / `store.get_portfolio`）：
- 新增 `session_profile` 表，按 `session_id` 存一行 JSON。
- 新增 `store.get_session_profile(session_id) -> SessionProfile`、
  `store.save_session_profile(session_id, profile)`。
- 会话删除时级联清理（与 portfolio 一致）。

约束：
- 这份 profile 是**唯一真相**。全字段 `Optional`，允许逐步填。
- 只有写进该表的值才算"已确认"；未进表的抽取结果仅是"提议"。
- 币种独立成字段，消除"资金池单位/币种歧义"这一类算错根源。

## 5. 后端

### 5.1 Prompt 注入（锚定）

在 [prompt.py](../../../tradingagents/advisor/prompt.py) 模板新增一段
`# 用户会话档案(已确认,强约束)`，由 [chat.py](../../../api/routes/chat.py) 的
`build_system_prompt` 注入。渲染示例：

```
# 用户会话档案(已确认,强约束)
- 可用资金池: 300000 CNY
- 风险偏好: 稳健
- 单票最大仓位: 25%
- 投资期限: 中期
- 偏好/禁投: 不碰白酒板块
```

未设置的字段标注"未设置"。新增行为准则：**这些是用户确认过的事实，必须直接使用，
禁止重新推断或猜测。**

### 5.2 工具 `propose_session_facts(...)`（复刻 `request_export_scope`）

LLM 从对话嗅到事实时调用。**不写库**，仅返回 JSON 供前端渲染确认卡片：

```json
{"proposal": {"available_capital": 300000, "capital_currency": "CNY"},
 "instruction": "已向用户弹出确认卡片，在用户确认前这些值未生效，不得据此计算。"}
```

入参校验（非法即抛 `ValueError`，由 engine 兜成 `NO_DATA_AVAILABLE: tool error`）：
- `available_capital` 不得为负；`capital_currency` 非空；`max_single_position_pct` 在 (0, 100]；
  `risk_tolerance` / `horizon` 取值合法。

### 5.3 工具 `compute_position_sizing(...)`（代码层硬约束 + 正确算术）

LLM 计算仓位 / 配置金额时**必须**走此工具。从已确认 profile 读资金池与单票上限：

- 资金池为空 → 返回 `NEED_CONFIRMATION: 缺少可用资金池，请先确认参数面板` 哨兵串
  （复刻 `NO_DATA_AVAILABLE` 机制，engine 已识别）。LLM 只能反问，无法瞎算。
- 参数齐全 → 由 **Python 做算术**（配置金额、股数、是否超单票上限），返回结构化结果。
  消除 LLM 心算错误。
- 超单票上限 → 结果中带 `exceeds_max: true` 标记，供 LLM 提示用户。

两个工具通过 `load_profile` 闭包获取 session profile，方式同 export 工具的 `load_context`
（[chat.py:286-299](../../../api/routes/chat.py#L286)）。`NEED_CONFIRMATION:` 加入
[tools.py](../../../tradingagents/advisor/tools.py) 的哨兵前缀集合，使其被 `is_no_data` 识别。

### 5.4 新增路由

`PUT/GET /api/chat/sessions/{session_id}/profile`，紧挨现有 portfolio 路由
（[chat.py:239-260](../../../api/routes/chat.py#L239)）。`PUT` 写库即视为用户确认，
更新 `confirmed_at`。

## 6. 前端（Next.js 16 / React 19，动手前先查 `node_modules/next/dist/docs/`）

### 6.1 会话参数面板 `components/chat/ProfilePanel.tsx`

- 放置于 chat 页侧栏，与持仓表（`HoldingsTable`）并列。
- 固定字段表单：可用资金池(+币种)、风险偏好(下拉)、单票最大仓位(%)、
  投资期限(下拉)、偏好/禁投(文本框)。
- 手填手改，"保存" → `PUT .../profile`，写库即"已确认"。
- 加载会话时 `GET .../profile` 回填。

### 6.2 确认卡片（复刻现有导出选项渲染路径）

[ChatMessage.tsx](../../../webui/components/chat/ChatMessage.tsx) 已能渲染导出选项；
新增识别 `propose_session_facts` 的 payload，渲染成卡片：**预填抽取值、字段可改**，
底部"确认填入 / 忽略"两个按钮。
- "确认填入" → `PUT .../profile` 落库，面板高亮更新。
- "忽略" → 不写库，提议作废。

## 7. 数据流闭环

```
用户："我有30万"
  → LLM 调 propose_session_facts
  → 前端渲染确认卡片(预填 300000 CNY，可改)
  → 用户点"确认填入" → PUT .../profile 落库
  → 下一轮 system prompt 注入"可用资金池 300000 CNY"
  → LLM 算仓位调 compute_position_sizing(从 profile 读到 300000)
  → Python 算术返回正确金额/股数 + 超限标记
```

## 8. 确认时机规则

**代码层（硬兜底）**：`compute_position_sizing` 缺资金池 → `NEED_CONFIRMATION:` 哨兵，
LLM 被迫反问。

**Prompt 层（覆盖代码够不到的场景）**，新增两条行为准则：
1. **缺参数即问**：回答需要某会话档案字段而该字段"未设置"时，先反问补齐，
   不得用默认值或猜测值往下算。
2. **推断即复述**：从对话临时推断出未确认的关键事实时，必须先调
   `propose_session_facts` 弹确认卡片，用户确认前不得据此给操作建议。

## 9. 错误处理

- profile 表不存在 / 读失败 → 视为空 profile（全字段未设置），不崩。
- `propose_session_facts` / `compute_position_sizing` 非法入参 → 抛 `ValueError`，
  被 [engine.py:42](../../../tradingagents/advisor/engine.py#L42) 兜成
  `NO_DATA_AVAILABLE: tool error`，LLM 据此说明而非崩溃。
- 确认卡片 payload 前端解析失败 → 降级为普通文本显示，不阻塞会话。

## 10. 测试（`pytest -m unit`，沿用注入 fake graph 的现有套路）

- store：profile 存取、删除级联。
- 工具单测：
  - 资金池为空 → `compute_position_sizing` 返回 `NEED_CONFIRMATION:`。
  - 参数齐全 → 算术正确；超单票上限带标记。
  - `propose_session_facts` 非法值（负资金 / 空币种 / 越界百分比）校验。
  - `is_no_data` 识别 `NEED_CONFIRMATION:` 前缀。
- prompt：已确认 profile 正确注入；空 profile 字段标"未设置"。
- 路由 smoke：`PUT/GET .../profile` 注册且读写通。
- 前端：确认卡片渲染 + "确认填入 / 忽略"按钮行为（按现有前端测试惯例）。

## 11. 涉及文件

新增：
- `tradingagents/advisor/profile_tools.py`（`propose_session_facts`、`compute_position_sizing`）
- `webui/components/chat/ProfilePanel.tsx`
- 相应测试文件。

修改：
- `api/schemas.py`（`SessionProfile`）
- `api/store.py`（profile 存取 + 级联删除）
- `api/routes/chat.py`（profile 路由、工具装配、prompt 注入入参）
- `tradingagents/advisor/prompt.py`（注入段 + 两条行为准则）
- `tradingagents/advisor/tools.py`（`NEED_CONFIRMATION:` 哨兵前缀）
- `webui/components/chat/ChatMessage.tsx`（确认卡片渲染）
- `webui/lib/api.ts`（profile 端点）
- `CHANGELOG.md`
