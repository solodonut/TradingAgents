# WebUI 辩论进度可视化设计

**日期**: 2026-07-02
**状态**: 已确认，待实现

## 背景与问题

TradingAgents 流水线里的「多空辩论」和「三方风险辩论」耗时较长，但 WebUI 在这两个阶段只显示一个笼统的 `WORKING`，用户看不到：

1. 当前在第几轮（`第 2/3 轮`）；
2. 现在轮到谁发言（多方/空方；激进/保守/中立）；
3. 每一轮到底说了什么。

同时，辩论的完整历史其实已经随 `final_state` 落库进 `result_json`（`investment_debate_state.history` / `risk_debate_state.history`），但历史详情页从不渲染它们。

**目标**：直播时展示「第几轮 + 谁在发言 + 正文流式」，历史 run 也能回放同样的辩论过程。

## 关键事实（已核实）

- LangGraph 以 `stream_mode="values"` 流式输出：**每个 chunk 都是完整累积 state**，因此 `count` 单调递增且每个 chunk 都在 → 靠「count 相比上次增长」判定有新发言。
- 多空辩论 `investment_debate_state`：每位发言者 `count += 1`，`current_response` 形如 `"Bull Analyst: ..."` / `"Bear Analyst: ..."`，顺序 Bull→Bear 交替。总数 = `2 × max_debate_rounds`。
- 风险辩论 `risk_debate_state`：每位发言者 `count += 1`，`latest_speaker ∈ {Aggressive, Conservative, Neutral}`，对应正文分别在 `current_aggressive_response` / `current_conservative_response` / `current_neutral_response`（按 `latest_speaker` 取），顺序 Aggressive→Conservative→Neutral。总数 = `3 × max_risk_discuss_rounds`。
- 轮次换算：多空 `round = ceil(count / 2)`；风险 `round = ceil(count / 3)`。
- 总轮次配置：`graph.config["max_debate_rounds"]` / `graph.config["max_risk_discuss_rounds"]`，runner 可直接读。
- runner 现状：`chunk_to_events` 只处理 `REPORT_SECTIONS`（8 个报告字段），辩论 state 的 chunk 被完全忽略。
- SSE 前端管道：`webui/lib/sse.ts` 注册监听 `["agent_status","message","report_section","stats","done","error","cancelled"]`；`webui/lib/types.ts` 的 `SSEEvent` 联合类型枚举同一批事件。

## 轮次/发言人换算

| 队伍 | round | total | 发言人判定 |
|------|-------|-------|-----------|
| invest | `ceil(count/2)` | `max_debate_rounds` | count 奇=多方(Bull)，偶=空方(Bear) |
| risk | `ceil(count/3)` | `max_risk_discuss_rounds` | `latest_speaker` |

## 设计

### 1. 后端 `api/runner.py`

新增独立、可测的纯函数 `debate_events(chunk, tracker, rounds_cfg) -> list[dict]`：

- 入参：当前 chunk（完整 state）、可变 tracker（记 `last_invest_count` / `last_risk_count`）、轮次配置 `{"invest_total": N1, "risk_total": N2}`。
- 检测两个辩论 state 的 `count` 是否比 tracker 记录的更大；每增长一步就发一个 `debate_round` 事件。
- 事件 payload：
  ```json
  {
    "team": "invest" | "risk",
    "round": <int>,
    "total": <int>,
    "speaker": "bull" | "bear" | "aggressive" | "conservative" | "neutral",
    "speaker_label": "多方" | "空方" | "激进" | "保守" | "中立",
    "content": "<current_response 去掉 'Xxx Analyst: ' 前缀>"
  }
  ```
- 正文来源：多空取 `current_response`；风险按 `latest_speaker` 取 `current_{aggressive|conservative|neutral}_response`。剥掉 `"Xxx Analyst: "` 前缀。若一个 chunk 内 count 跳增多步（正常不会，但防御性处理），按需回退用 `history` 拆分补齐，保证不漏发言。

在 `AnalysisRunner.run()` 内：
- run 开始时构造 `rounds_cfg`（从 `graph.config` 读，缺省兜底 `1`）和 `tracker = {}`。
- 流循环里，在既有 `chunk_to_events(...)` 之后追加 `debate_events(...)` 的事件入队。
- `chunk_to_events` 与 `REPORT_SECTION_KEYS` 落库逻辑保持不变。
- **不改数据库 schema、不改 `complete_run`**（历史仍走 `result_json`）。

### 2. SSE 管道

- `webui/lib/types.ts`：`SSEEvent` 联合类型加一支
  ```ts
  | { event: "debate_round"; data: {
      team: "invest" | "risk";
      round: number; total: number;
      speaker: string; speaker_label: string; content: string;
    } }
  ```
- `webui/lib/sse.ts`：监听数组加 `"debate_round"`。

### 3. 前端直播 `webui/app/page.tsx`

`followRun` 的事件处理里新增 `debate_round` 分支：

- **消息流**：追加一条气泡，`agent` 标签形如 `多空辩论 · 第 1/3 轮 · 多方`（风险同理），`content` 为正文，复用现有 message 渲染。
- **Matrix 状态**：把 `statuses["debate"]`（invest）或 `statuses["risk_debate"]`（risk）设为 `working`，并写入一条明细字符串 `第 X/N 轮 · 空方` 存入新的 `details: Record<string,string>` state。
- 收到属于某队伍的第一条 `debate_round` 即认为该阶段开始（比旧的深/快模型启发式更可靠）。旧启发式仅作为「打开一个正在运行、但本端未订阅的 run」时的兜底，保留不动。

### 4. Agent Matrix `webui/components/AgentProgress.tsx`

- 组件签名加可选 `details?: Record<string, string>`。
- 当某行 `working` 且 `details[id]` 存在时，在 `label` 下方多渲染一行小字（如 `第 2/3 轮 · 空方`），替换/补充原本第二行的 `a.id`。仅辩论两行会用到；其余行行为不变。

### 5. 历史回放 `webui/components/RunDetail.tsx`

- 新增解析工具：把 `result.investment_debate_state.history` 和 `risk_debate_state.history` 按 `"Xxx Analyst:"` 前缀切成有序发言，映射出 `{round, speaker_label, content}` 列表。
- 在 SECTIONS 渲染顺序中：多空辩论块插在「研究经理(investment_plan)」之前，风险辩论块插在「组合经理(final_trade_decision)」之前。
- 每条发言渲染为带轮次/发言人标题的小块，正文走现有 Markdown 渲染。
- 若历史里没有这两个 state（老数据），静默跳过，不报错。

## 不做（YAGNI）

- 不改数据库 schema / `complete_run` / `update_partial_result`。
- 不改任何 LangGraph 节点或 agent 代码（researcher / risk debator 不动）。
- 不删除 `deriveHistoryProgress` 的深/快模型启发式（仍作兜底）。
- 不做 token 级流式（辩论正文按「一位发言者一条」整段推送即可）。

## 测试

- **后端单测**（`tests/webui/`，`unit` 标记，mock 无网络）：
  - `debate_events`：喂入连续 chunk（count 从 0→1→2→…），断言每步发出正确的 `debate_round`（team/round/total/speaker/label/去前缀 content）。
  - 幂等：同一 count 的重复 chunk 不重复发事件。
  - 风险队伍：`latest_speaker` 三种取值映射正确、round 换算正确。
  - runner 集成：用 fake graph（`app.state.graph_factory` 既有测试模式）跑一遍带辩论 state 的 chunk 序列，断言队列里出现 `debate_round` 且报告事件不受影响。
- **前端**：类型编译通过（`tsc`），本地 `npm run dev` 手动验证直播明细与历史回放。
- 收尾：`.venv/bin/python -m ruff check .` + `.venv/bin/python -m pytest -m "not integration"`。

## 涉及文件

| 文件 | 改动 |
|------|------|
| `api/runner.py` | 新增 `debate_events`；`run()` 内接入 |
| `webui/lib/types.ts` | `SSEEvent` 加 `debate_round` |
| `webui/lib/sse.ts` | 监听数组加 `debate_round` |
| `webui/app/page.tsx` | `followRun` 处理 `debate_round`；新增 `details` state |
| `webui/components/AgentProgress.tsx` | 可选 `details`，辩论行多显示轮次明细 |
| `webui/components/RunDetail.tsx` | 解析并渲染历史辩论 |
| `tests/webui/test_runner.py`（或新文件） | `debate_events` 单测 |
