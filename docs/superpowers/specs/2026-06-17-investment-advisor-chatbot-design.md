# 投资操作顾问 Chatbot — 设计文档

- **日期**: 2026-06-17
- **状态**: 已批准,待编写实现计划
- **作者**: 头脑风暴产出 (Sisyphus + 用户)

## 1. 目标与范围

在现有 TradingAgents WebUI(FastAPI `api/` + Next.js `webui/`)中,新增一个**投资操作顾问对话机器人**。它是一个**快速咨询层**,叠加在已完成的多智能体分析报告之上:基于(a)已生成的分析报告、(b)实时查询的市场数据、(c)用户上传截图提取的当前持仓与交易记录,给出**具体、可执行、有研究依据**的操作建议与解释。

与同目录下 `2026-06-15-webui-chatbot-design.md`(那是把 CLI 分析体验搬到网页的"对话式分析向导")是**两个不同的功能**:本文档的顾问机器人**不触发**昂贵的 `propagate()` 分析,只**消费**其产出的报告。

### 已确认的范围决策

| 维度 | 决策 |
|---|---|
| 与分析管线的关系 | **消费已有报告**——只读取已完成 run 的报告,不触发 `propagate()` |
| 图片上传处理 | **Vision LLM 提取**——截图经视觉模型提取持仓/交易为结构化数据,对话中可纠错 |
| 实时数据来源 | **复用现有 dataflows**——`route_to_vendor` 的函数作为 LLM 工具 |
| 交互界面 | **新 Next.js 页面** `/chat` + 新 `api/routes/chat.py` 路由 |
| 建议具体度 | **具体建议 + 研究框架 + 免责声明**——引用具体 agent/报告,附 not-financial-advice |
| 会话与持仓持久化 | **持久化会话 + 持仓上下文**——存入现有 SQLite store(`~/.tradingagents/webui.db`) |

### 对话引擎架构选择

**方案 A — 手写工具调用循环**(已确认采用):
`chain = prompt | llm.bind_tools(tools)`,手动检查 `result.tool_calls` 决定是否继续循环。
- **理由**:最直接映射到现有 SSE 流式模式(`runner.py` 的 `queue.Queue` → `asyncio.to_thread(q.get)` → `EventSourceResponse`);token 和工具调用状态都能干净地推成 SSE 事件;对话场景不需要 LangGraph StateGraph 的复杂编排。
- 否决方案 B(`create_react_agent`):流式 token 与工具状态事件需额外适配 LangGraph stream 模式。
- 否决方案 C(自定义 StateGraph):对单一对话场景过度设计(YAGNI)。

### 非目标 (YAGNI)

- **不触发分析**:不调用 `propagate()`,不做"无报告则跑分析"的混合编排。
- **不接入决策日志记忆**:本期不与 `~/.tradingagents/memory/` 的反思记忆系统打通(可作后续迭代)。
- **不做多用户/认证**:沿用项目单用户本地工具定位。
- **不改 `tradingagents/` 核心或 `cli/`**:仅新增 `tradingagents/advisor/` 模块、扩展 `api/`、新增 `webui/app/chat/`。
- **不做 WebSocket**:服务器单向推送,SSE 足够。

## 2. 现有系统约束(探索结论)

### 后端 (`api/`)
- 路由注册:`main.py` 用延迟导入 + `app.include_router(router)`;新路由在文件底部追加(`# noqa: E402`)。
- SSE 模式:后台 daemon thread → `queue.Queue` → `async` 生成器经 `asyncio.to_thread(q.get, True, 1.0)` 抽取 → `EventSourceResponse`(`from sse_starlette.sse import EventSourceResponse`)。事件形如 `{"event": str, "data": dict}`,`None` 作结束哨兵(必须在 `finally` 中投递)。前端断连用 `await request.is_disconnected()` 检测。
- 单 run 锁:`store.has_running_run()` → 409,**只针对 analysis_runs**;对话不受此锁约束,可并发。
- 可测试性:`app.state.graph_factory = None` + startup hook 仅在未注入时赋真实工厂;测试直接注入 fake。对话引擎沿用同一模式新增 `app.state.chat_llm_factory`。
- SQLite store:`store.py` 单连接每操作(`check_same_thread=False`,`row_factory=sqlite3.Row`),单 `threading.Lock` 守护写,`_SCHEMA` 用 `CREATE TABLE IF NOT EXISTS` 在 `__init__` 应用;有 `_dumps()`/`_json_default()` JSON 辅助。
- Pydantic:纯 `BaseModel`;模块级 `Literal` 约束串;`Field(default_factory=...)` 默认可变值;`@field_validator`(v2);`str | None`(3.10+ 联合语法);命名 `XxxRequest`/`XxxSummary`/`XxxResult`/`XxxOptions`。

### 已完成报告的结构(顾问机器人消费对象)
- 持久化:`analysis_runs.result_json` 存完整 `AgentState` dict;经 `GET /api/history/{run_id}` → `RunResult.result`(`Record<string,string>`)读取。
- 7 个报告字段(`tradingagents/agents/utils/agent_states.py`):
  | 字段 | 来源 Agent |
  |---|---|
  | `market_report` | 市场/技术分析师 |
  | `sentiment_report` | 情绪分析师(结构化,含 `**Overall Sentiment:**` 头) |
  | `news_report` | 新闻分析师 |
  | `fundamentals_report` | 基本面分析师 |
  | `investment_plan` | 研究经理(`ResearchPlan`) |
  | `trader_investment_plan` | 交易员(`TraderProposal`) |
  | `final_trade_decision` | 投资组合经理(`PortfolioDecision`,含 `**Rating**:`) |
- 内部辩论态(可选引用):`investment_debate_state`(bull/bear)、`risk_debate_state`(aggressive/conservative/neutral)。
- 抽取决策:`parse_rating()` → 五档 `Buy|Overweight|Hold|Underweight|Sell`,存 `decision` 列。

### dataflows 工具层(实时数据来源)
- 全部为 `@tool` 装饰的 LangChain 工具,内部调 `route_to_vendor(method, *args)`,**返回 `str`,从不抛异常**;不可用时返回以 `NO_DATA_AVAILABLE:` 或 `DATA_SOURCE_DISABLED:` 开头的哨兵串。统一从 `tradingagents.agents.utils.agent_utils` 导入。
- 可用工具(签名):
  - `get_stock_data(symbol, start_date, end_date) -> str`(OHLCV CSV)
  - `get_indicators(symbol, indicator, curr_date, look_back_days=30) -> str`(rsi/macd/boll/atr/sma/ema…)
  - `get_fundamentals(ticker, curr_date)`、`get_balance_sheet/get_cashflow/get_income_statement(ticker, freq="quarterly", curr_date=None)`
  - `get_news(ticker, start_date, end_date)`、`get_global_news(curr_date, look_back_days=None, limit=None)`、`get_insider_transactions(ticker)`
  - `get_macro_indicators(indicator, curr_date, look_back_days=None)`(cpi/unemployment/fed_funds_rate/vix…)
  - `get_prediction_markets(topic, limit=None)`
- 配置单例:`route_to_vendor` 前须 `set_config(config_dict)`(进程全局,初始化一次)。

### LLM 层(对话 + 视觉)
- `create_llm_client(provider, model, base_url=None, **kwargs).get_llm()` 返回标准 LangChain chat model(`ChatOpenAI`/`ChatAnthropic`/`ChatGoogleGenerativeAI`)。
- 工具绑定模式(`market_analyst.py:80`):`chain = prompt | llm.bind_tools(tools)`;`result.tool_calls` 为空即终态。
- 多模态:anthropic/google/openai 返回的模型支持图片输入;`normalize_content` 覆写**只处理响应,不动输入**,故可直接传标准多模态 `HumanMessage`:
  ```python
  HumanMessage(content=[
      {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
      {"type": "text", "text": "提取所有持仓(ticker, shares, value)"},
  ])
  ```
- 视觉模型选择:`model_catalog` **无显式 vision 标志**;按家族判定——anthropic(全 Claude 3+)、google(全 Gemini 2.5+/3)、openai(GPT-4o/4.1/5.x)均支持;deepseek/qwen/glm/ollama 不保证。后端须校验所选 provider 是否支持视觉。

### 前端 (`webui/`)
- App Router 单页 SPA;新增 `webui/app/chat/page.tsx` 即得 `/chat` 路由,无需路由配置。
- SSE 消费:`webui/lib/sse.ts` 用原生 `EventSource` + 命名事件监听器。
- API base:`webui/lib/api.ts` `process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000"`。
- 样式:**非标准 shadcn**,`components.json` 为 `base-nova`(底层 `@base-ui/react`,非 Radix);Tailwind 4;暗色 OKLCH 主题;Geist 字体;`lucide-react` 图标;`react-markdown`+`remark-gfm`(`<MarkdownContent/>`);`cn()` = clsx+tailwind-merge。复用现有 `Button`/`Card` 或裸 div(`rounded-lg border border-border bg-card`)。
- **Next.js 16 有破坏性变更**:写页面前先查 `node_modules/next/dist/docs/`(见 `webui/AGENTS.md`)。

## 3. 系统组件划分

```
api/
  routes/chat.py          ← 新增:会话 CRUD + 持仓提取 + 流式对话端点
  schemas.py              ← 扩展:Chat* / PortfolioHolding 等模型
  store.py                ← 扩展:_SCHEMA 加 3 张表 + 对应 CRUD 方法
  main.py                 ← 扩展:注册 chat router + chat_llm_factory 注入点

tradingagents/advisor/    ← 新增模块(对话引擎核心,与 agents/ 平级)
  __init__.py
  engine.py               ← 工具调用循环:prompt | llm.bind_tools(tools)
  tools.py                ← 从 agent_utils 收集 dataflows 工具
  vision.py               ← 截图 → 结构化持仓提取(多模态 HumanMessage)
  prompt.py               ← 系统提示词(研究框架 + 引用规则 + 免责声明)
  context.py              ← 从 result_json 组装报告上下文

webui/app/chat/page.tsx   ← 新增:对话页面 (/chat 路由)
webui/components/chat/     ← 新增:ChatMessage / PortfolioUpload / HoldingsTable / RunPicker
webui/lib/                 ← 扩展:api.ts / sse.ts / types.ts
```

**关键边界:**
- `tradingagents/advisor/` 独立模块,**不依赖 `api/`**(api 依赖它)。对话引擎可单元测试、可被 CLI 复用,符合 isolation/clarity 原则。
- 单一职责:`vision.py` 只管图片提取;`tools.py` 只管工具收集;`engine.py` 只管循环;`context.py` 只管报告组装;`prompt.py` 只管提示词。

## 4. 数据流

### 主线 1 — 创建会话并绑定上下文
```
/chat 页 RunPicker 选一个已完成 run_id(可不选)
  → POST /api/chat/sessions {run_id?}
  → store.insert_chat_session() 生成 session_id
  → 从 result_json 读取 7 报告字段缓存进会话上下文
```

### 主线 2 — 上传截图提取持仓
```
上传截图 → POST /api/chat/sessions/{id}/portfolio (multipart)
  → vision.py: base64 → HumanMessage([image_url, text="提取持仓..."])
  → 视觉 LLM 返回结构化 JSON → 解析为 PortfolioHolding[] → 存 chat_portfolios
  → 返回前端 HoldingsTable(可编辑纠错)
  → 用户改完 → PUT /api/chat/sessions/{id}/portfolio 覆盖保存
```

### 主线 3 — 流式对话(核心)
```
发消息 → POST /api/chat/sessions/{id}/stream {message}
  → 组装上下文:[系统提示词] + [7 报告字段 + decision] + [持仓] + [历史消息] + [新消息]
  → engine.py 工具循环(后台 daemon thread):
      chain = prompt | llm.bind_tools([get_stock_data, get_news, ...])
      result = chain.invoke(messages)
      while result.tool_calls:
          q.put({"event":"tool_call","data":{tool,args}})           # SSE
          tool_result = run_tool(...)   # route_to_vendor,检查 NO_DATA_ 前缀
          result = chain.invoke(messages + [tool_result])
      for token in stream: q.put({"event":"token","data":{content}}) # 流式回答
      q.put({"event":"done","data":{...}}); q.put(None)              # 哨兵
  → 前端 EventSource 消费 token/tool_call/done,逐字渲染
  → 完成后 store.insert_chat_message() 持久化 user + assistant 两条
```

**关键设计点:**
- 复用 `runner.py` 完全相同的 SSE 骨架,`None` 哨兵不可省。
- 对话**不检查** `has_running_run()`(409 锁仅针对 analysis,对话可并发)。
- 工具返回以 `NO_DATA_AVAILABLE:`/`DATA_SOURCE_DISABLED:` 开头时,引擎告知 LLM 数据不可用,LLM 据实说明而非编造。

## 5. 数据模型

### SQLite 表(追加到 `store.py` 的 `_SCHEMA`,`IF NOT EXISTS` 对老库零迁移)

```sql
CREATE TABLE IF NOT EXISTS chat_sessions (
    session_id    TEXT PRIMARY KEY,
    run_id        TEXT,              -- 可空,关联 analysis_runs 作报告上下文
    title         TEXT,              -- 自动用首条消息或 ticker 生成
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS chat_messages (
    message_id      TEXT PRIMARY KEY,
    session_id      TEXT NOT NULL,   -- → chat_sessions
    role            TEXT NOT NULL,   -- 'user' | 'assistant'
    content         TEXT NOT NULL,
    tool_calls_json TEXT,            -- 可空,记录该轮调用了哪些数据工具(可追溯/审计)
    created_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS chat_portfolios (
    session_id    TEXT PRIMARY KEY,  -- 每会话一份持仓(覆盖式)
    holdings_json TEXT NOT NULL,     -- PortfolioHolding[] 序列化
    source        TEXT NOT NULL,     -- 'vision' | 'manual'
    updated_at    TEXT NOT NULL
);
```

### Pydantic 模型(追加到 `api/schemas.py`)

```python
class PortfolioHolding(BaseModel):
    ticker: str
    name: str | None = None
    shares: float | None = None
    avg_cost: float | None = None        # 成本价
    market_value: float | None = None    # 当前市值
    weight: float | None = None          # 仓位占比 %
    action: Literal["buy", "sell"] | None = None  # 交易记录(若截图含)
    trade_date: str | None = None

class ChatRequest(BaseModel):
    message: str

class ChatSessionCreate(BaseModel):
    run_id: str | None = None

class ChatMessage(BaseModel):
    message_id: str
    session_id: str
    role: Literal["user", "assistant"]
    content: str
    tool_calls: list[dict] = Field(default_factory=list)
    created_at: str

class ChatSession(BaseModel):
    session_id: str
    run_id: str | None
    title: str | None
    created_at: str
    updated_at: str

class PortfolioExtractResponse(BaseModel):
    holdings: list[PortfolioHolding] = Field(default_factory=list)
    source: Literal["vision", "manual"]
```

**设计点:**
- 持仓字段全部可空——视觉提取常缺字段,提不到就留空,用户在表格补,绝不编造。
- `tool_calls_json` 记录每轮调用的实时数据,满足"引用具体来源"的可追溯需求。
- 每会话一份持仓(`session_id` 主键),覆盖式更新,符合"提取一次、全程复用"。

## 6. 系统提示词策略、错误处理、测试

### 6a. 系统提示词 (`prompt.py`)
对应"具体建议 + 研究框架 + 免责声明",固定段:
1. **角色**:基于 TradingAgents 报告 + 实时数据 + 用户持仓给出具体、可执行的操作建议。
2. **引用规则(强约束)**:每条建议必须注明依据——引用具体 agent(如"看跌研究员指出…")、具体报告字段、或实时工具返回值。**禁止脱离报告/数据凭空给建议。**
3. **持仓感知**:结合实际仓位给相对建议(如"AAPL 占 40%,集中度偏高")而非泛泛而谈。
4. **免责声明**:每会话首条回复 + 每条明确操作建议后附 not-financial-advice,与项目 research-only 定位一致。
5. **诚实约束**:工具返回 `NO_DATA_AVAILABLE:` 时如实说明数据缺失,绝不编造价格/数字(继承 anti-hallucination DNA)。

### 6b. 错误处理
- **工具失败**:`route_to_vendor` 返回哨兵串(从不抛),引擎把"数据不可用"喂给 LLM,据实告知。
- **视觉提取失败/无法解析**:返回空 `holdings[]` + 提示手动录入或重传清晰截图。
- **无视觉模型**:所选 provider 不支持视觉(如 deepseek)时,后端校验后返回明确错误,引导改用 anthropic/google/openai。
- **会话/run 不存在**:沿用现有 404 约定。
- **流中断**:`request.is_disconnected()` 检测 + 清理 queue,沿用 `analysis.py` 模式。
- **LLM 调用异常**:推 `{"event":"error",...}` SSE + 哨兵,前端展示错误气泡。

### 6c. 测试方案(`pytest -m unit`,无网络无真实 key)
- `advisor/` 单测:注入 fake LLM(固定 tool_calls 序列)测工具循环;注入 fake 视觉响应测 `vision.py` 解析;测 `context.py` 从 result_json 正确组装 7 字段。
- `api/routes/chat.py` 路由测:`app.state.chat_llm_factory = fake` 注入(沿用 `graph_factory` 模式),测会话 CRUD、SSE 事件序列、持仓提取/覆盖、并发不受 409 锁影响。
- store 测:3 张新表 CRUD + 老库兼容(`IF NOT EXISTS`)。
- 标记 `unit`,复用 `conftest.py` 的 placeholder key 注入。

### 6d. 前端注意事项
- **非标准 shadcn**:`base-nova` + `@base-ui/react`,复用现有 `Button`/`Card` 或裸 div 模式(`border border-border bg-card`)。
- 暗色 OKLCH 主题、Geist 字体、`lucide-react`、`react-markdown`+`remark-gfm` 渲染回复。
- 写页面前先查 `node_modules/next/dist/docs/`(Next.js 16 破坏性变更)。

## 7. API 端点汇总

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/chat/sessions` | 创建会话(可带 `run_id`) |
| GET | `/api/chat/sessions` | 会话列表 |
| GET | `/api/chat/sessions/{id}` | 会话详情(含历史消息) |
| DELETE | `/api/chat/sessions/{id}` | 删除会话 |
| POST | `/api/chat/sessions/{id}/portfolio` | 上传截图提取持仓(multipart) |
| PUT | `/api/chat/sessions/{id}/portfolio` | 覆盖保存(手动纠错后的)持仓 |
| GET | `/api/chat/sessions/{id}/portfolio` | 读取当前持仓 |
| POST | `/api/chat/sessions/{id}/stream` | 流式对话(SSE:token / tool_call / done / error) |
