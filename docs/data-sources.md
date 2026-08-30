# 数据源全集

本文是 **vendor 视角**的数据源清单:每个数据源的真实上游是谁、覆盖哪些方法、要什么
凭证、花不花钱、默认开不开。

方法视角(每个 `get_*` 方法传什么、返回什么)见
[data-fetching-apis.md](./data-fetching-apis.md)。两篇互为索引,不重复内容。

---

## 1. 总览

数据源分两类,区别在于**走不走 `route_to_vendor`**:

```
① 路由层内 —— 10 个 vendor,登记在 interface.py::VENDOR_METHODS
   Agent → @tool → route_to_vendor(method) → vendor 链 → 首个成功即停
   永不抛错,失败返回 NO_DATA_AVAILABLE / DATA_SOURCE_UNAVAILABLE 哨兵

② 路由层外 —— 4 处直连,不经 route_to_vendor
   反幻觉身份解析、reflection 收益回算、stockstats OHLCV、情绪分析师社交源
   AGENTS.md 的「不要在 agent 代码里直连数据源」对这几处是**已知例外**
```

**每个 vendor 到底能不能用、多快、返回多少数据**,见第 4 节的全量实测矩阵
(54 个路由组合 + 7 项路由外,逐格真实调用)。

### 全源 × 全能力总表

一张表看完 **15 个源**(10 个路由内 vendor + 2 处路由外社交源 + 腾讯/新浪/东财三家未接入源)
在 10 类能力上的实测结果。**这是全文的索引**:耗时、体积、失败根因等细节在第 4 节(现有源)
和第 8 节(三家横评)。

图例:✅ 有数据 · ⚪ 调用成功但内容为空 · ⛔ 未配置(缺 key/CLI/占位) ·
🚫 本次网络层失败 · ⚠️ 静默降级 · ❌ 接口存在但无此字段 ·
❓ 未找到公开接口 · ➖ 该源不覆盖此能力 · `未测` 本次未探测

| 数据源 | 行情 | 指标 | 估值快照 | 财务指标 | 三表 | 个股新闻 | 全局快讯 | ETF 画像 | ETF 分钟 | 独有能力 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| **`amazingdata`** 银河/QMT | ✅ | ✅ | ➖ | ✅ | ✅ | ➖ | ➖ | ➖ | ✅ | **龙虎榜/两融/股东/盈利预测**(唯一源) |
| **`tushare`** Tushare Pro | ✅ | ✅ | ➖ | ✅ | ✅ | ⚪ 无命中 | ✅ | ✅ | ✅ | ETF 新闻(⚪) |
| **`akshare`** 东财+新浪 | 🚫 push2 抖动 | 🚫 | ➖ | ✅ | ✅ 103 期 | ✅ | ➖ | ✅ 19s | ➖ | — |
| **`eastmoney`** 东财搜索 | ➖ | ➖ | ➖ | ➖ | ➖ | ✅ | ➖ | ➖ | ➖ | — |
| **`longbridge`** 长桥 | ➖ | ➖ | ➖ | ➖ | ➖ | ⛔ CLI 缺 | ➖ | ⚠️ 误报 | ➖ | — |
| **`tdx`** 通达信 | ➖ | ➖ | ➖ | ➖ | ➖ | ➖ | ➖ | ⛔ 占位 | ➖ | — |
| **`yfinance`** Yahoo | 🚫 | 🚫 | ➖ | 🚫 | 🚫 | 🚫 | 🚫 | ➖ | ➖ | 内部交易(🚫) |
| **`alpha_vantage`** | ⛔ | ⛔ | ➖ | ⛔ | ⛔ | ⛔ | ⛔ | ➖ | ➖ | 内部交易(⛔) |
| **`fred`** 美联储 | ➖ | ➖ | ➖ | ➖ | ➖ | ➖ | ➖ | ➖ | ➖ | 宏观指标(⛔ 且默认禁用) |
| **`polymarket`** | ➖ | ➖ | ➖ | ➖ | ➖ | ➖ | ➖ | ➖ | ➖ | 预测市场(🚫 且默认禁用) |
| *StockTwits*(路由外) | ➖ | ➖ | ➖ | ➖ | ➖ | ➖ | ➖ | ➖ | ➖ | 社交情绪(⚠️ 403) |
| *Reddit*(路由外) | ➖ | ➖ | ➖ | ➖ | ➖ | ➖ | ➖ | ➖ | ➖ | 社交情绪(🚫 超时) |
| **腾讯**(未接入) | ✅ K 线+快照 | ➖ 须自算 | ✅ **88 字段最全** | ❓ | ❓ | ❓ | ❓ | ✅ | 未测 | — |
| **新浪**(未接入) | ✅ 快照 | ➖ 须自算 | ❌ **34 字段无估值** | ✅ HTML | ✅ **1 次拿全** | ✅ **含当天** | ✅ | ✅ | 未测 | — |
| **东财**(直连,超出现接入面) | 🚫 push2 抖动 | ➖ 须自算 | ✅ | ✅ JSON | ✅ **字段最深** | ✅ 排序有问题 | ✅ | ✅ | 未测 | — |

读这张表要注意 5 点,否则会误读:

1. **一格 🚫 不代表方法不可用**。每格是「该 vendor 自己」的能力(直接调 vendor 函数、绕过
   `route_to_vendor`),而实际调用走 fallback 链 —— 链上任一格 ✅ 就够用。例:`get_stock_data`
   的默认链 `amazingdata,tushare,akshare` 里 AKShare 挂了,但前两档撑住了。
2. **🚫 全部是本次网络环境**,不是数据源的永久属性。yfinance / Reddit / Polymarket 三个境外域
   本机裸 curl 全部 connect timeout;AKShare 那两格是东财 `push2` 行情域间歇 reset(第 4 节末)。
3. **「估值快照」这一列现有 vendor 全是 ➖ —— 这是一个真实缺口**。项目没有独立的
   PE/PB/市值快照方法,只有 `get_fundamentals`(LLM 可读的整段文本)。腾讯一个请求给 88 字段,
   是这次横评里最直接可用的补位点。
4. **「东财」在表里出现 3 次,不是重复**:`akshare` 行(经 AKShare 用到 9 个 `_em` 接口)、
   `eastmoney` 行(只覆盖 `get_news`)、以及最后一行**东财直连**(第 8 节实测的完整东财能力面,
   其中财务指标 JSON、全局快讯等**项目当前没有接**)。同理 `akshare` 的财务指标那格底层其实是
   **新浪**,所以「新浪」也已经被间接用上了。上游集中度详见第 5 节。
5. **➖「须自算」**:三家都不提供算好的技术指标。项目的 `get_indicators` 是本地 stockstats
   基于 OHLCV 计算,换源只影响 OHLCV 底座,不影响指标能力。

---

## 2. 路由层内:10 个 vendor

「真实上游」是**实际提供数据的机构**,不是 Python 包名。这一列是本表最重要的信息:
多个 vendor 可能共享同一上游,链式 fallback 因此可能不提供真正的冗余(见第 5 节)。

| vendor | 真实上游 | 覆盖方法 | 凭证 | 费用 | 默认 |
| --- | --- | --- | --- | --- | --- |
| `amazingdata` | **银河证券**(经本地 QMT docker 常驻服务 `127.0.0.1:8888`) | 行情/指标/基本面/ETF 分钟/资金面全部 4 个方法 | `AD_API_TOKEN`(+`AD_API_PORT`/`AD_API_BASE`) | 需银河账户与 QMT;服务本身无 API 费 | ✅ 多数类别链首 |
| `tushare` | **Tushare Pro**;快讯 `news()` 底层为**新浪 + 华尔街见闻** | 行情/指标/基本面/新闻/全球新闻/ETF 画像/ETF 分钟/ETF 新闻 | `TUSHARE_TOKEN` | 注册免费,**ETF/新闻等端点需付费积分** | ✅ |
| `akshare` | **东方财富**(9 个 `_em` 接口)+ **新浪**(1 个财务指标接口) | 行情/指标/基本面/新闻/ETF 画像 | 无 | 免费,无 SLA | ✅ A 股自动路由链首 |
| `eastmoney` | **东方财富** 搜索 API(`search-api-web.eastmoney.com`)直连 | `get_news` | 无 | 免费,无 SLA | ✅ 在 `get_news` 链尾 |
| `longbridge` | **长桥 OpenAPI**(经 `longbridge` CLI subprocess) | `get_news`、ETF 画像 | CLI 自身认证 | 需长桥账户 | ✅ 在链尾 |
| `tdx` | 通达信「问小达」 | ETF 画像 | 无(见下) | 无 | ⚠️ **纯占位** |
| `yfinance` | **Yahoo Finance** | 行情/指标/基本面/新闻/全球新闻/内部交易 | 无 | 免费,无 SLA | ❌ 需显式启用 |
| `alpha_vantage` | **Alpha Vantage**(`alphavantage.co`) | 行情/指标/基本面/新闻/全球新闻/内部交易 | `ALPHA_VANTAGE_API_KEY` | 免费层有每日配额,超出需订阅 | ❌ 需显式启用 |
| `fred` | **美联储圣路易斯分行**(`api.stlouisfed.org`) | `get_macro_indicators` | `FRED_API_KEY` | 免费 | ❌ `disabled` |
| `polymarket` | **Polymarket** Gamma API | `get_prediction_markets` | 无 | 免费 | ❌ `disabled` |

### `tdx` 是占位,不是可用 vendor

[tdx.py](../tradingagents/dataflows/tdx.py) 的 `get_etf_profile` **无条件抛**
`VendorNotConfiguredError`。通达信在本工作区只经 MCP 暴露,没有运行时 Python 依赖。
它登记在路由表里的唯一作用是:让生产配置能写 `tdx` 这一档而不崩,路由会干净跳过。

所以 `get_etf_profile` 的默认链 `akshare,tushare,tdx,longbridge` **有效档位只有 3 个**。
[data-fetching-apis.md](./data-fetching-apis.md) 第 8 节的字段级偏好表里把通达信 MCP
列为多个字段的首选,那是**在 Codex 会话里经 MCP 手工查询**的结论,代码路径拿不到。

---

## 3. 路由层外:4 处直连

这几处不走 `route_to_vendor`,因此**没有 fallback、没有哨兵字符串**,失败方式与路由层不同。
但前三处各自都有配置前置分支,默认配置下**并不真的出境**:

| 位置 | 默认配置下实际走哪条路 | 用途 | 为什么在路由外 |
| --- | --- | --- | --- |
| [agent_utils.py:160](../tradingagents/agents/utils/agent_utils.py#L160) `resolve_instrument_identity` | A 股 → **AKShare**(`ticker_name.resolve_ticker_name`);非 A 股且 `domestic_china_only=True` → 直接返回 `{}`;其余才走 yfinance `Ticker().info` | **反幻觉**:标的身份解析一次,注入每个分析师 prompt | 身份必须单源确定,链式 fallback 会让不同 vendor 给出不同名称 |
| [trading_graph.py:298](../tradingagents/graph/trading_graph.py#L298) `_resolve_outcome` | `domestic_china_only=True` → **整段跳过**(log 一行 Skipping),不调 yfinance | **reflection**:回算已实现收益 + benchmark 对比(算 alpha) | 学习层,不是 agent 工具调用 |
| [stockstats_utils.py:154](../tradingagents/dataflows/stockstats_utils.py#L154) `load_ohlcv` | A 股且 `akshare_auto_route=True` → 复用 **`akshare_stock._fetch_hist`**;其余走 yfinance `download()` + 5 年 CSV 缓存 | stockstats 指标计算的 OHLCV 底座 | vendor 内部实现细节 |
| [sentiment_analyst.py:81-82](../tradingagents/agents/analysts/sentiment_analyst.py#L81) | **无分支,无条件出境**:StockTwits `api.stocktwits.com`、Reddit `search.json` + RSS 回退 | 情绪分析师的社交面输入 | 只服务单个 analyst,没登记成 `TOOLS_CATEGORIES` 方法 |

Reddit/StockTwits 都不需要 key(Reddit 有可选 OAuth,失败降级到 RSS),两者都自带
`tradingagents/0.2 (+github…)` 这样的具名 UA —— Reddit 会拦裸 `Mozilla/5.0` 和 `curl/…`。

**一个容易搞错的点**:前三处虽然代码里写着 yfinance,但在默认配置
(`domestic_china_only=True`、`akshare_auto_route=True`)下,A 股**一次都不会触达 Yahoo** ——
身份走 AKShare、OHLCV 走 AKShare、reflection 整段跳过。默认配置下唯一无条件出境的是
情绪分析师那两个社交源,而第 4 节实测显示两者当前都拿不到数据。

---

## 4. 实测能力矩阵

2026-08-29 22:19–22:35 对 `VENDOR_METHODS` 的**全部 54 个 (方法, vendor) 组合**加上第 3 节
的 7 项路由外直连做了真实调用。

**测法与三条限定**(读表前必须知道,否则会误读):

1. **直接调用 vendor 实现函数,绕过 `route_to_vendor`**。所以每格反映的是**该 vendor 自己**
   的能力,不是默认配置下的可达性 —— 链上任一格 ✅ 就够用,一格 🚫 不代表方法不可用。
2. **反映当次网络环境**,不是数据源的永久属性。本机到境外的 `query1.finance.yahoo.com`、
   `www.reddit.com`、`gamma-api.polymarket.com` 三个域**裸 curl 全部 connect timeout**,
   所以 yfinance / Reddit / Polymarket 的失败是网络不通,与数据源本身能力无关。
3. **标的**:A 股方法用 `600519`(贵州茅台),ETF 方法用 `510300`(沪深300ETF),
   境外 vendor 用 `AAPL`;区间 2026-08-01 → 2026-08-28,`curr_date=2026-08-29`。

图例:✅ 有数据 · ⚪ 调用成功但内容为空 · ⛔ 未配置(缺 key/CLI/占位) ·
🚫 网络层失败 · ⚠️ 静默降级(返回占位串,不报错也无数据)

### 行情与技术指标

| 方法 | `amazingdata` | `tushare` | `akshare` | `yfinance` | `alpha_vantage` |
| --- | --- | --- | --- | --- | --- |
| `get_stock_data` | ✅ 2.1s · 2.3KB | ✅ 0.13s · 1.4KB | 🚫 32.3s(6 次重试耗尽) | 🚫 限频 19.5s | ⛔ 无 key |
| `get_indicators` | ✅ 2.8s · 480B | ✅ 0.17s · 481B | 🚫 熔断快速失败 | 🚫 返回 0 行 | ⛔ 无 key |

### 基本面与三张报表

| 方法 | `amazingdata` | `tushare` | `akshare` | `yfinance` | `alpha_vantage` |
| --- | --- | --- | --- | --- | --- |
| `get_fundamentals` | ✅ 4.3s · 2.2KB | ✅ 0.30s · 9.0KB | ✅ 0.46s · 6.1KB | 🚫 | ⛔ |
| `get_balance_sheet` | ✅ 2.4KB | ✅ 0.15s · 76KB | ✅ 8.1s · 123KB(103 期) | 🚫 | ⛔ |
| `get_cashflow` | ✅ 1.6KB | ✅ 0.12s · 60KB | ✅ 6.9s · 110KB(99 期) | 🚫 | ⛔ |
| `get_income_statement` | ✅ 2.0KB | ✅ 0.22s · 52KB | ✅ 5.9s · 80KB(103 期) | 🚫 | ⛔ |

AmazingData 那三张报表实测 0.01–0.02s,是同进程内缓存命中(`get_fundamentals` 已付过
4.3s 的首次成本),不是真实冷启动耗时。AKShare 三张报表体积大一个数量级是因为它一次返回
全部历史报告期(99–103 期),Tushare 返回的是配置窗口。

### 新闻

| 方法 | `tushare` | `akshare` | `eastmoney` | `longbridge` | `yfinance` | `alpha_vantage` |
| --- | --- | --- | --- | --- | --- | --- |
| `get_news` | ⚪ 0.73s(无匹配新闻) | ✅ 0.23s · 2.4KB | ✅ 0.18s · 2.4KB | ⛔ CLI 未安装 | 🚫 限频 19.0s | ⛔ 无 key |
| `get_global_news` | ✅ 2.9s · 1.2KB | — | — | — | 🚫 限频 19.0s | ⛔ 无 key |
| `get_etf_news` | ⚪ 6.3s(无 ETF 级新闻) | — | — | — | — | — |

新闻这块实测出两件事:

- **`akshare` 与 `eastmoney` 返回的是同一条新闻**(标题、体积几乎相同:2426B vs 2444B),
  实证了第 5 节说的「两档同源东财」—— 这两档不构成冗余。
- **Tushare 的 `news()` 有权限**(`get_global_news` 成功返回新浪+华尔街见闻快讯),
  但 `get_news`(个股维度)返回 `No news found`。所以之前"token 没有 news 权限"的说法
  不准确:是个股新闻按标的检索命中不到,不是无权限。

### 宏观、预测市场、内部交易

| 方法 | vendor | 实测 |
| --- | --- | --- |
| `get_macro_indicators` | `fred` | ⛔ `FRED_API_KEY` 未设置(且默认 `disabled`) |
| `get_prediction_markets` | `polymarket` | 🚫 连接超时 60s(`gamma-api.polymarket.com` 不可达;默认 `disabled`) |
| `get_insider_transactions` | `yfinance` / `alpha_vantage` | 🚫 限频 18.3s / ⛔ 无 key |

### ETF

| 方法 | `akshare` | `tushare` | `amazingdata` | `tdx` | `longbridge` |
| --- | --- | --- | --- | --- | --- |
| `get_etf_profile` | ✅ **19.0s** · 955B | ✅ 0.41s · 3.2KB | — | ⛔ 占位适配器 | ⚠️ 报 NO_DATA(实为 CLI 缺失) |
| `get_etf_intraday` | — | ✅ 0.60s · 2.5KB | ✅ 0.86s · 2.5KB | — | — |

- `get_etf_profile` 的 **19.0s** 独立复现了 8.1 节的性能问题:`fund_etf_spot_em` 内部分 15 页
  拉全市场再筛 1 行。同一份数据直连东财 `ulist.np` 是 0.39s。
- `longbridge` 那格是**约定偏差**:[longbridge.py:57-71](../tradingagents/dataflows/longbridge.py#L57)
  的 `get_etf_profile` 把 CLI 缺失的异常 `except Exception: continue` 吞掉,最后抛
  `NoMarketDataError`;同文件的 `get_news` 抛的是 `VendorNotConfiguredError`。路由对两者
  都 `continue`,所以不截断链,但终态哨兵会把「未配置」报成「查无数据」。
- **两个源的 ETF 分钟线数据不一致**:同为 510300 / 2026-08-28 / 5min 的 09:30 首根,
  AmazingData 是 `price 4.693, vol 28291266`,Tushare 是 `price 4.684, vol 3097300` ——
  成交量差 9.1 倍(不是整 100 倍,排除手/股单位),价格差 0.9 分。口径差异未查明,
  **跨源比较该字段前需要先定口径**。

### 资金面(仅 AmazingData 覆盖)

| 方法 | `amazingdata` |
| --- | --- |
| `get_dragon_tiger` | ✅ 0.45s · 2.1KB |
| `get_margin_trading` | ✅ 2.4s · 1.5KB |
| `get_shareholders` | ✅ 0.43s · 556B |
| `get_profit_forecast` | ✅ 0.23s · 998B |

这 4 个方法**没有第二个 vendor**,本地服务离线即返回 `NO_DATA`。

### 路由层外 7 项

| 探测 | 实测 |
| --- | --- |
| `resolve_instrument_identity("600519.SS")` | ✅ 0.0s → `{"company_name": "贵州茅台"}`,走 AKShare 路径 |
| `resolve_instrument_identity("AAPL")` | ⚪ → `{}`,`domestic_china_only=True` 按设计直接跳过 |
| `load_ohlcv("600519.SS")` | ✅ 0.44s,走 `_load_ohlcv_akshare` |
| `load_ohlcv("AAPL")` | 🚫 yfinance 返回 0 行 |
| reflection 收益回算 | 默认配置**整段跳过**;裸调 `yf.Ticker().history()` 验证时报限频 |
| `fetch_stocktwits_messages("AAPL")` | ⚠️ 返回 34B 占位串 `<stocktwits unavailable: URLError>` |
| `fetch_reddit_posts("AAPL")` | 🚫 3 个 subreddit RSS 全超时,总耗时 62s |

StockTwits 是**两层失败**:`.venv` 的 Python 默认 SSL 上下文缺根证书
(`CERTIFICATE_VERIFY_FAILED`);换 `certifi` 上下文修好证书后拿到的是 **HTTP 403**。
即使修证书也取不到数据。它不抛异常而是返回占位串,情绪分析师会拿到一句"不可用"。

### AKShare 的失败定位:是东财行情域抖动,不是 AKShare 坏了

矩阵里 AKShare 有 6 格 ✅、2 格 🚫,值得说清楚,否则容易误判成"AKShare 不可用"。
同一时刻做了一组对照探测:

东财**不是一个域名**,而是 6 个各自独立的域,项目通过 AKShare 用到全部 6 个。
逐域实测(标的 600519 / 510300):

| 域名 | 被哪个调用用到 | 结果 |
| --- | --- | --- |
| `push2.eastmoney.com` / `push2his.eastmoney.com` | `stock_zh_a_hist` → `get_stock_data`/`get_indicators` | **连接被断**,连打 6 次 **0/6** |
| `33.push2his` / `63.push2his` / `82.push2` 分片域 | 同上 | 同样失败 |
| `push2delay.eastmoney.com`(延时行情域) | `fund_etf_spot_em` → `get_etf_profile` | ✅ 连打 6 次 **6/6**,平均 0.20s |
| `emweb.securities.eastmoney.com` | `stock_*_sheet_by_report_em` → 三张报表 | ✅ 200 · 0.2–0.4s |
| `datacenter.eastmoney.com` | `stock_financial_analysis_indicator_em` → 财务指标 | ✅ 200 · 0.31s |
| `api.fund` / `fundf10.eastmoney.com` | `fund_etf_fund_info_em`、`fund_portfolio_hold_em` | ✅ 200 |
| `search-api-web.eastmoney.com` | `stock_news_em` + `eastmoney` vendor → 个股新闻 | ✅ 200 · 0.20s |
| `np-weblist.eastmoney.com` | `stock_info_global_em`(项目未接) | ✅ 200 · 0.23s |
| `qt.gtimg.cn`(腾讯)/ `hq.sinajs.cn`(新浪) | 对照组 | ✅ 双双 200 |

DNS 解析正常,是 TCP/TLS 层被 reset。所以:

- 失败范围**只限实时行情域 `push2` / `push2his` 及其分片**,其余 5 个东财域全程正常 ——
  这正好解释了为什么 AKShare 的 `get_stock_data`/`get_indicators` 挂而财报/新闻/ETF ✅。
- **`push2delay` 是现成的规避路径**:主域 0/6 的同一时刻,延时域 6/6 且 0.20s。
  `fund_etf_spot_em` 恰好用的就是它,这就是 ETF 画像那格能成功的原因。
  代价是行情有延迟(通常 15 分钟),对日线级分析无影响,对盘中实时校验不适用。
- 是**间歇性**的:同一 URL 在首轮探测中还是 200 · 0.17s,几分钟后转为持续失败,
  之后又自行恢复。本会话累计复现 3 次。
- 同一时刻腾讯、新浪均可用 —— 这给 8.1 节的建议补了一条**可用性**理由:腾讯不只是字段
  更全,它在东财行情域抖动时仍然可用,是真正独立的上游。

一个正面结论:`get_stock_data`/`get_indicators` 的默认链 `amazingdata,tushare,akshare` 在
这次东财抖动中**照常工作**,因为前两档一个是本地银河服务、一个是 Tushare,与东财无关。
兜底档跟着东财抖,但兜底之前的两档撑住了。

---

## 5. 上游集中度:fallback 链的冗余是假的

按第 2 节的「真实上游」列重新归类,会看到链式 fallback 的实际冗余度:

```
东方财富  ← akshare(9/11 个接口)、eastmoney
          ← 也就是 get_news 默认链 tushare,akshare,eastmoney 的后两档同源
          ← ETF 画像链 akshare,tushare,tdx,longbridge 的首档

银河证券  ← amazingdata(行情/指标/基本面/ETF分钟/资金面 全部链首)
          ← 本地服务离线则整条链首失效

新浪      ← akshare 的 stock_financial_analysis_indicator
          ← tushare 快讯 news() 的底层源之一(sina)

Yahoo     ← yfinance vendor + 3 处路由外直连
```

两个直接后果:

1. **`get_news` 的 `akshare,eastmoney` 两档同源东财**。东财限频或弹验证码时两档一起失败,
   链路只剩 Tushare 一档 —— 而当前 token 实测没有 `news` 权限。
2. **ETF 画像链实际只有 2 个有效独立源**(akshare→东财、tushare)。`tdx` 是占位,
   `longbridge` 需 CLI 认证。

已知上游风险:东财自 **2025-04 起按 IP 限频**,AKShare 侧已出现需手工抓 cookie、
过验证码的情况(akshare#7119)。限频按 IP 计,与用哪个封装无关。

---

## 6. 凭证速查

数据源相关环境变量(LLM provider key 不在此列,见 [.env.example](../.env.example)):

| 变量 | 数据源 | 缺失时行为 |
| --- | --- | --- |
| `AD_API_TOKEN` / `AD_API_PORT` / `AD_API_BASE` | AmazingData 本地服务 | 探测失败,链路回退 tushare/akshare |
| `TUSHARE_TOKEN` | Tushare Pro | vendor 跳过 |
| `ALPHA_VANTAGE_API_KEY` | Alpha Vantage | 抛配置错误 |
| `FRED_API_KEY` | FRED | vendor 跳过(且默认 `disabled`) |
| 无 | akshare / eastmoney / yfinance / polymarket / reddit / stocktwits | 直接可用 |
| CLI 自身认证 | longbridge | CLI 缺失或未登录则跳过 |

`AD_API_TOKEN` 指向**本地常驻服务**,与 QMT docker 的 `.env` 保持一致,不是银河账号密码。

---

## 7. 默认链路

来自 [default_config.py](../tradingagents/default_config.py)。`tool_vendors`(方法级)
**优先于** `data_vendors`(类别级)。

```python
data_vendors = {
    "core_stock_apis":      "amazingdata,tushare,akshare",
    "technical_indicators": "amazingdata,tushare,akshare",
    "fundamental_data":     "amazingdata,tushare,akshare",
    "news_data":            "akshare,longbridge",     # 被下面 get_news 覆盖
    "macro_data":           "disabled",
    "prediction_markets":   "disabled",
}
tool_vendors = {                                       # 方法级,优先
    "get_news":          "tushare,akshare,eastmoney",
    "get_etf_news":      "tushare",
    "get_global_news":   "tushare",
    "get_etf_profile":   "akshare,tushare,tdx,longbridge",
    "get_etf_intraday":  "amazingdata,tushare",
    "get_dragon_tiger":  "amazingdata",                # 资金面 4 个方法
    "get_margin_trading": "amazingdata",               # 仅 AmazingData 覆盖,
    "get_shareholders":  "amazingdata",                # 服务离线即 NO_DATA
    "get_profit_forecast": "amazingdata",
}
akshare_auto_route = True   # A 股代码把 akshare 提到链首(除显式 tushare/longbridge/tdx 链)
```

配的链**就是**全部候选:路由不会回退到没配置的 vendor(避免跨源数据不一致)。
`"default"` 哨兵表示用该方法所有可用 vendor。

---

## 8. 腾讯 / 新浪 / 东财 三家横评

2026-08-29 对这三家的公开接口做过两轮直连实测。东财**已接入**(`eastmoney` vendor +
AKShare 底层的 6 个东财域);腾讯、新浪**均未接入代码**,留档备查。

### 8.1 ETF 维度

标的 510300 / 159241 / 588000,三家全部直连成功,连续 30 次请求(间隔 0.1s)零失败。

| 能力 | 腾讯 `qt.gtimg.cn` | 新浪 `hq.sinajs.cn` | 东财 `push2` |
| --- | --- | --- | --- |
| 快照字段数 | 88 | 34 | 按需选 |
| **IOPV** | ✅ 第 78 位 | ❌ | ✅ `f441` |
| **单位净值 NAV** | ✅ 第 81 位 | ❌ | 需另调 `api.fund…/lsjz` |
| 折溢价率 | 由 IOPV 自算 | ❌ | ✅ `f402` |
| 日K/前复权、分钟线 | ✅ | ✅ | ✅ |
| 全市场 ETF 列表 | ❌ | ❌ | ✅ `clist`(1587 只) |
| 份额/规模、前十成分、净值序列 | ❌ | ❌ | ✅ `fundf10`(HTML) |
| 需要 Referer | 不需要 | **无则 403** | 不需要 |

三项实测结论:

- 腾讯第 78 位 = 4.6744 与东财 `f441` = 4.6744 **完全一致**;腾讯第 81 位 = 4.6758
  等于东财 `lsjz` 的 `DWJZ`。**腾讯一个请求同时给出 IOPV + NAV**,且不要 Referer,
  上游与东财独立 —— 适合做 [market_data_validator.py](../tradingagents/dataflows/market_data_validator.py)
  的第二个独立校验源,补第 5 节说的冗余缺口。
- **新浪对 ETF 可排除**:34 个字段里没有 IOPV 也没有 NAV。
- 性能差:`ak.fund_etf_spot_em` **20.7 秒**(内部分 15 页拉全量 1587 只再筛 1 行),
  直连东财 `ulist.np` 指定 secids **0.39 秒**,约 50 倍。该接口在
  [akshare_fundamentals.py:107](../tradingagents/dataflows/akshare_fundamentals.py#L107)、
  [:179](../tradingagents/dataflows/akshare_fundamentals.py#L179)、
  [ticker_name.py:27](../tradingagents/dataflows/ticker_name.py#L27) 共 3 处调用,
  有 15 分钟 `cached_call` 兜底,但每次缓存失效都要付这 20 秒。

费用上三家这些接口都是网页/App 内部接口:零费用、无需 key、**无授权、无 SLA**。
官方授权路径另算 —— 东财 Choice(`quantapi.eastmoney.com`,商业授权,报价需询)、
新浪财经 MCP(`zyhub.finance.sina.cn/mcp`,称免费申请,**是否覆盖 ETF 的 IOPV/份额未验证**)。

30 次短时探测**不能**证明生产级高频安全,东财确实会封 IP(第 5 节,本次实测已复现)。直连的真实收益是
把单次 ETF 快照的请求数从 15 次降到 1 次,**降低**触发限频的概率,而不是绕过限频。

### 8.2 基本面 · 三张报表 · 新闻 维度

标的统一 600519(贵州茅台)。新浪和东财的 URL + params 取自 AKShare 源码(即生产参数);
腾讯因 AKShare 中**不存在**任何财报/新闻函数,只能探测候选端点 —— 相关结论按「探测」而非
「实测」看待,见 8.2.5。

#### 8.2.1 估值快照(PE / PB / 市值)

| 项目 | 腾讯 `qt.gtimg.cn` | 新浪 `hq.sinajs.cn` | 东财 `push2*` |
| --- | --- | --- | --- |
| 快照字段总数 | **88** | 34 | 按需选 |
| 市盈率 | ✅ 19.92 | ❌ | ✅ `f162` = 18.22 |
| 市净率 | ✅ 6.46 | ❌ | ✅ `f167` = 6.46 |
| 总市值 / 流通市值 | ✅ 16218.56 亿 | ❌ | ✅ `f116` / `f117` |
| 换手率 / 量比 / 振幅 | ✅ | ❌ | ✅ `f168` 等 |
| 五档盘口 | ✅ | ✅ | 需另选字段 |
| 耗时 | 0.26s | 0.20s | 0.17s |

- **新浪在这一格可直接排除**:34 个字段是纯行情 + 五档盘口 + 日期时间,**没有任何估值字段**。
  这与 8.1 节 ETF 维度的结论一致(新浪也没有 IOPV/NAV)。
- 腾讯一个请求给出 PE/PB/市值/换手率/量比,**不需要 Referer**,是三家里最省事的。
- ⚠️ **PE 口径不一致**:腾讯 19.92 vs 东财 18.22(PB 两家都是 6.46)。差异约 9%,
  大概率是 TTM 与静态/动态市盈率之别。**跨源比较这个字段前必须先定口径**,
  与第 4 节记的 ETF 分钟线成交量差异属同类问题。

#### 8.2.2 财务指标(ROE / 毛利率 / 每股收益 体系)

| 项目 | 腾讯 | 新浪 | 东财 |
| --- | --- | --- | --- |
| 接口 | **未找到** | `money.finance.sina…vFD_FinancialGuideLine` | `datacenter…RPT_F10_FINANCE_MAINFINADATA` |
| 返回格式 | — | HTML(71KB,须 BeautifulSoup) | **JSON** |
| 端到端可解析 | — | ✅(AKShare 实测通过) | ✅ |
| 规模 | — | 按年逐页取 | **103 期 × 141 字段**,单次 0.31s / 358KB |
| ROE/毛利率/EPS 等关键项 | — | 12 项 | 14 项 |

东财在这一格明显占优:一次请求拿全 103 期、JSON 免解析。新浪要按年翻页 + 解析 HTML。

#### 8.2.3 三张报表

| 项目 | 腾讯 | 新浪 `quotes.sina.cn` | 东财 `emweb.securities` |
| --- | --- | --- | --- |
| 资产负债表 | ❌ | ✅ 103 期 × **141** 字段 | ✅ 103 期 × **319** 字段 |
| 利润表 | ❌ | ✅ 103 期 × **77** 字段 | ✅ 103 期 × **203** 字段 |
| 现金流量表 | ❌ | ✅ 99 期 × **64** 字段 | ✅ 99 期 × **254** 字段 |
| 最早覆盖 | — | 1998-12-31 | 1998-12-31 |
| 取全部报告期的请求数 | — | **1 次** | **21 次**(每批 5 期) |
| 单次响应体积 | — | 1.7–3.4 MB | 每批 44–68 KB |
| 返回格式 | — | JSON | JSON |
| 耗时 | — | 0.23–0.44s | 0.20–0.41s |

这是一组清晰的权衡,两家**报告期覆盖完全相同**(103/103/99 期,均自 1998 年起):

- **东财字段深约 2.3 倍**(319 vs 141 等),要做细粒度财报分析只有东财够用。
- **新浪请求省 21 倍**:一次拿全,东财要翻 21 批。若只需少数几期,东财更省流量;
  若要拉全历史,新浪是一次调用,东财是 21 次串行(限频风险随之上升)。
- 项目当前走东财(`stock_*_sheet_by_report_em`),第 4 节矩阵里 AKShare 三表耗时
  5.9–8.1s,正是这个 20+ 次串行请求的代价。

#### 8.2.4 新闻

个股新闻:

| 项目 | 腾讯 | 新浪 `vCB_AllNewsStock` | 东财 `search-api-web` |
| --- | --- | --- | --- |
| 可用性 | **未找到** | ✅ 40 条 | ✅ `hitsTotal` = 619 |
| 返回格式 | — | HTML(须 BeautifulSoup) | JSON |
| 严格时间倒序 | — | ✅ | ❌ 默认按相关性 |
| 最新一条 | — | **当天 08-29**(当天 9 条) | 08-27 |
| 每条含发布时间 | — | ✅ | ✅(但项目输出时丢弃,见 8.2.6) |

全局财经快讯:

| 项目 | 腾讯 | 新浪 | 东财 |
| --- | --- | --- | --- |
| 接口 | **未找到**(2 个候选全 404) | `zhibo.sina.com.cn/api/zhibo/feed` | `np-weblist…getFastNewsList` |
| 结果 | — | ✅ 200 · 0.15s · 54KB | ✅ 200 · 0.23s · 20KB |

两家都可用且都未接入项目(项目的 `get_global_news` 只有 yfinance / alpha_vantage / tushare
三档,前两档在境内网络下不可用)。**新浪与东财的快讯是可直接补上的境内替代**。

#### 8.2.5 腾讯:结论必须谨慎

腾讯**在基本面快照上是三家最强的**(88 字段,估值最全),但财报与新闻没能探到。
证据链:

| 探测 | 结果 |
| --- | --- |
| 对照组:板块排名 `getBoardRankList` | ✅ 200 · 4910B |
| 对照组:K 线 `newfqkline/get` | ✅ 200 · 2581B |
| 财务指标 3 个候选端点 | 404 ×2,`Can't load controller:F10Controller` ×1 |
| 三张报表 4 个候选端点 | 404 ×3,`Can't load controller:FinanceController` ×1 |
| 个股新闻 3 个候选端点 | 404 ×2,`Can't load controller:NewsController` ×1 |
| 快讯 2 个候选端点 | 404 ×2 |
| 再枚举 8 个 controller 名 | 全部 `Can't load controller:*` |
| 抓 `gu.qq.com/sh600519/gp/finance` 反查 API | HTML 仅 **3988B**,纯 SPA,**零** API 线索 |

对照组两项成功,证明腾讯域本身完全可达 —— 失败不是网络原因。但正确的结论是
**「在公开无鉴权途径下未能找到腾讯的财报/新闻接口」,而不是「腾讯不提供」**:
`Can't load controller:*` 说明 `appstock/app/<controller>/<action>` 这个路由模式真实存在,
只是这几个 controller 名猜错了。要确证需抓 SPA 的运行时 XHR(本次未做)。

**当前可下的判断**:腾讯适合做估值快照与行情的独立校验源(与 8.1 节 ETF 结论一致),
但**不能**作为财报或新闻源接入 —— 没有已验证的端点。

#### 8.2.6 顺带查出:项目东财新闻接口的两个实测问题

[eastmoney_news.py:57-74](../tradingagents/dataflows/eastmoney_news.py#L57-L74) 的 `param` 是**扁平结构**,
缺少东财 API 期望的 `cmsArticleWebOld` 嵌套配置块。实测后果:

| 请求写法 | 返回条数 | 日期跨度 | 时间倒序 | 落在 08-22~08-29 窗口内 |
| --- | --- | --- | --- | --- |
| 现状(扁平,无 `sort`) | **10**(`pageSize:40` 被忽略) | 08-27 ~ 08-15 | ❌ | **4 条** |
| 嵌套 + `"sort":"time"` | **40** | 08-27 ~ 08-17 | ✅ | **15 条** |

1. **`pageSize` 被服务端忽略** —— 扁平 param 下永远只返回 10 条,
   配置项 `news_article_limit` 实际不生效。
2. **无 `sort` 字段** —— 服务端按相关性排序,时间散布(08-15 ~ 08-27),
   叠加 [eastmoney_news.py:126-137](../tradingagents/dataflows/eastmoney_news.py#L126)
   的窗口过滤(该过滤本身是**正确**设计,防止回测看到未来新闻),
   请求 7 天窗口最终只剩 4 条。

改成嵌套 param + `sort=time` 后窗口内召回 **4 → 15 条**,提升约 3.7 倍。
AKShare 的 `stock_news_em` 用的是嵌套结构但写死 `"sort": "default"`,同样受排序问题影响。

另有一处信息损失:[输出模板](../tradingagents/dataflows/eastmoney_news.py#L143)是
`### {title} (source: {source})`,
**不含每条新闻的发布时间**,agent 拿到新闻后无从判断其新旧。

⚠️ 一处不能断言的观测:即使改用 `sort=time`,东财最新一条仍是 08-27,而新浪同一时刻有
08-29 当天 9 条。这是**单标的、单日**的一次观测,不足以证明东财搜索索引存在系统性延迟,
留作待查。

---

## 9. 加一个数据源要改哪里

1. 在 `dataflows/` 新建 `<vendor>_<domain>.py`,实现与现有 vendor **同名同签名**的方法
   (`route_to_vendor` 靠这个用同一组参数遍历整条链)。
2. 在 [interface.py](../tradingagents/dataflows/interface.py) 的 `VENDOR_METHODS`
   对应方法下登记。
3. 需要默认启用时,改 [default_config.py](../tradingagents/default_config.py) 的
   `data_vendors` / `tool_vendors`。
4. 凭证写进 [.env.example](../.env.example) 并在第 5 节补一行。
5. 无数据时抛 `NoMarketDataError`,未配置时抛 `VendorNotConfiguredError` —— 路由靠这两个
   区分「查不到」和「跳过」。**不要**自己返回哨兵字符串,那是路由层的职责。
