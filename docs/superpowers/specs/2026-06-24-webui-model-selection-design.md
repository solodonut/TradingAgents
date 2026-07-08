# Web 页面模型选择 — 设计文档

- **日期**: 2026-06-24
- **状态**: 已确认，待实现

## 背景与目标

让用户在 Web 页面自行选择 LLM 模型，覆盖两处：

1. **分析功能**（TradingAgents 工作台）：分别选择 `deep_think_llm`（深度思考）和 `quick_think_llm`（快速思考）。
2. **Chat 功能**：选择对话用的模型。

## 范围与约束

- **限定当前已配置的 provider**：不做跨 provider 切换、不做 API key 检测。provider 由后端 `configured_provider` 驱动（当前默认 `ibm_ica`），前端不暴露切换 UI。
- 模型列表来源：复用 `tradingagents/llm_clients/model_catalog.py` 的 `get_model_options(provider, mode)`。
- 选择记忆：浏览器 `localStorage`，后端无持久化改动。
- 不处理「Custom 文本框降级」：当前 provider（ibm_ica）有具体模型列表，无需此边界逻辑。

## 现状（关键事实）

- **分析功能后端已打通**：`AnalysisRequest` 已有 `llm_provider` / `deep_think_llm` / `quick_think_llm` 字段；`real_graph_factory`（`api/main.py`）收到非空值即覆盖 `DEFAULT_CONFIG`。前端 `ConfigCard.tsx` 目前写死传 `null`。
- **Chat 功能后端未打通**：`real_chat_llm_factory`（`api/main.py`）硬读 `DEFAULT_CONFIG`，不接受参数；`ChatRequest` 无模型字段。
- **无可用模型列表端点**：`GET /api/config/options` 仅返回 `configured_*` 当前值；`model_catalog.py` 未被 API 层导入。

## 设计

### 后端

**(1) 扩展 `GET /api/config/options`**
- 文件：`api/routes/config.py`、`api/schemas.py`。
- `ConfigOptions` 新增字段：
  ```python
  model_options: dict[str, list[tuple[str, str]]]
  # { "deep": [(label, model_id), ...], "quick": [(label, model_id), ...] }
  ```
- 取值：`get_model_options(configured_provider, "deep")` 与 `get_model_options(configured_provider, "quick")`。

**(2) Chat 打通模型参数**
- `api/schemas.py`：`ChatRequest`（发消息请求体）新增 `chat_llm: str | None = None`。
- `api/main.py`：`real_chat_llm_factory` 改为接受可选 `model` 参数；`model` 为空回退 `DEFAULT_CONFIG["quick_think_llm"]`，provider 仍用 `configured_provider`。
- `api/routes/chat.py`：发消息路由把 `request` 中的 `chat_llm` 透传给 `chat_llm_factory(model=...)`。
- 测试用的 fake factory 需同步接受可选参数。

**(3) 分析后端**：不改动。

### 前端

**(4) 类型 + API client**
- `webui/lib/types.ts`：`ConfigOptions` 加 `model_options`；Chat 发消息类型加 `chat_llm`。
- `webui/lib/api.ts`：发消息函数支持携带 `chat_llm`。

**(5) 分析页 `webui/components/ConfigCard.tsx`**
- 新增两个下拉：**深度模型**（deep）、**快速模型**（quick），选项来自 `model_options`。
- 默认值：`configured_deep_llm` / `configured_quick_llm`。
- 用户改动写入 `localStorage`，刷新后回填。
- 提交时把选中值填入 `deep_think_llm` / `quick_think_llm`（替换写死的 `null`）。

**(6) Chat 页 `webui/app/chat/page.tsx`**
- 顶部新增**模型下拉**，选项 = `model_options.deep` + `model_options.quick` 合并去重。
- 默认值：`configured_quick_llm`；改动写 `localStorage`。
- 发消息时带 `chat_llm`。

## 数据流

```
配置中心 (.env / DEFAULT_CONFIG)
   → GET /api/config/options { configured_*, model_options }
       → 分析页 ConfigCard（默认值 + 下拉选项, localStorage）
           → POST /api/analysis { deep_think_llm, quick_think_llm }
               → real_graph_factory 覆盖 config
       → Chat 页（默认值 + 下拉选项, localStorage）
           → POST 发消息 { message, chat_llm }
               → real_chat_llm_factory(model=chat_llm)
```

## 测试

- 后端（`tests/webui/`）：
  1. `GET /api/config/options` 返回包含非空 `model_options.deep` / `model_options.quick`。
  2. Chat 发消息带 `chat_llm` 时，factory 收到对应 model；不带时回退默认。
  - 沿用现有 fake factory 注入方式（`app.state.*_factory`）。
- 前端：无测试框架，手动验证下拉渲染、默认值、localStorage 回填、提交参数。
- 收尾：`ruff check .` + `pytest -m "not integration"`。

## 非目标（YAGNI）

- 跨 provider 切换 / provider 下拉。
- API key 可用性检测。
- Custom / 自由文本模型输入。
- 模型选择的后端持久化（数据库）。
