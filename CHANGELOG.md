# Changelog

All notable changes to TradingAgents are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
Breaking changes within the 0.x line are called out explicitly.

## [Unreleased]

### Added

- **Tushare Pro 作为中国大陆数据主源,AKShare 兜底。** 新增 `tushare_utils`/`tushare_stock`/
  `tushare_indicator`/`tushare_fundamentals` 四个数据模块,经 `route_to_vendor()` 注册;
  默认价格/技术指标/基本面链改为 `tushare,akshare`(新闻仍 `akshare`),Tushare 成功即停止、
  未配置/限流/无数据时自动回退 AKShare。指标沿用本地 `stockstats` 计算,ETF/基金财报返回
  `not_applicable`,A 股财报按 `curr_date` 过滤防前视。需 `.env` 配置 `TUSHARE_TOKEN`;
  WebUI 服务健康检查新增 Tushare Pro 探针(缺 token 报错、可达报 ok)。
- WebUI 历史记录列表在标的代码下方显示标的可读名称（A 股/ETF 中文名、其余 yfinance 公司全名）。
  名称在分析启动时由 `resolve_instrument_identity` 解析并落库到 `analysis_runs.instrument_name`
  新列（动态迁移，兼容旧库），经 `GET /api/history` 返回；解析不到时留空、前端回退为仅显示代码。
  旧记录可用 `scripts/backfill_instrument_names.py` 回填（先解析已存上下文文本、否则联网兜底）。
- 决策流水线末尾新增报告校验节点：对各报告中的标的名称与可验证市场数字做事实校对、自动修正不一致，并产出 `validation_report` 校验报告。可经 `TRADINGAGENTS_REPORT_VALIDATION_ENABLED` 关闭。
- WebUI 分析配置改用可持久化的代码清单：单代码输入框逐个添加、可增删排序、localStorage
  长期保存（刷新/重开不变，分析后保留），开始分析按清单顺序入队。名称查询
  （`GET /api/ticker/{code}`）A 股/ETF 优先 AKShare 中文名、其余及失败回退 yfinance，
  全程 fail-open；冷缓存导致的空名称会在再次打开页面时自动补查自愈。
- **WebUI 分析队列**：一次输入多个标的代码，持久化为后端队列，由调度器串行依次分析；
  支持移除/清空/重排 pending、取消当前并自动推进、出错跳过；服务重启后 pending 队列保留。
- **WebUI 模型选择.** 分析工作台新增「深度思考模型 / 快速思考模型」两个下拉，Chat
  页新增模型下拉（deep+quick 合并去重）；选项来自当前已配置 provider 的模型目录
  （`GET /api/config/options` 新增 `model_options`），选择记忆于浏览器 localStorage。
  Chat 发消息支持 `chat_llm` 请求字段，在当前 provider 内覆盖对话模型。
- **LLM API architecture reference.** Added a maintainer document covering every
  model-backed execution path across TradingAgents, Advisor Chat, vision extraction,
  report export, startup health checks, Provider authentication, structured-output
  fallback, retries, streaming semantics, and IBM ICA wire details.
- 服务启动时对当前 provider 的候选模型做健康检查，自动为 deep/quick 槽位选用可用模型（原配置优先，全挂不阻断启动）。可用 `TRADINGAGENTS_STARTUP_MODEL_CHECK=0` 关闭。
- **Chat 会话档案 Harness.** 新增可用资金池/风险偏好/单票上限/投资期限等会话参数面板，
  确认后稳定注入每轮推理；新增 `propose_session_facts`（对话抽取→确认卡片）与
  `compute_position_sizing`（强制使用已确认资金池、缺失则返回 `NEED_CONFIRMATION` 反问）工具。
- **Context-aware Chat report export.** The advisor can clarify an ambiguous
  export scope with persisted clickable choices, then save only the session's
  final confirmed conclusions and action items as a dated, collision-safe
  Markdown file under `report/`.
- **Chat multi-report context.** A Chat session can now persist an ordered
  selection of multiple completed analysis reports (normalized into a new
  `chat_session_runs` table, with `chat_sessions.run_id` kept as a legacy
  read fallback). The right-sidebar `RunPicker` became a completed-only
  multi-select, report selections are validated atomically at the API
  boundary, and sessions support inline rename plus bulk delete.
- **AKShare ETF/fund fundamentals.** Mainland China listed fund/ETF symbols
  (e.g. `159241`, `510300.SS`) now return a fund-specific fundamentals snapshot
  (East Money spot quote plus recent NAV history) instead of attempting to fetch
  operating-company financials. The balance sheet, income statement, and
  cash-flow endpoints return a structured `not_applicable` response for these
  products rather than failing.

### Changed

- A 股/ETF 标的名称解析优先级改为 **tushare → AKShare → yfinance**（原 AKShare 优先）。
  tushare 经 `fund_basic`/`stock_basic` 的 `name` 字段取名，复用基本面相同的磁盘缓存
  （`fund_basic_`/`stock_basic_{ts_code}`），常可零额外请求命中；tushare 未配置/限流/超时
  一律 fail-open 自动回退 AKShare，再不行回退 yfinance。与「tushare 为大陆数据主源」一致。
- **IBM ICA now uses Anthropic Messages.** The Claude-only `ibm_ica` provider
  now sends native Anthropic requests to `/ica/v1/messages` with
  `IBM_ICA_API_KEY` as `x-api-key`. Core, CLI, Chat, vision, export, and startup
  health checks share the same `/ica` Base URL, and ICA fallback candidates no
  longer include GPT, Gemini, or Granite models.
- **Liquid-glass WebUI theme.** Refreshed the Next.js frontend (chat, history,
  config, run detail, and shared UI primitives) with a liquid-glass visual
  style and updated global styles.

### Fixed

- **AKShare 连接被远端关闭不再中断整个分析.** `get_verified_market_snapshot`
  工具直连 `build_verified_market_snapshot`，绕过了 `route_to_vendor` 的「永不抛异常」
  保护：东财行情瞬时断连（`RemoteDisconnected`，A 股/ETF 重试 6 次后仍失败）、无数据或
  数据过期时，原始异常会穿过 LangGraph ToolNode 冒泡到 `api/runner.py` 并把整条 run 标记
  为 error 终止。现工具边界统一捕获网络错误 / `NoMarketDataError` / 空数据，返回
  `MARKET_SNAPSHOT_UNAVAILABLE` 哨兵串（提示分析师如实报告数据不可用、不要编造数字），
  与数据层 `DATA_SOURCE_UNAVAILABLE` 契约一致；分析继续而非崩溃。
- **A 股/ETF 分析报告标题不再编造标的名称.** 反幻觉的标的身份注入此前在
  `domestic_china_only`（默认开启）下对 A 股直接返回空身份，分析管线只拿到纯代码、
  没有名称，LLM 便自行虚构（如 `159241` 写成「中证全球半导体ETF」，实为「航空航天ETF天弘」），
  与 WebUI 侧栏的 AKShare 真名对不上、令人怀疑报告真实性。现 `resolve_instrument_identity`
  对 A 股改走与 WebUI 同一套域内名称解析（`resolve_ticker_name`，AKShare 优先、不触碰海外
  yfinance），把真实中文名注入每个 agent 的 prompt；查不到名时仍 fail-open 退回纯代码。
- **WebUI 队列面板与历史侧栏不再卡在旧状态.** 两者此前只靠实时 SSE 流关闭回调推进,
  没有独立轮询:停在某条运行中 run 的历史详情、或刷新过页面时,后台队列已串行推进到
  下一个,但右侧「分析队列」仍显示上一个运行中、左侧历史的 RUNNING/COMPLETED 状态也不更新,
  只能手动刷页面。现新增轮询——只要队列里还有 running/pending(后台仍在推进),就每 5s
  同时刷新队列面板和历史侧栏,瞬时网络错误保留上次结果不闪空;队列跑空后自动停止轮询。
- **WebUI Agent Matrix 不再把风险辩论阶段误标为「组合经理」.** Agent Matrix 之前没有
  风险辩论(激进/保守/中立)这一格,交易员之后直接跳到组合经理。流水线跑到风险辩论时
  (该阶段用 quick 模型),进度兜底逻辑会把第一个未完成的格子=组合经理标成 WORKING,而
  RUNTIME STATUS 的「模型」字段又显示风险辩论在飞的 quick 模型,拼成「组合经理 / quick 模型」
  的假象,看起来像组合经理用错了模型(组合经理实际正确绑定 deep 模型,且此时尚未启动)。
  现新增「风险辩论」行,并用在飞模型是否等于 deep 模型来区分「风险辩论中(quick)」与
  「组合经理裁决中(deep)」,与已有的多空辩论/研究经理判别逻辑同构。
- **LLM 请求不再因网关 hang 住而无限挂死.** `llm_request_timeout` 默认从 `None` 改为
  `300`(秒)。此前注释声称「None 留给各 SDK 自己的默认值」是错的:langchain_anthropic
  把 `default_request_timeout=None` 当成*有意义*的值,会显式把 `timeout=None` 传给自建
  httpx client(= 永不超时),绕过 Anthropic SDK 自带的 600s 默认。当 IBM ICA 等网关
  「接了请求但一直不回包」时,`llm.invoke` 会卡在 socket 读上无限等待;而 `max_retries`
  只在收到错误/超时响应时才重试,没有 timeout 就永远不抛 `APITimeoutError`,于是这一轮
  分析既不报错也不结束(实测卡死 1 小时+)。改为有限默认后,hang 住的请求会超时 → 触发
  现有重试预算 → 网关恢复即成功,全挂则让该轮**报错结束**而非永久挂起。可用
  `TRADINGAGENTS_LLM_REQUEST_TIMEOUT` 覆盖。
- **Agent Matrix 不再把多空辩论误挂在研究经理名下.** 此前矩阵无「研究员」行，多头/空头
  辩论（用 quick 模型）整段被归到「研究经理 WORKING」，导致 RUNTIME STATUS 显示的模型是
  quick 而非研究经理实际使用的 deep 模型，看起来像配置错乱。现矩阵在分析师与研究经理之间
  新增「多空辩论」行；辩论与研究经理判定处于同一报告窗口（分析师已完成、investment_plan
  未出），用 runtime 的当前模型与 run 配置的 `deep_think_llm` 是否一致来区分：deep ⇒
  研究经理判定中，否则 ⇒ 多空辩论中（deep 与 quick 相同时无法区分，停留在辩论行直至出
  investment_plan）。「当前 Agent」标签同步修正。
- **LLM 网关瞬时故障不再崩整轮分析.** Provider 网关(含 IBM ICA / Cloudflare 前端)
  偶发 5xx/429;底层 SDK 虽会对 408/409/429/≥500 做指数退避重试,但默认预算仅 2,
  撑不过数秒级网关抖动,任一节点(如 researcher 的 `llm.invoke`)收到一个 502 就崩掉
  整个多智能体 run。新增跨 provider 的 `llm_max_retries`(默认 6)与
  `llm_request_timeout`,经 `_get_provider_kwargs` 注入所有 provider client,
  由 SDK 退避吸收瞬时故障。可用 `TRADINGAGENTS_LLM_MAX_RETRIES` /
  `TRADINGAGENTS_LLM_REQUEST_TIMEOUT` 覆盖。
- **数据源不可达不再崩整轮分析.** 当配置的 vendor 链仅因网络/连接错误
  (`ConnectionError`/`ProxyError`/`Timeout`/`ChunkedEncodingError`,如 East Money
  对非大陆出口直接关连接的 `RemoteDisconnected`) 全部失败、且无 vendor 报告 clean
  no-data 时,`route_to_vendor` 改为返回 `DATA_SOURCE_UNAVAILABLE` 哨兵而非
  `raise first_error`,兑现 AGENTS.md “永不抛错” 契约——analyst 报告 “数据暂不可用”
  而不是让单个不可达数据源杀死整个多智能体 run。非网络的真错误(坏符号、解析 bug)
  仍照常抛出。
- **Empty provider response retry.** `NormalizedChatOpenAI.invoke` now retries
  once when an OpenAI-compatible gateway returns an empty successful response
  that the SDK parses as `None` (surfacing as
  `'NoneType' object has no attribute 'model_dump'`), instead of failing the run
  on a transient gateway hiccup.
- **Advisor tool execution.** `run_chat` now invokes LangChain structured tools
  via `tool.invoke(args)` instead of `tool(**kwargs)`, matching the
  `StructuredTool` calling convention.

## [0.2.5] — 2026-05-11

### Added

- **Grounded Sentiment Analyst.** The renamed `sentiment_analyst` now reads
  real Yahoo News, StockTwits, and Reddit data before generating its report,
  replacing the prior flow that could fabricate social posts under prompt
  pressure. (#557, #607)
- **MiniMax provider** with the full M2.x catalog (M2.7 / M2.5 / M2.1 / M2
  plus highspeed variants, 204K context). Dual-region: Global
  (`MINIMAX_API_KEY`) and China (`MINIMAX_CN_API_KEY`).
- **Dual-region Qwen and GLM** with separate keys per region — international
  (`DASHSCOPE_API_KEY`, `ZHIPU_API_KEY`) and China (`DASHSCOPE_CN_API_KEY`,
  `ZHIPU_CN_API_KEY`), selectable via a secondary region prompt. (#758)
- **`TRADINGAGENTS_*` env-var configurability for `DEFAULT_CONFIG`.** Override
  `llm_provider`, deep/quick model IDs, `backend_url`, `output_language`,
  debate-round counts, checkpoint flag, and benchmark ticker via `.env` with
  type-aware coercion (string / int / bool). (#602)
- **Interactive API-key detection in the CLI.** When the selected provider's
  key is missing, the CLI prompts for it and persists the value to `.env`
  so the analysis run continues without restart.
- **Remote Ollama support.** `OLLAMA_BASE_URL` points the CLI and the
  programmatic client at a remote `ollama-serve`. The CLI surfaces the
  resolved endpoint and warns on common malformed inputs. Adds a
  `"Custom model ID"` option for models pulled via `ollama pull`. (#648, #768)
- **Configurable news-fetch parameters** in `DEFAULT_CONFIG` — per-ticker
  article limit, macro headline limit, lookback window, and macro search
  queries. (#606, #683)
- **Configurable alpha benchmark** for non-US tickers. Replaces hardcoded
  SPY with regional indices for `.NS` (^NSEI), `.T` (^N225), `.HK` (^HSI),
  `.L` (^FTSE), `.TO` (^GSPTSE), `.AX` (^AXJO), `.BO` (^BSESN); explicit
  `benchmark_ticker` override available. Eliminates FX drift dominating
  alpha for non-USD listings. (#628, #684)
- **Multi-language output covers every user-facing agent** — researchers,
  risk debators, research manager, and trader, ending the previous
  partial-localization reports. (#575)
- **Model catalog refresh.** OpenAI GPT-5.5 frontier, Anthropic Claude Opus
  4.7, Gemini 3.1 Flash-Lite GA, xAI Grok 4.20, Qwen 3.6 line. Versioned IDs
  only; auto-shifting aliases moved to the `"Custom model ID"` option.

### Changed

- **Sentiment Analyst** is now consistently named across the CLI dropdown,
  status panel, and final reports (previously the backend was renamed but
  the CLI still said "Social Analyst"). The `AnalystType.SOCIAL = "social"`
  wire value is kept for saved-config back-compat.

### Fixed

- **Structured output works on DeepSeek V4 / reasoner and MiniMax M2.x.**
  Those providers reject `tool_choice` per their tool-calling docs; the
  binding flow now skips it automatically via a capability table.
- **`pip install .` installations pick up the project `.env`** when running
  the CLI as a console script. (#747)
- **Reports save end-to-end** — streamed chunks were previously dropped from
  `complete_report.md`. (#719, #736)
- **Ticker prompt preserves exchange suffixes** (`.SH`, `.SZ`, `.SS`, `.HK`,
  `.T`, etc.) for A-share, HK, Tokyo, and other non-US flows. (#770)
- **Docker permission errors** no longer block first-run write to
  `~/.tradingagents/`. (#519, #627, #672, #771)
- **Config state no longer leaks between runs** when sub-dicts are mutated;
  `set_config` partial updates preserve sibling defaults. (#788)
- **`max_recur_limit` config actually applies** — previously read but not
  forwarded to the propagator. (#764)
- **Missing-API-key error** names the exact env var to set. (#680)
- **Quieter startup** — suppressed the noisy upstream
  `LangChainPendingDeprecationWarning` from langgraph-checkpoint; will be
  removed once that package ships its fix.

### Security

- **Ticker path-traversal validation** at every filesystem-path site (cache,
  checkpoint database, results) so a malicious ticker cannot escape its
  intended directory. (#618)

## [0.2.4] — 2026-04-25

### Added

- **Structured-output decision agents.** Research Manager, Trader, and Portfolio
  Manager now use `llm.with_structured_output(Schema)` on their primary call
  and return typed Pydantic instances. Each provider's native structured-output
  mode is used (`json_schema` for OpenAI / xAI, `response_schema` for Gemini,
  tool-use for Anthropic, function-calling for OpenAI-compatible providers).
  Render helpers preserve the existing markdown shape so memory log, CLI
  display, and saved reports keep working unchanged. (#434)
- **LangGraph checkpoint resume** — opt-in via `--checkpoint`. State is saved
  after each node so crashed or interrupted runs resume from the last
  successful step. Per-ticker SQLite databases under
  `~/.tradingagents/cache/checkpoints/`. `--clear-checkpoints` resets them. (#594)
- **Persistent decision log** replacing the per-agent BM25 memory. Decisions
  are stored automatically at the end of `propagate()`; the next same-ticker
  run resolves prior pending entries with realised return, alpha vs SPY, and
  a one-paragraph reflection. Override path with `TRADINGAGENTS_MEMORY_LOG_PATH`.
  Optional `memory_log_max_entries` config caps resolved entries; pending
  entries are never pruned. (#578, #563, #564, #579)
- **DeepSeek, Qwen (Alibaba DashScope), GLM (Zhipu), and Azure OpenAI**
  providers, plus dynamic OpenRouter model selection.
- **Docker support** — multi-stage build with separate dev and runtime images.
- **`scripts/smoke_structured_output.py`** — diagnostic that exercises the
  three structured-output agents against any provider so contributors can
  verify their setup with one command.
- **5-tier rating scale** (Buy / Overweight / Hold / Underweight / Sell) used
  consistently by Research Manager, Portfolio Manager, signal processor, and
  the memory log; Trader keeps 3-tier (Buy / Hold / Sell) since transaction
  direction is naturally ternary.
- **Pytest fixtures** — lazy LLM client imports plus placeholder API keys so
  the test suite runs cleanly without credentials. (#588)

### Changed

- **`backend_url` default is now `None`** rather than the OpenAI URL. Each
  provider client falls back to its native default. The previous default
  leaked the OpenAI URL into non-OpenAI clients (e.g. Gemini), producing
  malformed request URLs for Python users who switched providers without
  overriding `backend_url`. The CLI flow is unaffected.
- All file I/O passes explicit `encoding="utf-8"` so Windows users no longer
  hit `UnicodeEncodeError` with the cp1252 default. (#543, #550, #576)
- Cache and log directories moved to `~/.tradingagents/` to resolve Docker
  permission issues. (#519)
- `SignalProcessor` reads the rating from the Portfolio Manager's rendered
  markdown via a deterministic heuristic — no extra LLM call.
- OpenAI structured-output calls default to `method="function_calling"` to
  avoid noisy `PydanticSerializationUnexpectedValue` warnings emitted by
  langchain-openai's Responses-API parse path. Same typed result, no warnings.

### Fixed

- Empty memory no longer triggers fabricated past-lessons in agent prompts;
  the memory-log redesign makes this structurally impossible since only the
  Portfolio Manager consults memory and only when entries exist. (#572)
- Tool-call logging processes every chunk message, not just the last one, and
  memory score normalization handles empty score arrays. (#534, #531)

### Removed

- `FinancialSituationMemory` (the per-agent BM25 system) and the dead
  `reflect_and_remember()` plumbing; subsumed by the persistent decision log.
- Hardcoded Google endpoint that caused 404 when `langchain-google-genai`
  changed its API path. (#493, #496)

### Contributors

Thanks to everyone who shaped this release through code, design, and reports:

- [@claytonbrown](https://github.com/claytonbrown) — checkpoint resume (#594), test fixtures (#588), design feedback on cost tracking (#582) and structured validation (#583)
- [@Bcardo](https://github.com/Bcardo) — memory-log redesign (#579), empty-memory hallucination report (#572), encoding fix proposal (#570)
- [@voidborne-d](https://github.com/voidborne-d) — memory persistence design (#564), portfolio manager state fix (#503)
- [@mannubaveja007](https://github.com/mannubaveja007) — structured-output feature request (#434)
- [@kelder66](https://github.com/kelder66) — RAM-only memory issue (#563)
- [@Gujiassh](https://github.com/Gujiassh) — tool-call logging fix (#534), test stub PR (#533)
- [@iuyup](https://github.com/iuyup) — memory score normalization fix (#531)
- [@kaihg](https://github.com/kaihg) — Google base_url fix (#496)
- [@32ryh98yfe](https://github.com/32ryh98yfe) — Gemini 404 report (#493)
- [@uppb](https://github.com/uppb) — OpenRouter dynamic model selection (#482)
- [@guoz14](https://github.com/guoz14) — OpenRouter limited-model report (#337)
- [@samchenku](https://github.com/samchenku) — indicator name normalization (#490)
- [@JasonOA888](https://github.com/JasonOA888) — y_finance pandas import fix (#488)
- [@tiffanychum](https://github.com/tiffanychum) — stale import cleanup (#499)
- [@zaizou](https://github.com/zaizou) — Docker permission issue (#519)
- [@Stosman123](https://github.com/Stosman123), [@mauropuga](https://github.com/mauropuga), [@hotwind2015](https://github.com/hotwind2015) — Windows encoding bug reports (#543, #550, #576)
- [@nnishad](https://github.com/nnishad), [@atharvajoshi01](https://github.com/atharvajoshi01) — encoding fix proposals (#568, #549)

## [0.2.3] — 2026-03-29

### Added

- **Multi-language output** for analyst reports and final decisions, with a
  CLI selector. Internal agent debate stays in English for reasoning quality. (#472)
- **GPT-5.4 family models** in the default catalog, with deep/quick model split.
- **Unified model catalog** as a single source of truth for CLI options and
  provider validation.

### Changed

- `base_url` is forwarded to Google and Anthropic clients so corporate proxies
  work consistently across providers. (#427)
- Standardised the Google `api_key` parameter to the unified `api_key` form.

### Fixed

- Backtesting fetchers no longer leak look-ahead data when `curr_date` is in
  the middle of a fetched window. (#475)
- Invalid indicator names from the LLM are caught at the tool boundary instead
  of crashing the run. (#429)
- yfinance news fetchers respect the same exponential-backoff retry as price
  fetchers. (#445)

### Contributors

- [@ahmedk20](https://github.com/ahmedk20) — multi-language output (#472)
- [@CadeYu](https://github.com/CadeYu) — model catalog typing (#464)
- [@javierdejesusda](https://github.com/javierdejesusda) — unified Google API key parameter (#453)
- [@voidborne-d](https://github.com/voidborne-d) — yfinance news retry (#445)
- [@kostakost2](https://github.com/kostakost2) — look-ahead bias report (#475)
- [@lu-zhengda](https://github.com/lu-zhengda) — proxy/base_url support request (#427)
- [@VamsiKrishna2021](https://github.com/VamsiKrishna2021) — invalid indicator crash report (#429)

## [0.2.2] — 2026-03-22

### Added

- **Five-tier rating scale** (Buy / Overweight / Hold / Underweight / Sell)
  introduced for the Portfolio Manager.
- **Anthropic effort level** support for Claude models.
- **OpenAI Responses API** path for native OpenAI models.

### Changed

- `risk_manager` renamed to `portfolio_manager` to match the role description
  shown in the CLI display.
- Exchange-qualified tickers (e.g. `7203.T`, `BRK.B`) preserved across all
  agent prompts and tool calls.
- Process-level UTF-8 default attempted for cross-platform consistency
  (note: this approach did not actually take effect; replaced in v0.2.4 with
  explicit per-call `encoding="utf-8"` arguments).

### Fixed

- yfinance rate-limit errors are retried with exponential backoff. (#426)
- HTTP client SSL customisation is supported for environments that need
  custom certificate bundles. (#379)
- Report-section writes handle list-of-string content gracefully.

### Contributors

- [@CadeYu](https://github.com/CadeYu) — exchange-qualified ticker preservation (#413)
- [@yang1002378395-cmyk](https://github.com/yang1002378395-cmyk) — HTTP client SSL customisation (#379)

## [0.2.1] — 2026-03-15

### Security

- Patched `langchain-core` vulnerability (LangGrinch). (#335)
- Removed `chainlit` dependency affected by CVE-2026-22218.

### Added

- `pyproject.toml` build-system configuration; the project now installs via
  modern packaging tooling.

### Removed

- `setup.py` — dependencies consolidated to `pyproject.toml`.

### Fixed

- Risk manager reads the correct fundamental report source. (#341)
- All `open()` calls receive an explicit UTF-8 encoding (initial pass).
- `get_indicators` tool handles comma-separated indicator names from the LLM. (#368)
- `Propagation` initialises every debate-state field so risk debaters never
  see missing keys.
- Stock data parsing tolerates malformed CSVs and NaN values.
- Conditional debate logic respects the configured round count. (#361)

### Contributors

- [@RinZ27](https://github.com/RinZ27) — `langchain-core` security patch (#335)
- [@Ljx-007](https://github.com/Ljx-007) — risk manager fundamental-report fix (#341)
- [@makk9](https://github.com/makk9) — debate-rounds config issue (#361)

## [0.2.0] — 2026-02-04

This is the largest release since the initial public version. The framework
moved from single-provider to a multi-provider architecture and grew several
production-ready surfaces.

### Added

- **Multi-provider LLM support** (OpenAI, Google, Anthropic, xAI, OpenRouter,
  Ollama) via a factory pattern, with provider-specific thinking configurations.
- **Alpha Vantage** integration as a configurable primary data provider, with
  yfinance as a community-stability fallback.
- **Footer statistics** in the CLI: real-time tracking of LLM calls, tool
  calls, and token usage via LangChain callbacks.
- **Post-analysis report saving** — the framework writes per-section markdown
  files (analyst reports, debate transcripts, final decision) when a run
  completes.
- **Announcements panel** — fetches updates from `api.tauric.ai/v1/announcements`
  for the CLI welcome screen.
- **Tool fallbacks** so a single vendor outage does not stop the pipeline.

### Changed

- Risky / Safe risk debaters renamed to **Aggressive / Conservative** for
  consistency with the displayed agent labels.
- Default data vendor switched to balance reliability and quota across
  community deployments.
- Ollama and OpenRouter model lists updated; default endpoints clarified.

### Fixed

- Analyst status tracking and message deduplication in the live display.
- Infinite-loop guard in the agent loop; reflection and logging hardened.
- Various data-vendor implementation bugs and tool-signature mismatches.

### Contributors

This release is the first with substantial outside contributions; many community
PRs from late 2025 also landed here.

- [@luohy15](https://github.com/luohy15) — Alpha Vantage data-vendor integration (#235)
- [@EdwardoSunny](https://github.com/EdwardoSunny) — yfinance fetching optimisations (#245)
- [@Mirza-Samad-Ahmed-Baig](https://github.com/Mirza-Samad-Ahmed-Baig) — infinite-loop guard, reflection, and logging fixes (#89)
- [@ZeroAct](https://github.com/ZeroAct) — saved results path support (#29)
- [@Zhongyi-Lu](https://github.com/Zhongyi-Lu) — `.env` gitignore (#49)
- [@csoboy](https://github.com/csoboy) — local Ollama setup (#53)
- [@chauhang](https://github.com/chauhang) — initial Docker support attempt (#47, later reverted; the merged Docker support shipped in v0.2.4)

## [0.1.1] — 2025-06-07

### Removed

- Static site assets that had been bundled with v0.1.0; the public site now
  lives separately.

## [0.1.0] — 2025-06-05

### Added

- **Initial public release** of the TradingAgents multi-agent trading
  framework: market / sentiment / news / fundamentals analysts; bull and bear
  researchers; trader; aggressive, conservative, and neutral risk debaters;
  portfolio manager. LangGraph orchestration, yfinance data, per-agent
  BM25 memory, single-provider OpenAI integration, interactive CLI.

[0.2.4]: https://github.com/TauricResearch/TradingAgents/compare/v0.2.3...v0.2.4
[0.2.3]: https://github.com/TauricResearch/TradingAgents/compare/v0.2.2...v0.2.3
[0.2.2]: https://github.com/TauricResearch/TradingAgents/compare/v0.2.1...v0.2.2
[0.2.1]: https://github.com/TauricResearch/TradingAgents/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/TauricResearch/TradingAgents/compare/v0.1.1...v0.2.0
[0.1.1]: https://github.com/TauricResearch/TradingAgents/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/TauricResearch/TradingAgents/releases/tag/v0.1.0
