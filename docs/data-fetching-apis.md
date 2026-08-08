# 数据获取 API 参考

TradingAgents 里所有「信息获取」都收敛到一套统一的数据方法上。本文说明这些
方法各自做什么、传什么参数、返回什么,以及背后的路由 / 容错机制。

代码位置:

- Agent 工具层:[tradingagents/agents/utils/](../tradingagents/agents/utils/)
- 数据路由层:[tradingagents/dataflows/interface.py](../tradingagents/dataflows/interface.py)
- Vendor 实现层:[tradingagents/dataflows/](../tradingagents/dataflows/) 下各 `*_stock.py` / `*_news.py` / …

---

## 1. 三层架构

```
Agent (LangGraph 节点)
   │  调用 LangChain @tool
   ▼
① Agent 工具层  agents/utils/*_tools.py
   │  编排参数(日期窗口/默认值)、登记证据(provenance),然后:
   ▼
② 路由层  interface.py::route_to_vendor(method, *args, **kwargs)
   │  按类别/方法查配置 → 选定 vendor 链 → 依次尝试,带 fallback
   ▼
③ Vendor 实现层  dataflows/{yfinance,tushare,akshare,...}.py
      真正抓 yfinance / Tushare / AKShare / FRED / … 的数据
```

- **同一逻辑方法(如 `get_stock_data`)在每个 vendor 里都有同名实现**,签名保持一致,
  这样 `route_to_vendor` 才能用同一组参数依次尝试整条 vendor 链。
- Agent 只认第 ① 层的 `@tool`;第 ②③ 层对 agent 透明。

---

## 2. 路由与容错契约

`route_to_vendor` 是所有数据获取的唯一入口,核心约定(见
[interface.py:304](../tradingagents/dataflows/interface.py#L304)):

1. **配置即链路**:某类别配 `"tushare,akshare"` 就先试 Tushare、失败再试 AKShare。
   **不会**回退到没配置的 vendor(避免跨源数据不一致)。`"default"` 表示用该方法所有
   可用 vendor。
2. **A 股自动路由**:A 股代码(`600519` / `600519.SS` / `sh600519` …)在未显式指定
   Tushare/Longbridge/TDX 时,会把 AKShare 提到链首。可用 `akshare_auto_route=False` 关闭。
3. **永不抛错(对 agent)**:返回的永远是字符串。遇到问题返回带前缀的「哨兵」文本,
   让 agent 如实报告「数据不可用」而不是编造数值:

   | 哨兵前缀 | 含义 |
   |---|---|
   | `NO_DATA_AVAILABLE:` | 有 vendor 明确说「查不到」——代码无效/退市/未覆盖/数据过期 |
   | `DATA_SOURCE_UNAVAILABLE:` | 只有网络/连通性错误(主机不可达、被墙、超时) |
   | `DATA_SOURCE_DISABLED:` | 该类别被配置为 `disabled`/`none`/`off` |

   只有非网络的真实错误(坏代码、解析 bug)才会真正 `raise`。

---

## 3. 方法总表

按类别(`TOOLS_CATEGORIES`)分组。「默认 vendor 链」来自
[default_config.py](../tradingagents/default_config.py) 的 `data_vendors` / `tool_vendors`。

| 类别 | 方法 | 默认 vendor 链 | 可用 vendor |
|---|---|---|---|
| core_stock_apis | `get_stock_data` | amazingdata,tushare,akshare | amazingdata, alpha_vantage, yfinance, tushare, akshare |
| technical_indicators | `get_indicators` | amazingdata,tushare,akshare | amazingdata, alpha_vantage, yfinance, tushare, akshare |
| fundamental_data | `get_fundamentals` | amazingdata,tushare,akshare | amazingdata, alpha_vantage, yfinance, tushare, akshare |
| fundamental_data | `get_balance_sheet` | amazingdata,tushare,akshare | 同上 |
| fundamental_data | `get_cashflow` | amazingdata,tushare,akshare | 同上 |
| fundamental_data | `get_income_statement` | amazingdata,tushare,akshare | 同上 |
| news_data | `get_news` | tushare,akshare,eastmoney | alpha_vantage, yfinance, longbridge, akshare, eastmoney, tushare |
| news_data | `get_global_news` | tushare | yfinance, alpha_vantage, tushare |
| news_data | `get_etf_news` | tushare | tushare |
| news_data | `get_insider_transactions` | alpha_vantage / yfinance | alpha_vantage, yfinance |
| macro_data | `get_macro_indicators` | disabled(可选 fred) | fred |
| prediction_markets | `get_prediction_markets` | disabled(可选 polymarket) | polymarket |
| etf_data | `get_etf_profile` | akshare,tushare,tdx,longbridge | akshare, tushare, tdx, longbridge |
| etf_data | `get_etf_intraday` | amazingdata,tushare | amazingdata, tushare |
| capital_flow_data | `get_dragon_tiger` | amazingdata | amazingdata |
| capital_flow_data | `get_margin_trading` | amazingdata | amazingdata |
| capital_flow_data | `get_shareholders` | amazingdata | amazingdata |
| capital_flow_data | `get_profit_forecast` | amazingdata | amazingdata |

> 默认配置面向「国内 A 股 only」:`macro_data`、`prediction_markets` 默认关闭,
> 海外源(yfinance / alpha_vantage / polymarket / fred)需要显式启用并配置对应 API key。

---

## 4. 方法详解

参数默认值以 Agent 工具层(`@tool`)签名为准。所有方法返回的都是**格式化字符串**
(Markdown 报告或表格文本),除非另有说明——设计成直接喂给 LLM 阅读,而不是结构化对象。

### 行情

#### `get_stock_data(symbol, start_date, end_date)`
- **用途**:某标的在日期区间内的 OHLCV 日线行情。
- **参数**:
  - `symbol` `str` — 代码,如 `AAPL`、`600519.SS`。
  - `start_date` `str` — 起始日 `yyyy-mm-dd`。
  - `end_date` `str` — 结束日 `yyyy-mm-dd`。
- **返回**:带表头的行情表(日期 / 开高低收 / 成交量)文本。
- 实现:[core_stock_tools.py](../tradingagents/agents/utils/core_stock_tools.py)

#### `get_indicators(symbol, indicator, curr_date, look_back_days=30)`
- **用途**:单个技术指标在回看窗口内的取值(RSI、MACD 等)。
- **参数**:
  - `symbol` `str` — 代码。
  - `indicator` `str` — 单个指标名,如 `rsi`、`macd`。**每次只查一个**;传逗号分隔的多个会被
    工具层拆开逐个查询。
  - `curr_date` `str` — 当前交易日 `yyyy-mm-dd`(窗口右端)。
  - `look_back_days` `int` — 回看天数,默认 `30`。
- **返回**:该指标随时间变化的表格文本。
- 实现:[technical_indicators_tools.py](../tradingagents/agents/utils/technical_indicators_tools.py)

### 基本面(财报)

#### `get_fundamentals(ticker, curr_date)`
- **用途**:公司基本面概览(名称、行业、市值、PE/PB、EPS、股息率、Beta、52 周高低等)。
- **参数**:`ticker` `str`;`curr_date` `str`(部分 vendor 如 yfinance 不使用该值)。
- **返回**:基本面字段清单文本。

#### `get_balance_sheet(ticker, freq="quarterly", curr_date=None)`
#### `get_cashflow(ticker, freq="quarterly", curr_date=None)`
#### `get_income_statement(ticker, freq="quarterly", curr_date=None)`
- **用途**:资产负债表 / 现金流量表 / 利润表。
- **参数**:
  - `ticker` `str`。
  - `freq` `str` — 报告频率 `annual` 或 `quarterly`,默认 `quarterly`。
  - `curr_date` `str | None` — 截止日,用于过滤掉未来报告期。
- **返回**:对应报表的分节文本;ETF 代码会返回「不适用」说明。
- 实现:[fundamental_data_tools.py](../tradingagents/agents/utils/fundamental_data_tools.py)

### 新闻

#### `get_news(ticker, start_date, end_date)`
- **用途**:个股/标的在时间窗口内的公司新闻与公告。
- **参数**:`ticker`;`start_date`、`end_date`(`yyyy-mm-dd`)。
- **返回**:`## <ticker> News, from <start> to <end>` 文档,每条新闻一个 `###` 块;
  窗口外的新闻会被丢弃(回测不会看到「未来」新闻)。
  单标的最多 `news_article_limit`(默认 20)条。

#### `get_global_news(curr_date, look_back_days=None, limit=None)`
- **用途**:宏观 / 大盘级别的全局新闻(非某一标的)。
- **参数**:
  - `curr_date` `str` — 当前日。
  - `look_back_days` `int | None` — 回看天数,`None` 用配置默认(`global_news_lookback_days`,默认 7)。
  - `limit` `int | None` — 最多返回条数,`None` 用配置默认(`global_news_article_limit`,默认 10)。
- **返回**:合并去重、按时间倒序的全局新闻文本。

#### `get_etf_news(symbol, start_date, end_date)`
- **用途**:境内 ETF/基金的相关新闻——基金自身公告 + 按主题/重仓股衍生的新闻。
- **参数**:`symbol`(境内 ETF/基金代码);`start_date`、`end_date`。
- **返回**:ETF 主题新闻 + 重仓股新闻的文档;非境内 ETF 返回 `NO_DATA_AVAILABLE`。

#### `get_insider_transactions(ticker)`
- **用途**:内部人(高管/大股东)交易记录。
- **参数**:仅 `ticker`。
- **返回**:内部人交易明细文本。
- 实现:[news_data_tools.py](../tradingagents/agents/utils/news_data_tools.py)

### 宏观

#### `get_macro_indicators(indicator, curr_date, look_back_days=None)`
- **用途**:从 FRED 拉宏观时间序列(政策利率、国债收益率、通胀、就业、增长等)。
- **参数**:
  - `indicator` `str` — 友好别名(见下表)或原始 FRED series ID(如 `CPIAUCSL`)。
  - `curr_date` `str` — 窗口右端;不返回其后的观测(避免泄露未来数据)。
  - `look_back_days` `int | None` — 回看窗口,`None` 用 1 年(`DEFAULT_LOOKBACK_DAYS=365`)。
- **返回**:含序列标题、单位、频率、最新值、区间变化和近期观测表的 Markdown 报告。
- **默认关闭**,需 `data_vendors.macro_data="fred"` 且配置 FRED API key。
- 实现:[macro_data_tools.py](../tradingagents/agents/utils/macro_data_tools.py) /
  [fred.py](../tradingagents/dataflows/fred.py)

支持的友好别名(`MACRO_SERIES`):

| 类别 | 别名 → FRED series |
|---|---|
| 利率/国债 | `fed_funds_rate`/`fed_funds`→FEDFUNDS,`2y_treasury`→DGS2,`10y_treasury`→DGS10,`30y_treasury`→DGS30,`10y_2y_spread`/`yield_curve`→T10Y2Y |
| 通胀 | `cpi`→CPIAUCSL,`core_cpi`→CPILFESL,`pce`→PCEPI,`core_pce`→PCEPILFE,`inflation_expectations`→T10YIE |
| 增长 | `real_gdp`→GDPC1,`gdp`→GDP,`industrial_production`→INDPRO |
| 就业 | `unemployment`→UNRATE,`nonfarm_payrolls`/`payrolls`→PAYEMS,`initial_claims`→ICSA |
| 货币/市场 | `m2`/`money_supply`→M2SL,`vix`→VIXCLS,`dollar_index`→DTWEXBGS |
| 情绪/地产 | `consumer_sentiment`→UMCSENT,`housing_starts`→HOUST,`retail_sales`→RSAFS |

### 预测市场

#### `get_prediction_markets(topic, limit=None)`
- **用途**:某事件主题的预测市场隐含概率(前瞻性事件)。
- **参数**:
  - `topic` `str` — 事件关键词,如 `Fed rate cut`、`recession 2026`。
  - `limit` `int | None` — 最多返回市场数(按成交量排序),`None` 默认 6。
- **返回**:匹配主题的活跃市场 Markdown 报告,含隐含概率、成交量、结算日、近一周变动。
- **默认关闭**,需 `data_vendors.prediction_markets="polymarket"`。
- 实现:[prediction_markets_tools.py](../tradingagents/agents/utils/prediction_markets_tools.py) /
  [polymarket.py](../tradingagents/dataflows/polymarket.py)

### ETF

#### `get_etf_profile(symbol, curr_date=None)`
- **用途**:ETF 概况——折溢价、IOPV、规模、重仓成分等。
- **参数**:`symbol`(境内 ETF 代码,如 `510300` / `510300.SS`);`curr_date` `str | None`。
- **返回**:ETF 画像 Markdown 文本。
- 实现:[etf_data_tools.py](../tradingagents/agents/utils/etf_data_tools.py)

#### `get_etf_intraday(symbol, trade_date, freq="5min")`
- **用途**:ETF 日内分钟级行情。
- **参数**:`symbol`;`trade_date` `str`;`freq` `str` — 分钟频率,默认 `5min`。
- **返回**:分钟级数据(`dict`,与其他返回字符串的方法不同)。
- 实现:[amazingdata_etf.py](../tradingagents/dataflows/amazingdata_etf.py) /
  [tushare_intraday.py](../tradingagents/dataflows/tushare_intraday.py)

### A 股资金面 / 事件面(仅 AmazingData 覆盖)

以下四个方法签名一致:`method(ticker, curr_date=None) -> str`。服务离线时路由回退为
`NO_DATA_AVAILABLE`。实现:[amazingdata_capital.py](../tradingagents/dataflows/amazingdata_capital.py)

| 方法 | 用途 | 返回内容 |
|---|---|---|
| `get_dragon_tiger` | 龙虎榜 | 近期上榜明细:上榜原因、营业部买卖额(最近 30 条) |
| `get_margin_trading` | 融资融券 | 近 20 个交易日的融资/融券余额与买入偿还 |
| `get_shareholders` | 股东户数 | 近期各报告期的 A 股股东户数变化(12 期) |
| `get_profit_forecast` | 业绩预告 | 近期预告净利润区间、变动幅度与原因(8 条) |

---

## 5. Vendor 清单

`VENDOR_LIST`(见 [interface.py:162](../tradingagents/dataflows/interface.py#L162)):

| Vendor | 覆盖 | 备注 |
|---|---|---|
| `yfinance` | 海外股票行情/基本面/新闻 | 免费,无 key |
| `alpha_vantage` | 行情/指标/基本面/新闻/内部人交易 | 需 key |
| `amazingdata` | A 股行情/指标/基本面/ETF 日内/资金面 | 需服务;国内默认首选 |
| `tushare` | A 股行情/指标/基本面/新闻/ETF | 需 token |
| `akshare` | A 股行情/指标/基本面/新闻/ETF | 免费,A 股自动路由首选 |
| `eastmoney` | A 股/ETF 新闻 | 东方财富 |
| `longbridge` | 新闻/ETF 概况 | 长桥 |
| `tdx` | ETF 概况 | 通达信 |
| `fred` | 美国宏观 | 需 key,默认关闭 |
| `polymarket` | 预测市场 | 默认关闭 |

---

## 6. 配置方式

在 `DEFAULT_CONFIG` 或 `TRADINGAGENTS_*` 环境变量中调整
(见 [default_config.py:263](../tradingagents/default_config.py#L263)):

- `data_vendors.<category>`:按**类别**指定 vendor 链,逗号分隔按序 fallback。
  可设 `disabled`/`none`/`off` 关闭该类别。
- `tool_vendors.<method>`:按**具体方法**指定,**优先级高于**类别级配置。
- `akshare_auto_route`(默认 `True`):A 股代码是否自动把 AKShare 提到链首。

新增数据源的步骤:在对应 `dataflows/<vendor>_*.py` 实现同名方法 → 在
`interface.py::VENDOR_METHODS` 里把它登记到相应 method 下 →(可选)加进 `VENDOR_LIST`。

---

## 7. 新增一个数据方法(method)

1. 在需要的 vendor 文件里实现,保持与其他 vendor **同名同签名**。
2. 在 `TOOLS_CATEGORIES` 里把方法名归入某个类别。
3. 在 `VENDOR_METHODS` 里登记 `method -> {vendor: impl}` 映射。
4. 在 `agents/utils/` 下新增一个 `@tool` 封装(编排参数 + 登记 provenance +
   识别哨兵前缀),供 agent 调用。
5. 在 `default_config.py` 的 `data_vendors` / `tool_vendors` 里给出默认路由。
