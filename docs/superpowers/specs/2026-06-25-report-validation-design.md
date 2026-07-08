# 报告校验与自动修正节点 — 设计文档

- 日期：2026-06-25
- 状态：已批准（待实现计划）
- 范围：在交易决策流水线末尾新增一个校验节点，确保各报告中的**标的名称**与**可验证市场数字**与 ticker 一致，发现不一致时**自动修正原文**，并产出一份校验报告。

## 1. 背景与目标

仓库已有反幻觉机制：`resolve_instrument_identity()` 把权威标的名称/身份注入每个分析师 prompt（`instrument_context`），`build_verified_market_snapshot()` 给市场数字提供"source of truth"。但这些都作用于**输入阶段**——没有任何环节在报告**生成之后**复核报告文本是否真的与权威名称/数字一致。

目标：在最终决策产出后，新增一个校验环节，对所有报告文本做事实层面的复核，自动修正错误的标的名称和可验证数字，并输出一份"校验报告"说明改了什么。

**非目标**：不改写分析、观点、结论、措辞或结构；不校验无机器标准答案的内容（新闻措辞、主观判断等）。

## 2. 修正范围（权威来源）

只修正有确定性"标准答案"可比对的两类事实：

1. **标的名称 / 身份**：来源为 `instrument_context`（已在 state，含 `resolve_instrument_identity()` 解析出的权威名称，如 `航空航天ETF天弘`）。
2. **可验证市场数字**：来源为 `build_verified_market_snapshot(ticker, date)` 产出的权威价格/指标表。

其余分析文字一律不动。

## 3. 架构与位置

- 新增模块：`tradingagents/graph/report_validator.py`（与 `reflection.py`、`signal_processing.py` 同层）。
- 新增图节点：`report_validator_node`，插在 `portfolio_manager` 之后、`END` 之前。
- 在 `GraphSetup`（`tradingagents/graph/setup.py`）中连边：`portfolio_manager → report_validator → END`。
- 节点函数签名遵循现有约定：`report_validator_node(state) -> dict`，返回写回 state 的字段。

### 受校验的报告字段（7 个文本字段）

| 字段 | 产出节点 |
|---|---|
| `market_report` | market_analyst |
| `sentiment_report` | sentiment_analyst |
| `news_report` | news_analyst |
| `fundamentals_report` | fundamentals_analyst |
| `investment_plan` | research_manager |
| `trader_investment_plan` | trader |
| `final_trade_decision` | portfolio_manager |

## 4. 数据流

节点拿到 `final_state` 后：

1. **建立标准答案（确定性，不走 LLM）**
   - 名称/身份：从 `state["instrument_context"]` 读取（已预计算，不重复走网络）。
   - 数字：调 `build_verified_market_snapshot(ticker, date)` 拿权威表。
   - 任一来源不可用（返回 `NO_DATA_AVAILABLE` 或为空）→ **跳过对应维度**，不报错。

2. **逐字段修正**：对 7 个字段各跑一次 `quick_thinking_llm`（控制成本）。prompt 严格限定：
   > "以下是权威标的名称与市场数据。只修正文中错误的标的名称和这些可验证数字，禁止改动任何分析、观点、结论、措辞或结构。无错则原样返回。"
   - 用结构化输出返回 `{corrected_text, corrections: [{field, original, fixed, reason}]}`。
   - 字段为空/缺失则跳过。

3. **写回**：修正后的文本覆盖回各字段；汇总所有 `corrections` 到新 state 字段 `validation_report`。

## 5. 校验报告产出（"校验功能"）

- 新增 `AgentState` 字段 `validation_report: str`（定义在 `tradingagents/agents/utils/agent_states.py`）。
- 内容为一段 Markdown：按报告分组列出发现的不一致（原值 → 修正值 → 依据）。
- 全部一致时输出明确的"✅ 全部一致"提示。
- 维度被跳过时注明"未校验（数据不可用）"。
- 该字段可被 CLI / webui 读取展示（本设计只负责产出字段，展示层接入由后续工作决定，不在本 spec 范围）。

## 6. 错误处理

- **标准答案缺失**：跳过该维度，`validation_report` 注明"未校验（数据不可用）"，不抛异常。
- **结构化输出失败**：复用现有 `invoke_structured_or_freetext` 回退机制；若仍失败，该字段**保留原文**并在 `validation_report` 标注"校验失败"。
- **信号稳定性**：只修正名称/数字、不动评级词，`process_signal(final_trade_decision)` 结果不变，无需重新抽取信号。

## 7. 配置开关

- `DEFAULT_CONFIG` 新增 `report_validation_enabled: bool`，默认 `True`。
- 支持 `TRADINGAGENTS_REPORT_VALIDATION_ENABLED` 环境变量覆盖（沿用现有 `TRADINGAGENTS_*` 类型感知机制）。
- 关闭时节点**直通透传**（不产生任何 LLM 调用），`validation_report` 置为空字符串 `""`。
- 修正所用 LLM 为 `quick_thinking_llm`（非 `deep_thinking_llm`）。

## 8. 测试（unit，mock LLM，无网络/无真实 key）

1. **修正正确性**：注入含错误名称/数字的报告，断言对应字段被修正、`validation_report` 列出条目。
2. **标准答案缺失**：snapshot / instrument_context 不可用时跳过该维度且不崩溃。
3. **开关关闭**：节点透传，无 LLM 调用，报告字段原样。
4. **信号稳定性**：修正前后 `process_signal` 结果一致。
5. **结构化输出失败回退**：mock 结构化失败，断言字段保留原文并标注"校验失败"。

## 9. 受影响文件（预估）

- 新增：`tradingagents/graph/report_validator.py`
- 修改：`tradingagents/graph/setup.py`（连边）
- 修改：`tradingagents/agents/utils/agent_states.py`（新增 `validation_report` 字段）
- 修改：`tradingagents/default_config.py`（新增 `report_validation_enabled`）
- 可能修改：`tradingagents/graph/trading_graph.py`（节点装配 / 传入 quick LLM）
- 新增：`tests/test_report_validator.py`
- 维护：`CHANGELOG.md`
