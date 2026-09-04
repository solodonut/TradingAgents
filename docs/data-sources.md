# 数据源全集

本文是 **vendor 视角**的数据源清单:每个数据源的真实上游是谁、覆盖哪些方法、要什么
凭证、花不花钱、默认开不开。

方法视角(每个 `get_*` 方法传什么、返回什么)见
[data-fetching-apis.md](./data-fetching-apis.md)。两篇互为索引,不重复内容。

> **⚠️ 2026-09-03:AKShare 已全局停用,第 7 节的建议已全部落地。** 它从
> `VENDOR_LIST` / `VENDOR_METHODS` 注销,`akshare_auto_route` 开关与 7.4 记录的三处
> 旁路(外加 `stockstats_utils` 的 A 股分支)、`service_health` 的 AKShare 探针卡都已删除。
> 同时采纳 7.2 的两条链序建议:`get_news` 提 `eastmoney` 到 `tushare` 之前,
> `get_etf_profile` 去掉恒被跳过的 `tdx` 占位档。
>
> **本文的实测矩阵(第 4 节)与横评(第 8 节)是 2026-08-29 的快照,保留 AKShare 的行/列
> 作为历史测量与回滚依据** —— 不要把它们读成「当前可路由的源」。哪些是当前形态、哪些
> 是历史,以第 2、3、6、7 节的说明为准。`akshare_*.py` 模块与 `akshare` 依赖仍在仓库里,
> 回滚只需重新注册。

---

## 1. 总览

数据源分两类,区别在于**走不走 `route_to_vendor`**:

```
① 路由层内 —— 9 个 vendor,登记在 interface.py::VENDOR_METHODS
   Agent → @tool → route_to_vendor(method) → vendor 链 → 首个成功即停
   永不抛错,失败返回 NO_DATA_AVAILABLE / DATA_SOURCE_UNAVAILABLE 哨兵
   (原第 10 个是 akshare,已注销;配置里再写 "akshare" 会抛 ValueError)

② 路由层外 —— 4 处直连,不经 route_to_vendor
   反幻觉身份解析、reflection 收益回算、stockstats OHLCV、情绪分析师社交源
   AGENTS.md 的「不要在 agent 代码里直连数据源」对这几处是**已知例外**
```

**每个 vendor 到底能不能用、多快、返回多少数据**,见第 4 节的全量实测矩阵
(54 个路由组合 + 7 项路由外,逐格真实调用)。

### 全源 × 全能力总表

一张表看完 **16 个源**(测量时的 10 个路由内 vendor + 2 处路由外社交源 + 腾讯/新浪/东财三家
未接入源 + QMT Native Bridge)在 10 类能力上的实测结果。**这是全文的索引**:耗时、体积、
失败根因等细节在第 4 节(现有源)、第 8 节(三家横评)和第 9 节(QMT Native Bridge)。
`akshare` 那一行是**历史行**(2026-09-03 已注销),留作回滚依据。

图例:✅ 有数据 · ⚪ 调用成功但内容为空 · ⛔ 未配置(缺 key/CLI/占位) ·
🚫 本次网络层失败 · ⚠️ 静默降级 · ❌ 接口存在但无此字段 ·
❓ 未找到公开接口 · ➖ 该源不覆盖此能力 · `未测` 本次未探测

| 数据源 | 行情 | 指标 | 估值快照 | 财务指标 | 三表 | 个股新闻 | 全局快讯 | ETF 画像 | ETF 分钟 | 独有能力 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| **`amazingdata`** 银河/QMT | ✅ | ✅ | ➖ | ✅ | ✅ | ➖ | ➖ | ➖ | ✅ | **龙虎榜/两融/股东/盈利预测**(唯一源) |
| **`tushare`** Tushare Pro | ✅ | ✅ | ➖ | ✅ | ✅ | ⚪ 无命中 | ✅ | ✅ | ✅ | ETF 新闻(⚪) |
| ~~**`akshare`** 东财+新浪~~(已注销) | 🚫 push2 抖动 | 🚫 | ➖ | ✅ | ✅ 103 期 | ✅ | ➖ | ✅ 19s | ➖ | — |
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
| **QMT Native Bridge**(未接入) | ⚠️ 当日 ✅,历史**逐 code** | ➖ 须自算 | ⚠️ 有股本/涨跌停,**无 PE/PB** | ❌ 501 | ❌ 501 | ➖ | ➖ | ✅ 全 300 成分申赎清单 | ⚠️ 仅当日 | **申赎篮子/涨跌停价/五档盘口/板块成分/真实持仓**(唯一源) |

读这张表要注意 6 点,否则会误读:

1. **一格 🚫 不代表方法不可用**。每格是「该 vendor 自己」的能力(直接调 vendor 函数、绕过
   `route_to_vendor`),而实际调用走 fallback 链 —— 链上任一格 ✅ 就够用。例:测量时
   `get_stock_data` 的默认链是 `amazingdata,tushare,akshare`,AKShare 挂了但前两档撑住了
   (正因为它那两格本来就是 🚫,现在的链 `amazingdata,tushare` 没有损失)。
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
6. **QMT Native Bridge 那一行的 ⚠️ 全是「口径」而不是「抖动」**:它的行情格不是网络问题,
   而是**历史日线有没有取决于该 code 在客户端本地库里补过没有** —— 没补过的 code 返回
   **200 + 全 0 行**,不报错。这一格误读的代价比其它任何格都大,细节与接入前必须做的
   零值拦截见第 9 节。它也是唯一能给出**账户真实持仓/委托/成交**的源,但项目当前没有对应方法。

---

## 2. 路由层内:9 个 vendor

「真实上游」是**实际提供数据的机构**,不是 Python 包名。这一列是本表最重要的信息:
多个 vendor 可能共享同一上游,链式 fallback 因此可能不提供真正的冗余(见第 5 节)。

| vendor | 真实上游 | 覆盖方法 | 凭证 | 费用 | 默认 |
| --- | --- | --- | --- | --- | --- |
| `amazingdata` | **银河证券**(经本地 QMT docker 常驻服务 `127.0.0.1:8888`) | 行情/指标/基本面/ETF 分钟/资金面全部 4 个方法 | `AD_API_TOKEN`(+`AD_API_PORT`/`AD_API_BASE`) | 需银河账户与 QMT;服务本身无 API 费 | ✅ 多数类别链首 |
| `tushare` | **Tushare Pro**;快讯 `news()` 底层为**新浪 + 华尔街见闻** | 行情/指标/基本面/新闻/全球新闻/ETF 画像/ETF 分钟/ETF 新闻 | `TUSHARE_TOKEN` | 注册免费,**ETF/新闻等端点需付费积分** | ✅ |
| `eastmoney` | **东方财富** 搜索 API(`search-api-web.eastmoney.com`)直连 | `get_news` | 无 | 免费,无 SLA | ✅ `get_news` 链首 |
| `longbridge` | **长桥 OpenAPI**(经 `longbridge` CLI subprocess) | `get_news`、ETF 画像 | CLI 自身认证 | 需长桥账户 | ✅ 在链尾 |
| `tdx` | 通达信「问小达」 | ETF 画像 | 无(见下) | 无 | ⚠️ **纯占位** |
| `yfinance` | **Yahoo Finance** | 行情/指标/基本面/新闻/全球新闻/内部交易 | 无 | 免费,无 SLA | ❌ 需显式启用 |
| `alpha_vantage` | **Alpha Vantage**(`alphavantage.co`) | 行情/指标/基本面/新闻/全球新闻/内部交易 | `ALPHA_VANTAGE_API_KEY` | 免费层有每日配额,超出需订阅 | ❌ 需显式启用 |
| `fred` | **美联储圣路易斯分行**(`api.stlouisfed.org`) | `get_macro_indicators` | `FRED_API_KEY` | 免费 | ❌ `disabled` |
| `polymarket` | **Polymarket** Gamma API | `get_prediction_markets` | 无 | 免费 | ❌ `disabled` |

**已注销**:`akshare`(上游为**东方财富** 9 个 `_em` 接口 + **新浪** 1 个财务指标接口,
曾覆盖行情/指标/基本面/新闻/ETF 画像,无凭证免费)。它 2026-09-03 从 `VENDOR_LIST` /
`VENDOR_METHODS` 移除,原因见第 7 节:唯一失效的域是东财 `push2`/`push2his`(行情),
而它真正的成本是 `get_etf_profile` 那 19 秒 —— `fund_etf_spot_em` 会翻完全市场 ETF。

### `tdx` 是占位,不是可用 vendor

[tdx.py](../tradingagents/dataflows/tdx.py) 的 `get_etf_profile` **无条件抛**
`VendorNotConfiguredError`。通达信在本工作区只经 MCP 暴露,没有运行时 Python 依赖。
它登记在路由表里的唯一作用是:让生产配置能写 `tdx` 这一档而不崩,路由会干净跳过。

测量时 `get_etf_profile` 的默认链是 `akshare,tushare,tdx,longbridge`,**有效档位只有 3 个**。
现在的默认链是 `tushare,longbridge`:摘掉 AKShare 的同时也去掉了这个恒被跳过的 `tdx` 占位档,
所以链上每一档都是真会被调用的。`tdx` 仍登记在 `VENDOR_METHODS["get_etf_profile"]` 里
(写进配置不会崩,路由干净跳过),只是不再出现在默认链中。
[data-fetching-apis.md](./data-fetching-apis.md) 第 8 节的字段级偏好表里把通达信 MCP
列为多个字段的首选,那是**在 Codex 会话里经 MCP 手工查询**的结论,代码路径拿不到。

---

## 3. 路由层外:4 处直连

这几处不走 `route_to_vendor`,因此**没有 fallback、没有哨兵字符串**,失败方式与路由层不同。
但前三处各自都有配置前置分支,默认配置下**并不真的出境**:

| 位置 | 默认配置下实际走哪条路 | 用途 | 为什么在路由外 |
| --- | --- | --- | --- |
| [agent_utils.py:160](../tradingagents/agents/utils/agent_utils.py#L160) `resolve_instrument_identity` | A 股 → **Tushare**(`ticker_name.resolve_ticker_name`,空/失败再回退 yfinance 英文名);非 A 股且 `domestic_china_only=True` → 直接返回 `{}`;其余才走 yfinance `Ticker().info` | **反幻觉**:标的身份解析一次,注入每个分析师 prompt | 身份必须单源确定,链式 fallback 会让不同 vendor 给出不同名称 |
| [trading_graph.py:298](../tradingagents/graph/trading_graph.py#L298) `_resolve_outcome` | `domestic_china_only=True` → **整段跳过**(log 一行 Skipping),不调 yfinance | **reflection**:回算已实现收益 + benchmark 对比(算 alpha) | 学习层,不是 agent 工具调用 |
| [stockstats_utils.py](../tradingagents/dataflows/stockstats_utils.py) `load_ohlcv` | **无分支**:一律走 yfinance `download()` + 5 年 CSV 缓存。A 股曾在这里被分流到 `akshare_stock._fetch_hist`,该分支已删除 —— A 股 OHLCV 现在只经 vendor(AmazingData/Tushare)取,**别指望这条路覆盖 A 股** | stockstats 指标计算的 OHLCV 底座 | vendor 内部实现细节 |
| [sentiment_analyst.py:81-82](../tradingagents/agents/analysts/sentiment_analyst.py#L81) | **无分支,无条件出境**:StockTwits `api.stocktwits.com`、Reddit `search.json` + RSS 回退 | 情绪分析师的社交面输入 | 只服务单个 analyst,没登记成 `TOOLS_CATEGORIES` 方法 |

Reddit/StockTwits 都不需要 key(Reddit 有可选 OAuth,失败降级到 RSS),两者都自带
`tradingagents/0.2 (+github…)` 这样的具名 UA —— Reddit 会拦裸 `Mozilla/5.0` 和 `curl/…`。

**一个容易搞错的点**:前两处虽然代码里写着 yfinance,但在默认配置(`domestic_china_only=True`)
下,A 股基本不会触达 Yahoo —— 身份先走 Tushare、reflection 整段跳过。**但这里比 AKShare
时期弱了一格**:`resolve_ticker_name` 在 Tushare 返回空或失败时会回退 yfinance(取英文名),
以前中间还垫着一层 AKShare;`load_ohlcv` 的 A 股分支也没了,不过 A 股 OHLCV 现在根本不走这条路
(反幻觉快照用 `AmazingData → Tushare`,指标走 vendor)。默认配置下唯一无条件出境的仍是
情绪分析师那两个社交源,而第 4 节实测显示两者当前都拿不到数据。

---

## 4. 实测能力矩阵

2026-08-29 22:19–22:35 对 `VENDOR_METHODS` 的**全部 54 个 (方法, vendor) 组合**加上第 3 节
的 7 项路由外直连做了真实调用。

> **本节是 2026-08-29 的历史快照,未重测。** `akshare` 列/行保留原样(它 2026-09-03 已注销),
> 因为这些数字正是第 7 节决策的依据。当前可路由的 vendor 见第 2 节。

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
| `resolve_instrument_identity("600519.SS")` | ✅ 0.0s → `{"company_name": "贵州茅台"}`,当时走 AKShare 路径(该档已删,现在 Tushare 之后直接回退 yfinance) |
| `resolve_instrument_identity("AAPL")` | ⚪ → `{}`,`domestic_china_only=True` 按设计直接跳过 |
| `load_ohlcv("600519.SS")` | ✅ 0.44s,当时走 `_load_ohlcv_akshare`(该分支已删,A 股不再经这条路) |
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

一个正面结论:`get_stock_data`/`get_indicators` 当时的默认链 `amazingdata,tushare,akshare` 在
这次东财抖动中**照常工作**,因为前两档一个是本地银河服务、一个是 Tushare,与东财无关。
兜底档跟着东财抖,但兜底之前的两档撑住了 —— 这也是现在把这两条链砍成 `amazingdata,tushare`
不算损失的直接依据。

---

## 5. 上游集中度:fallback 链的冗余是假的

按第 2 节的「真实上游」列重新归类,会看到链式 fallback 的实际冗余度:

```
东方财富  ← eastmoney(get_news 链首)
          ← tushare 快讯 news() 的可选源之一(eastmoney)
          ← 停用前还有 akshare(9/11 个接口),它与 eastmoney 同源

银河证券  ← amazingdata(行情/指标/基本面/ETF分钟/资金面 全部链首)
          ← 本地服务离线则整条链首失效

新浪      ← tushare 快讯 news() 的底层源之一(sina)
          ← 停用前还有 akshare 的 stock_financial_analysis_indicator

Yahoo     ← yfinance vendor + 2 处路由外直连(身份兜底、非 A 股 OHLCV)
```

两个直接后果:

1. **`get_news` 的 `eastmoney,tushare` 两档实际同源东财**(Tushare 快讯的源列表里也有
   eastmoney)。东财限频或弹验证码时两档一起失败。**这一点在停用 AKShare 前后没有变化** ——
   原来的 `akshare` 档也是东财,所以摘掉它没有减少任何真实冗余(实测两者返回同一条新闻)。
2. **ETF 画像链现在是 2 档**(tushare、longbridge),原来 4 档里 `tdx` 是占位、`akshare`→东财,
   有效独立源数量不变。`longbridge` 需 CLI 认证,实际常态是单档 Tushare。

已知上游风险:东财自 **2025-04 起按 IP 限频**,AKShare 侧已出现需手工抓 cookie、
过验证码的情况(akshare#7119)。限频按 IP 计,与用哪个封装无关 ——
所以 `eastmoney` 直连同样受这条风险影响。

---

## 6. 凭证速查

数据源相关环境变量(LLM provider key 不在此列,见 [.env.example](../.env.example)):

| 变量 | 数据源 | 缺失时行为 |
| --- | --- | --- |
| `AD_API_TOKEN` / `AD_API_PORT` / `AD_API_BASE` | AmazingData 本地服务 | 探测失败,链路回退 tushare |
| `TUSHARE_TOKEN` | Tushare Pro | vendor 跳过 |
| `ALPHA_VANTAGE_API_KEY` | Alpha Vantage | 抛配置错误 |
| `FRED_API_KEY` | FRED | vendor 跳过(且默认 `disabled`) |
| 无 | eastmoney / yfinance / polymarket / reddit / stocktwits | 直接可用 |
| CLI 自身认证 | longbridge | CLI 缺失或未登录则跳过 |

`AD_API_TOKEN` 指向**本地常驻服务**,与 QMT docker 的 `.env` 保持一致,不是银河账号密码。

---

## 7. 默认链路

来自 [default_config.py](../tradingagents/default_config.py)。`tool_vendors`(方法级)
**优先于** `data_vendors`(类别级)。

```python
data_vendors = {
    "core_stock_apis":      "amazingdata,tushare",
    "technical_indicators": "amazingdata,tushare",
    "fundamental_data":     "amazingdata,tushare",
    "news_data":            "eastmoney,tushare",       # 被下面 get_news 覆盖
    "macro_data":           "disabled",
    "prediction_markets":   "disabled",
}
tool_vendors = {                                       # 方法级,优先
    "get_news":          "eastmoney,tushare",
    "get_etf_news":      "tushare",
    "get_global_news":   "tushare",
    "get_etf_profile":   "tushare,longbridge",
    "get_etf_intraday":  "amazingdata,tushare",
    "get_dragon_tiger":  "amazingdata",                # 资金面 4 个方法
    "get_margin_trading": "amazingdata",               # 仅 AmazingData 覆盖,
    "get_shareholders":  "amazingdata",                # 服务离线即 NO_DATA
    "get_profit_forecast": "amazingdata",
}
# 没有 akshare_auto_route,也没有任何按市场重排链的逻辑:配置写什么就是什么。
```

配的链**就是**全部候选:路由不会回退到没配置的 vendor(避免跨源数据不一致)。
`"default"` 哨兵表示用该方法所有可用 vendor。写 `"akshare"` 会抛 `ValueError`(未知 vendor)。

### 7.1 排序原则

上面这套默认值是历史演进的结果,不是按统一标准排的。若要重排,建议按以下权重(高 → 低):

1. **上游独立性** —— 第 5 节已经说明链式 fallback 的冗余大量是假的(两档同源东财)。
   首档撞在同一个上游上,是唯一会一次性打掉整条链的失误。
2. **可用性** —— 不依赖易失效的前置条件(本地服务在跑 / CLI 已登录 / 客户端 GUI 开着)。
3. **覆盖面** —— 字段齐不齐、历史深不深。
4. **速度** —— **放最后**。一次 run 里 LLM 延迟绝对主导,0.2s 与 2s 的差别看不出来;
   只有 `get_etf_profile` 那种**19 秒**的量级才值得为速度改排序。

### 7.2 停用 AKShare:决策依据(已落地)

**这一小节记录的是决策依据,配置已经是上面 7 节开头那份。** 保留是因为「为什么这么排」
比「排成什么样」更容易丢。

AKShare 的不稳定性在第 4 节末尾已定位清楚:**只坏在东财 `push2` / `push2his` 行情域**,
其余 5 个东财域全程正常。所以它 8 格里 6 格 ✅,挂的正好是 `get_stock_data` / `get_indicators`
——而这两格前面已有两档健康源兜住。**停用它的最大收益其实不是稳定性,是 `get_etf_profile`
从 19.0s 降到 0.41s**(见 8.1 节:19 秒是 `fund_etf_spot_em` 分 15 页拉全市场的实现问题,
与上游抖动无关)。

逐项改动:三条 `data_vendors` 链删掉 `akshare` 尾档(这格本来就 🚫);`news_data` 改
`eastmoney,tushare`(三个新闻方法都被 `tool_vendors` 覆盖,此行实为死配置,改它只为一致);
`get_news` 从 `tushare,akshare,eastmoney` 改 `eastmoney,tushare`;`get_etf_profile` 从
`akshare,tushare,tdx,longbridge` 改 `tushare,longbridge`(顺手删恒跳过的 `tdx`);
`get_etf_news` / `get_global_news` / `get_etf_intraday` / 资金面 4 个方法的配置不变。

**为什么保持 `amazingdata` 在首档而不是让快一个数量级的 Tushare 上位**:摘掉 AKShare 后每条链
(下同,「摘掉后」即当前形态)
只剩 2 档,再把 Tushare 提到首档,就等于行情/指标/基本面/ETF画像/新闻**全部**首档指向同一上游
——正是第 5 节批评的那个问题。保持「银河(本地)→ Tushare」是两个真正独立的上游,
且 amazingdata 无外部限频、与资金面 4 个方法口径一致。

**为什么 `get_news` 把 eastmoney 提到 Tushare 前**:实测 Tushare 个股新闻 ⚪ 0.73s 无命中
(`get_global_news` 有权限且 ✅,是个股维度检索命中不到),eastmoney ✅ 0.18s,省掉每次空转。
代价是个股新闻变成单上游东财 —— 但**这一点在改动前就已成立**:实测 `akshare` 与 `eastmoney`
返回的是同一条新闻(2426B vs 2444B)。停用 AKShare 在这里没有减少任何真实冗余。

**逐方法代价**:

| 方法 | 停用后的链 | 实际损失 |
| --- | --- | --- |
| `get_stock_data` / `get_indicators` | `amazingdata,tushare` | **零**。AKShare 这两格实测就是 🚫 |
| `get_fundamentals` | `amazingdata,tushare` | 零(0.30s / 4.3s 双 ✅) |
| 三张报表 | `amazingdata,tushare` | 轻微:AKShare 一次给**全部 99–103 个报告期**,Tushare 只给配置窗口。仅深度历史报表有感 |
| `get_news` | `eastmoney,tushare` | 零(同源) |
| `get_etf_profile` | `tushare,longbridge` | ⚠️ **唯一实质损失**:**IOPV 彻底没有源了**(字段表里首选就是 AKShare,通达信 MCP 实测不返回);另丢基金份额、重仓成分中文名 |
| `get_etf_intraday` / 资金面 4 个 / `get_global_news` | 不变 | 零 |

讽刺的是丢掉的这几个 ETF 字段走的是 **`push2delay` 延时域(实测 6/6 全通、0.20s)**,
**不受要规避的那个抖动影响** —— 它们是被 AKShare 那 19 秒的实现连带牺牲的。

### 7.3 为什么只改配置做不到「禁用」:`akshare_auto_route`(已删除)

原 `interface.py` 有这么一段:

```python
if (config.get("akshare_auto_route", True)
    and "akshare" in VENDOR_METHODS[method]
    and "tushare" not in explicit_vendor_names ...):
    if _is_a_share_symbol(symbol):
        vendor_chain = ["akshare"] + [v for v in vendor_chain if v != "akshare"]
```

**无条件 prepend,不检查 akshare 在不在配的链里。** 当时默认每条链都含 `tushare` 才恰好躲过;
一旦把某条链改成不含 tushare 的(如 `"amazingdata"` 单档),AKShare 会被重新插到**链首**。
这就是本次改动必须动代码、不能只动配置的原因。

该分支及 `akshare_auto_route` 开关已整段删除,现在不存在任何按市场重排 vendor 链的逻辑。
连带删除的还有它在 [stockstats_utils.py](../tradingagents/dataflows/stockstats_utils.py)
`load_ohlcv` 里的那个 A 股分支 —— 那条路现在一律走 yfinance `download()`(本机 🚫),
所以 **A 股链里绝不能加回 yfinance**,别指望这条路覆盖 A 股。

### 7.4 配置管不到的 AKShare 残留(已全部切断)

改配置之外还有 4 条路会 `import akshare`,`data_vendors` / `tool_vendors` 对它们**完全无效**。
本次一并切断:

| 位置 | 原行为 | 处理 |
| --- | --- | --- |
| [market_data_validator.py](../tradingagents/dataflows/market_data_validator.py) `_load_mainland_ohlcv` | 反幻觉快照的验证链**硬编码** `AmazingData → Tushare → AKShare` | 删第三档,现在是 `AmazingData → Tushare`;失败仍抛 `SnapshotVendorChainError` |
| [ticker_name.py](../tradingagents/dataflows/ticker_name.py) `_akshare_name` | 中文名解析 `tushare → AKShare → yfinance`,喂给 `resolve_instrument_identity`(反幻觉身份注入)与 WebUI 代码清单 | 删中间档,现在 `tushare → yfinance`(英文名)。仍 fail-open + 6s 线程超时 |
| [tushare_etf_news.py](../tradingagents/dataflows/tushare_etf_news.py) `_fetch_akshare_holdings` | `get_etf_news` 的 **tushare vendor 内部**:`fund_portfolio` 返回空时直接 `import akshare` 调 `fund_portfolio_hold_em` | 删除。⚠️ 这是最隐蔽的一条 —— 在此之前 `get_etf_news: "tushare"` 并不是纯 Tushare。Coverage Notes 里那句「AKShare 兜底」也一并去掉 |
| [stockstats_utils.py](../tradingagents/dataflows/stockstats_utils.py) `_load_ohlcv_akshare` | A 股且 `akshare_auto_route=True` 时分流到 AKShare | 删除,见 7.3 |

外加 `api/service_health.py` 的 AKShare 探针卡(探 `push2` 可达性 + `push2his` 新鲜度)——
探的是已注销 vendor,一并删掉。注意删完之后 `_DATA_SERVICES` 里只剩 `fred` 走
「可达性探测 → 新鲜度探测」这条分离路径,相关测试已迁到 `fred`。

**没有全局 `disabled_vendors` 开关** —— 本次是逐处删除,不是加开关。回滚要手工还原上述各处。

### 7.5 链只剩两档,第三档补谁

注销 AKShare 后,四条 A 股链都只剩两档(`amazingdata,tushare` ×3 / `eastmoney,tushare` /
`tushare,longbridge`),而且 `eastmoney` 与 `tushare` 快讯读的是同一家上游(见第 5 节),
新闻链的冗余是名义上的。**实时 ETF IOPV / 折溢价率现在没有任何源**——这是已经发生的
缺口,不是假设。补第三档的候选:

| 候选 | 评价 |
| --- | --- |
| **腾讯 `qt.gtimg.cn`**(未接入) | ✅ **首选**。东财行情域 0/6 的同一时刻腾讯 200 ✅,是真正独立的第 4 个上游;88 字段含 PE/PB/换手/市值;配合直连东财 `ulist.np`(0.39s)可同时解决 ETF 画像那 19 秒。**能补上除 IOPV 外的全部丢失字段**(见 8.1) |
| QMT Native Bridge(未接入) | ⚠️ **不适合当第三档**。历史日线逐 code、失败是 200+全 0 行、要求 QMT 客户端在跑(盘后通常关着)。它的价值在**独有字段**(申赎篮子、涨跌停价),不在补位(见第 9 节) |
| `yfinance` | ❌ 别加回 A 股链。本机三个 Yahoo 域裸 curl connect timeout,且会重新激活 `load_ohlcv` 那条无哨兵的路 |
| `tdx` | ❌ 占位适配器,运行时恒跳过。本次已从 `get_etf_profile` 的链里摘掉(见 7.2) |

---

## 8. 腾讯 / 新浪 / 东财 三家横评

2026-08-29 对这三家的公开接口做过两轮直连实测(当时 AKShare 还在路由里,所以下面
「东财已接入」包含它底层的 6 个东财域)。现在代码里只剩 `eastmoney` vendor 这一条东财
直连路径(`search-api-web` 新闻);腾讯、新浪**均未接入代码**,留档备查。

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
  直连东财 `ulist.np` 指定 secids **0.39 秒**,约 50 倍。这 20 秒是停用 AKShare 的主要
  性能动因(见 7.2)。测量时它有 3 处调用(`akshare_fundamentals` 两处 + `ticker_name`);
  现在只剩 [akshare_fundamentals.py:107](../tradingagents/dataflows/akshare_fundamentals.py#L107)、
  [:179](../tradingagents/dataflows/akshare_fundamentals.py#L179) 两处,而该模块已从
  `VENDOR_METHODS` 注销,**运行时不再被调用**。

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
- 测量时项目经 AKShare 走东财(`stock_*_sheet_by_report_em`),第 4 节矩阵里 AKShare
  三表耗时 5.9–8.1s,正是这个 20+ 次串行请求的代价。**现在三张报表走
  `amazingdata,tushare`**,东财/新浪这两列都只是候选参考。

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

## 9. QMT Native Bridge(未接入,已实测)

[QMT Native Bridge](file:///Volumes/%5BC%5D%20Windows%2011.hidden/Users/joseph/Code/qmt-native-bridge)
把**国金 QMT 完整版客户端**的能力经 HTTP/WebSocket 暴露到局域网(109 条 HTTP + 2 条 WS,
其中 27 ✅ / 24 ⚠️ / 60 固定 501)。**未接入本项目**,以下是 2026-09-03 15:00–15:20
对它 15 条数据面路由逐条真实调用的结论。

### 9.1 先分清:它不是 `amazingdata`

两个源都叫「QMT」,但**不是同一个东西,也不是同一个上游**,混起来会得出完全错误的替换结论:

| | `amazingdata`(已接入) | QMT Native Bridge(未接入) |
| --- | --- | --- |
| 真实上游 | **银河证券**,经本地 QMT docker 常驻服务 | **国金证券**,经 Windows 上的完整版 QMT 客户端进程 |
| 地址 | `127.0.0.1:8888`(`AD_API_PORT`) | 局域网 `<VM-IP>:8000`(本机实测 `10.211.55.3:8000`) |
| 取数机制 | 服务内调银河 SDK | 客户端**进程内**内置 Python 模型 `ContextInfo` + socket IPC |
| 覆盖面 | 行情/指标/基本面/ETF 分钟/资金面 4 类 | 行情快照/合约/板块/日历/ETF 申赎清单/**真实账户与交易** |
| 财务三表 | ✅ | ❌ 固定 501 |

所以它**不是** `amazingdata` 的备份档:两者能力面只在「当日行情」上重叠,资金面(龙虎榜/两融/
股东户数/业绩预告)和财务三表**桥一条都没有**。第 5 节的上游集中度问题里,「银河证券离线则
`amazingdata` 整条链首失效」这一条,桥**补不上**。

### 9.2 实测能力矩阵(2026-09-03)

标的 `600519.SH` / `510300.SH` / `000001.SZ`;桥版本 0.1.0;数据面默认不鉴权。

| 路由 | 实测 | 内容 |
| --- | --- | --- |
| `/api/meta/health` | ✅ 0.01s | `{"status":"ok","data_agent":"up"}` |
| `/api/market/full_tick` | ✅ 0.008s | **19 字段**:五档 `askPrice/bidPrice/askVol/bidVol` + OHLC + `lastClose` + `amount` + `volume`(手)+ `pvolume`(股)+ `stockStatus` |
| `/api/market/history`(1d) | ⚠️ 0.03–0.10s | **逐 code 分化**,见 9.3.1 |
| `/api/market/history`(1m / 5m) | ⚠️ 0.04s | 1m **241 根 = 当日整段**(09:30→15:00);5m **63 根**(含 09-02 尾盘 15 根)。**没有更早的分钟线** |
| `/api/market/batch_history` | ✅ 0.03s | 一次拿 5 个 code;零值分化同上 |
| `/api/market/indices` | ✅ 0.026s | 七大指数(上证/深成/创业板/沪深300/上证50/中证500/中证1000)快照 |
| `/api/market/divid_factors` | 🚫 **500** | `TypeError: get_divid_factors() got an unexpected keyword argument 'start_time'` —— **桥侧 bug**,`api-coverage.md` 记的是 ✅ |
| `/api/instrument/detail` | ✅ 0.01s | **30 字段**(见 9.5) |
| `/api/instrument/is_suspended` | ⚠️ 0.008s | 600519 在 **15:00 后返回 `true`** —— 盘后语义不是「停牌」。桥仓库记的盘中实测是 `false`。**不可直接当停牌判断** |
| `/api/sector/list` | ✅ 0.01–0.03s | 分层:根节点 10 个目录;`node=沪深板块` → 13 个板块 |
| `/api/sector/stocks` | ✅ 0.02s | `沪深300` → **300 个 code**(指数成分清单;**没有权重**) |
| `/api/etf/list` | ✅ 0.02s | **1706 只**(桥仓库 08-24 记的是 1686) |
| `/api/etf/info` | ✅ 真实申赎清单 | 见 9.5,**这是它最强的一格** |
| `/api/calendar/trading_dates` | ✅ 0.008s | `market=SH` 区间交易日列表 |
| `/api/utility/stock_name` · `batch_stock_name` | ✅ 0.01s | 中文名(GBK 已修复,不乱码);批量上限 **100 个 code** |
| `/api/financial/report` | ❌ **501** | `financial fundamental data is not available in-process on this client` |
| `/api/formula/call` | ⚠️ | `MA.ma1` 600519 = 1295.338,但 `resolved.bar_time` 是 **13:05**(主图 1m 序列 38686 根的「最后一根」不是收盘那根) |

**延迟是它最突出的优点**:除个别请求外全在 **8–100 ms**。对比第 8.1 节 AKShare 的
`get_etf_profile` 19–20 秒,快两个数量级。

### 9.3 三个限制,决定它能替换什么

#### 9.3.1 历史日线是**逐 code 的本地库状态**,失败方式是 200 + 全 0 行

同一次 `batch_history`(`period=1d&count=5`)里:

| code | 5 根日线 |
| --- | --- |
| `000001.SZ` 平安银行 | **5 根全真实**;拉到 `count=1200` 仍 **1200 根全真实**,回溯到 **2021-09-22** |
| `000300.SH` 沪深300 | **5 根全真实** |
| `600519.SH` 贵州茅台 | 只有 **20260903** 一根真实,前 4 根 `open=high=low=close=volume=0` |
| `510300.SH` / `510500.SH` | 同上,只有当日 |

把 600519 的区间拉到 `20260101→20260903`:返回 **163 行,只有 1 行 `close` 非 0**,其余
带 `suspendFlag: 1`。

机制:`data_agent.py::_h_market_data_ex` 直接调 `ContextInfo.get_market_data_ex`,**不传
`subscribe`** —— 读的就是客户端**本地数据库**。补过数据的 code(在主图/自选/持仓里的)有深度历史,
没补过的没有。而桥的 `/api/download/*` **整组固定 501**(下载是 xtdata 专有),所以**桥自己补不了**,
只能在 QMT 界面手工「补充数据」。

**接入时必须做零值拦截**:`close == 0 && suspendFlag == 1` 要判成无数据、抛 `NoMarketDataError`。
不拦的话 agent 会拿到一串 0.0 当真实价格 —— 这正是项目反幻觉约定(`NO_DATA_AVAILABLE` 哨兵
而不是编造数值)要防的事,而且比网络失败更危险:它是 **HTTP 200**。

#### 9.3.2 数据面依赖 QMT 客户端在跑,且受 handlebar 时间片约束

数据面每次取数都要等客户端进程内模型的**协作时间片**(`SERVE_SLICE_SECONDS = 0.5`),而这个
时间片与**真钱交易面共用同一个框架线程**。实测到的三个后果:

- **`health` 说 `up` 不等于能取数**。收盘后连打时出现过 `data agent socket error: timed out`
  和 `[WinError 10061] 目标计算机积极拒绝`,而同一时刻 `/api/meta/health` 仍答 `data_agent: up`
  —— 健康检查是 listener 层的 ping,取数要排队。瞬时,几秒后自行恢复,但**不能靠 health 做熔断**。
- **批量有硬上限 100 个 code**(`MAX_BATCH_CODES`,两侧都校)。
- **A 股收盘后客户端通常被关掉**,而本项目多在盘后跑分析 —— 这是可用性上最现实的障碍,
  比任何字段缺失都致命。

对本项目还有一层:4 个分析师即使串行跑,每个也会打多次数据工具。把桥放进链首等于让 LLM
分析的节奏去挤那个 0.5 秒时间片。**它适合做低频校验源,不适合做链首主源。**

#### 9.3.3 没有财务,没有新闻

- **财务**:`/api/financial/report` 固定 501。签名已查明(`get_financial_data(['Table.field'], ['code'], start, end)`),
  但这台客户端**没有加载财务库**(横跨 10 年 2431 行全 `None`)。
- **新闻**:桥**一条新闻路由都没有** —— 不是 501,是压根不在 API 形状里。

### 9.4 逐方法:能替换什么

| 项目方法 | 桥能不能替 | 结论 |
| --- | --- | --- |
| `get_stock_data` | ⚠️ **不能做通用源** | 覆盖面 = 「这台客户端补过哪些标的」。可作**当日收盘价的独立校验源**(第 5 节说的冗余缺口),或对**已补数据的固定标的池**做主源 |
| `get_indicators` | ⚠️ 只能换底座 | 项目的指标是本地 stockstats 算的,桥只能替 `load_ohlcv` 的 OHLCV;而 30 天回看窗口对没补数据的 code 直接不成立。`/api/formula/call` **不能**用:单值/单 bar、算不出来时**安静返回 `-1.0`**、且 bar 不一定是最新的 |
| `get_fundamentals` | ⚠️ 部分 | 给得出总股本/流通股(`TotalVolume`/`FloatVolume`)、涨跌停价、前收 → **总市值可自算**;但 **PE/PB/EPS/股息率全给不出**(缺财务)。第 1 节那个「估值快照」缺口,桥只补一半,腾讯的 88 字段仍是更直接的补位 |
| `get_balance_sheet` / `get_cashflow` / `get_income_statement` | ❌ | 501 |
| `get_news` / `get_global_news` / `get_etf_news` | ❌ | 无此能力 |
| `get_etf_profile` | ✅ **强补位** | `/api/etf/info` 给出现有 4 个 vendor 都没有的**完整申赎清单**;但**不给 IOPV、基金规模、基金份额、跟踪指数、管理人、费率**,所以是**补字段**而不是**换源**(见 9.5) |
| `get_etf_intraday` | ⚠️ 仅当日 | 当日 5min/1min 可用,可作第三个独立源去定第 4 节那个「AmazingData 与 Tushare 成交量差 9.1 倍」的口径 —— 桥把两种单位**分开命名**(`volume` 手 / `pvolume` 股,实测严格 100 倍),这正是定口径需要的。**历史交易日取不到**,所以替不了这个方法的主要用法 |
| `get_dragon_tiger` / `get_margin_trading` / `get_shareholders` / `get_profit_forecast` | ❌ | 桥没有对应路由。这 4 个方法仍然只有 `amazingdata` 一档 |
| `get_macro_indicators` / `get_prediction_markets` / `get_insider_transactions` | ➖ | 出桥的范围(仅 A 股股票 + ETF) |

一句话:**它替不掉任何一个现有 vendor 的主源地位,但能补两个现有 15 个源都没有的东西**(9.5),
并给「当日行情」加一个真正独立的第三方上游。

### 9.5 独有能力:现有 16 个源里只有它能给

**① ETF 完整申赎清单**(`/api/etf/info`,510300 实测):

```
nav 4.614 · navPerCU 4152589.89 · reportUnit 900000(最小申赎单位份数)
cashBalance 105955.89 · ecc 103405.89 · maxCashRatio 0.5
enableCreation 1 · enableRedemption 1 · creationLimit 0 · redemptionLimit 3600000000
stocks: 300 只(不是前十!)每只带
  componentVolume(一个申赎单位里的份数)· ReplaceFlag(49 允许现金替代 179 只 / 50 必须现金替代 121 只)
  ReplaceRatio · ReplaceBalance · physCreateRedeem · discountReplaceRatio · redemptReplaceBalance
```

三个直接用法,都是现有源做不到的:

- **申赎篮子** —— [data-fetching-apis.md](./data-fetching-apis.md) 第 8 节里这个字段写的是
  「Tushare 付费 ETF 权限(可得时)/ 当前凭证未确认」。桥**免费、实测有真值**。
- **全部成分股 + 份数** —— Tushare `fund_portfolio` 只给**前十**重仓(AKShare 的持仓兜底也只给
  前十,且已随本次停用删除)。有了 `componentVolume` 就能算
  近似权重(`componentVolume × 价格 / navPerCU`),等于补上了 `/api/instrument/index_weight`
  拿不到的东西。注意 **21 只 `componentVolume = 0`**(全现金替代),算权重时不能当缺失值丢掉。
- **折溢价** —— `lastPrice / nav - 1`,实测 4.621 / 4.614 = **+0.15%**。
  ⚠️ **口径未定**:`tradingDay` 与 `preTradingDay` 都返回 **0**,所以**这个接口自己说不清 `nav`
  是哪一天的净值**。用它算折溢价前必须另行确认口径 —— 与第 4 节的 ETF 分钟线成交量差异、
  第 8.2.1 节的 PE 口径差异是同一类问题。

**② 合约详情 30 字段**(`/api/instrument/detail`,600519 实测):

```
InstrumentName 贵州茅台 · ExchangeID SH · OpenDate 20010827 · TradingDay 20260903
PreClose 1297.5 · UpStopPrice 1427.25 · DownStopPrice 1167.75   ← 涨跌停价:现有源全都没有
TotalVolume / FloatVolume 1250081601                              ← 总股本/流通股 → 市值可自算
PriceTick 0.01 · VolumeMultiple 1 · InstrumentStatus 0 · HSGTFlag(本例 null)
```

**涨跌停价**是现有 15 个源一个都不提供的字段,而它对 A 股决策有直接意义(一字板 = 有价无量,
交易员/风险辩论环节现在无从判断)。

**③ 五档盘口**(`/api/market/full_tick`)—— 腾讯/新浪也有,但两家都未接入代码;桥是**已实测可调**的。

**④ 板块成分清单**(`/api/sector/stocks`)—— `沪深300` 一次给 300 个 code,0.02s。

**⑤ 交易日历**(`/api/calendar/*`)—— 项目当前**完全没有**交易日历,日期窗口全靠自然日推算。

**⑥ 真实账户状态**(`/api/trading/*`、`/api/credit/*`)—— 持仓、委托、成交、资产、信用负债。
**项目当前没有任何方法承接这类信息**:`final_trade_decision` 是在不知道实际持仓的前提下做的。
这不是「换数据源」,是新增一类能力,要动的是 `TOOLS_CATEGORIES` 而不是某条 vendor 链。
⚠️ 交易面**无条件鉴权且 fail-closed**(`QMT_BRIDGE_API_KEY` 为空则一律 503),
且下单面 `dry_run` 默认开、`opType` 常量未经真机校准 —— 只读查询可以考虑,**写入面不要碰**。

### 9.6 接入建议

如果要接,按第 10 节的步骤,并注意这 6 点:

1. **vendor 名不要叫 `qmt`**,会和 `amazingdata` 的上游混掉。建议 `qmtbridge`,文件
   `dataflows/qmtbridge_*.py`。
2. **凭证**:`QMT_BRIDGE_BASE`(如 `http://10.211.55.3:8000`)+ 可选 `QMT_BRIDGE_API_KEY`
   (`X-API-Key` 请求头)。base 未配 → `VendorNotConfiguredError`。
3. **探测降级照 `amazingdata_utils.py` 抄**:它已经解决了同一个问题(「本地常驻服务可能离线」),
   包括把服务端连接类错误归成 `VendorRateLimitError` 让路由回退,而不是 crash 整个 run。
   桥这边要额外把 `{"code":"unavailable"}`(agent socket 超时)归到这一类,
   把 `{"code":"unsupported"}`(501)归到 `VendorNotConfiguredError`。
4. **零值拦截是硬要求**(9.3.1),否则违反反幻觉约定。
5. **只放链尾或校验位**,别放链首(9.3.2)。
6. **先接 `get_etf_profile` 的字段补位最划算**:唯一源、免费、20ms、且填的正是现有链
   `tushare,longbridge` 填不上的字段。风险最小、收益最明确 —— 尤其在停用 AKShare 之后,
   实时 IOPV / 折溢价率已经彻底没有源(7.2、7.5),不过桥这边的 `nav` 口径也未定(见上)。

---

## 10. 加一个数据源要改哪里

1. 在 `dataflows/` 新建 `<vendor>_<domain>.py`,实现与现有 vendor **同名同签名**的方法
   (`route_to_vendor` 靠这个用同一组参数遍历整条链)。
2. 在 [interface.py](../tradingagents/dataflows/interface.py) 的 `VENDOR_METHODS`
   对应方法下登记。
3. 需要默认启用时,改 [default_config.py](../tradingagents/default_config.py) 的
   `data_vendors` / `tool_vendors`。
4. 凭证写进 [.env.example](../.env.example) 并在第 5 节补一行。
5. 无数据时抛 `NoMarketDataError`,未配置时抛 `VendorNotConfiguredError` —— 路由靠这两个
   区分「查不到」和「跳过」。**不要**自己返回哨兵字符串,那是路由层的职责。
