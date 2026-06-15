# TradingAgents WebUI (对话式分析助手) — 设计文档

- **日期**: 2026-06-15
- **状态**: 已批准,待编写实现计划
- **作者**: 头脑风暴产出 (Sisyphus + 用户)

## 1. 目标与范围

为现有的 TradingAgents 多智能体金融分析框架增加一个 Web 界面,以"对话式分析助手"的形态把现有 CLI 体验搬到网页上。技术栈:**FastAPI(后端)+ Next.js(前端)**。

### 已确认的范围决策

| 维度 | 决策 |
|---|---|
| 定位 | 对话式分析向导(把 CLI 体验搬到聊天网页),非自由问答机器人 |
| 使用场景 | 单用户本地工具,一次跑一个分析 |
| 持久化 | 轻量持久化 + 历史列表(SQLite) |
| 视觉风格 | 专业金融终端风(深色背景、等宽字体、数据密集、涨跌色) |
| 后端通信 | FastAPI + SSE 流式 + 后台线程 |
| 配置交互 | 一张卡片集中配置 + 一键开始(非逐条对话提问) |

### 非目标 (YAGNI)

- 多用户、登录认证、并发任务队列(单用户场景不需要)
- WebSocket 双向通道(只需服务器单向推送,SSE 足够)
- 自然语言意图解析(用户直接填 ticker,不需要 LLM 解析"帮我看看英伟达")
- 修改 `tradingagents/` 核心或 `cli/` 现有代码(完全不动,只新增 `api/` 和 `webui/`)

## 2. 现有系统约束(探索结论)

- 核心入口:`TradingAgentsGraph(selected_analysts, debug, config, callbacks)`,主方法 `propagate(company_name, trade_date, asset_type) -> (final_state, decision)`。
- `decision` 是单个字符串:`Buy | Overweight | Hold | Underweight | Sell`。
- `final_state` 是一个 dict,含全部报告板块:`market_report`、`sentiment_report`、`news_report`、`fundamentals_report`、`investment_debate_state`、`investment_plan`、`trader_investment_plan`、`risk_debate_state`、`final_trade_decision`。
- `propagate()` 是**同步阻塞**(30 秒到数分钟),且**非线程安全**(`ta.ticker`/`ta.curr_state` 每次调用被改写)——单用户单实例 + 一次一个分析的约束下可接受。
- `graph.graph.stream(init_state)` 按 LangGraph 节点逐块 yield 输出——这是流式推送的天然挂载点。
- 配置:`DEFAULT_CONFIG.copy()` 后 merge 覆盖,其余由 `.env` 的 `TRADINGAGENTS_*` 环境变量驱动(`tradingagents/__init__.py` 在导入时 `load_dotenv`)。
- 进度统计:CLI 用 `StatsCallbackHandler`(LangChain callback)统计 LLM/工具调用与 token,可在服务端复用。
- 项目无任何现有 Web/服务端代码,是干净起点。Python 3.12,已有依赖含 `langgraph`、`redis`、`python-dotenv`。
- 框架自带副作用:每次 run 自动写决策日志到 `~/.tradingagents/memory/`,写完整状态 JSON 到 `~/.tradingagents/logs/`。WebUI 的 SQLite 独立于此,放 `~/.tradingagents/webui.db`。

## 3. 整体架构

### 目录结构

```
TradingAgents/
├── tradingagents/          # 现有核心,完全不动
├── cli/                    # 现有 CLI,完全不动
├── api/                    # 新增:FastAPI 后端
│   ├── main.py             # 应用入口、CORS、路由挂载、单例 graph 生命周期
│   ├── routes/
│   │   ├── analysis.py     # POST 启动分析 + GET SSE 流式订阅 + 下载报告
│   │   ├── history.py      # 历史列表 / 单条详情 / 删除
│   │   └── config.py       # 返回可选的分析师/模型/语言选项
│   ├── runner.py           # 包装 graph.stream(),后台线程跑,事件入线程安全队列
│   ├── store.py            # SQLite 历史读写
│   └── schemas.py          # Pydantic 请求/响应/事件模型
└── webui/                  # 新增:Next.js 前端 (App Router)
    ├── app/
    ├── components/         # 聊天气泡、智能体卡片、配置卡片、进度条、结论卡、历史侧栏
    └── lib/                # SSE 客户端、API 封装、TypeScript 类型
```

### 数据流

```
用户在配置卡片填完并点「开始分析」
  → POST /api/analysis  → 后端插入 SQLite(status=running),启动后台线程跑 graph.stream(),返回 run_id
  → 前端用 run_id 打开 SSE: GET /api/analysis/{run_id}/stream
  → 后台线程每个 chunk 解析为事件 put 进线程安全队列;SSE async 侧从队列 get 并 yield:
      agent_status   → 顶部进度条
      message        → 逐条助手聊天气泡
      report_section → 可折叠报告气泡
      stats          → 底部统计行
      done           → 结论卡 + 落库(update status=completed, decision, result_json)
  → 完成的分析出现在左侧历史侧栏
```

**桥接机制**:后台线程跑阻塞的 `graph.graph.stream()`,逐块解析后把事件 `put` 进 `queue.Queue`(线程安全);SSE 端点的 `async` 生成器从该队列 `get` 并 yield。阻塞调用因此不会占用 FastAPI 事件循环。

## 4. 前端交互设计

### 布局

- **左侧常驻历史侧栏**:列出过往分析(`NVDA · 2024-05-10 · BUY`,带涨跌色标),点击重新加载查看,支持删除。类似 ChatGPT 左栏。
- **主区域聊天流**:自上而下的对话式界面。
- **视觉**:专业金融终端风——深色背景、等宽字体、数据密集、Buy 绿 / Sell 红 / Hold 中性色。前端用 shadcn/ui + Tailwind,在其上施加金融终端主题。

### 交互流程

1. **欢迎气泡**(助手):提示用户输入要分析的股票。
2. **股票 + 日期输入**:一个 ticker 输入框(支持 `NVDA`/`0700.HK`/`BTC-USD`)+ 日期选择器(默认今天),作为一条用户气泡发出。
3. **配置卡片**(助手气泡内嵌一张可交互卡片,集中配置,带合理默认值):
   - 分析师团队:4 个 pill 多选(市场/情绪/新闻/基本面),默认全选;`asset_type=crypto` 时基本面自动禁用。至少选 1 个。
   - 研究深度:3 选 1(浅 1 轮 / 中 3 轮 / 深 5 轮),默认「中」。
   - LLM 提供商 + 模型:两个下拉,默认读后端 `.env` 已配置的值;**若 `.env` 已配好,这部分默认折叠/隐藏**,不打扰用户。
   - 输出语言:下拉,默认中文。
   - 醒目的「🚀 开始分析」按钮。
4. **运行中**:
   - 顶部智能体进度行:Analyst Team(市场/情绪/新闻/基本面)→ Research Team(看涨/看跌/研究经理)→ Trading Team(交易员)→ Risk Management(激进/保守/中立)→ Portfolio Management(组合经理)。每个智能体状态:pending → working(动画)→ done/error。
   - 每个智能体产出作为一条助手聊天气泡逐条冒出(带智能体名/头像);长报告气泡可折叠。
   - 底部轻量 stats 行:LLM 调用数 / 工具调用数 / token 进出 / 已用时。
5. **完成**:
   - 结论卡:大字 `BUY/HOLD/SELL`(涨跌色)+ 执行摘要 + 价格目标 + 时间范围(来自 `final_trade_decision`)。
   - 「下载完整报告(Markdown)」按钮。
   - 自动出现在左侧历史侧栏。

## 5. 后端 API 契约

### 5.1 REST 接口

| 方法 | 路径 | 作用 |
|---|---|---|
| `GET` | `/api/config/options` | 返回配置卡片选项(可选分析师、研究深度档位、语言列表、`.env` 已配置的 provider/模型) |
| `POST` | `/api/analysis` | 启动一次分析,返回 `{ run_id }`,后台线程立即开跑 |
| `GET` | `/api/analysis/{run_id}/stream` | SSE 端点,订阅该 run 实时事件流 |
| `GET` | `/api/analysis/{run_id}/report` | 下载完整 Markdown 报告 |
| `GET` | `/api/history` | 历史列表(摘要:run_id、ticker、trade_date、decision、status、created_at) |
| `GET` | `/api/history/{run_id}` | 单条完整结果(全部报告板块) |
| `DELETE` | `/api/history/{run_id}` | 删除一条历史 |

### 5.2 POST /api/analysis 请求体

```jsonc
{
  "ticker": "NVDA",
  "trade_date": "2024-05-10",
  "asset_type": "stock",                  // stock | crypto
  "analysts": ["market","social","news","fundamentals"],
  "research_depth": 3,                     // 1 | 3 | 5 → 映射 max_debate_rounds / max_risk_discuss_rounds
  "output_language": "Chinese",
  "llm_provider": null,                    // null = 用后端 .env 默认
  "deep_think_llm": null,
  "quick_think_llm": null
}
```

后端把非 null 字段 merge 进 `DEFAULT_CONFIG.copy()`,其余沿用 `.env` 的 `TRADINGAGENTS_*`。

> 注:`analysts` 数组用框架内部名 `"social"` 表示情绪分析师(对应 `final_state["sentiment_report"]`),与 `TradingAgentsGraph` 的 `selected_analysts` 入参一致。

### 5.3 SSE 事件协议

每条 SSE 消息形如 `event: <type>\ndata: <json>\n\n`。

```jsonc
// 1. 智能体状态变化 → 顶部进度条
event: agent_status
data: { "agent": "market_analyst", "team": "analyst", "status": "working" }
// status: pending | working | done | error

// 2. 智能体输出一段文字 → 一条助手聊天气泡
event: message
data: { "agent": "bull_researcher", "team": "research", "content": "...markdown...", "ts": 1715000000 }

// 3. 完整报告板块就绪 → 可折叠报告气泡 / 历史详情
event: report_section
data: { "section": "market_report", "content": "...markdown..." }
// section 取值为 final_state 中的报告字段名(见第 2 节)

// 4. 实时统计 → 底部 stats 行(复用 StatsCallbackHandler)
event: stats
data: { "llm_calls": 12, "tool_calls": 5, "tokens_in": 8400, "tokens_out": 3200, "elapsed_sec": 47 }

// 5. 结束 → 结论卡 + 落库
event: done
data: { "decision": "Buy", "final_trade_decision": "...markdown...", "run_id": "..." }

// 异常
event: error
data: { "message": "..." }
```

## 6. 数据模型 (SQLite)

DB 文件:`~/.tradingagents/webui.db`(与框架现有 `~/.tradingagents/` 目录一致)。单表:

```sql
CREATE TABLE analysis_runs (
    run_id        TEXT PRIMARY KEY,        -- uuid
    ticker        TEXT NOT NULL,
    trade_date    TEXT NOT NULL,
    asset_type    TEXT NOT NULL,
    decision      TEXT,                    -- 跑完才写:Buy/Overweight/Hold/Underweight/Sell
    status        TEXT NOT NULL,           -- running | completed | error
    config_json   TEXT NOT NULL,           -- 这次用的配置快照
    result_json   TEXT,                    -- 完整 final_state(所有报告板块)
    created_at    TEXT NOT NULL,
    completed_at  TEXT
);
```

生命周期:启动分析插入一行(status=running)→ 跑完 update(decision、result_json、completed_at、status=completed)→ 异常时 status=error。历史列表查摘要字段;详情查 `result_json`。

## 7. 错误处理

- LLM/数据源异常 → 后台线程捕获 → 发 `error` SSE 事件 + DB `status=error`;前端在结论位置显示错误卡 + 重试按钮。
- SSE 连接断开 → 前端可凭 `run_id` 重连;若 run 已完成,改用 `GET /api/history/{run_id}` 拉取完整结果。
- 单用户单实例约束:同一时刻只允许一个 running 任务;若已有 running,POST 返回 409 提示当前有分析在跑(单用户场景下足够,不引入队列)。

## 8. 测试策略

- **后端**:
  - `runner` 用 mock 的 fake graph(yield 预设假 chunk)做单测,不真调 LLM,验证 chunk → SSE 事件的映射正确。
  - REST + SQLite 用 FastAPI `TestClient` 测试启动/历史/删除/下载全流程。
  - 线程队列桥接的并发正确性单测(put/get 顺序、结束信号)。
- **前端**:
  - SSE 客户端解析逻辑单测(各事件类型 → 状态更新)。
  - 关键组件渲染测试:配置卡片、进度条、结论卡、历史侧栏。

## 9. 部署

- 新增 `Dockerfile.api`(或 `docker-compose.yml` 增加一个 service)运行 `uvicorn api.main:app --port 8000` 并暴露端口。现有 CLI Dockerfile 不动。
- 前端 Next.js 独立构建/运行,通过环境变量配置后端地址;开发期 FastAPI 开启 CORS 允许前端来源。
