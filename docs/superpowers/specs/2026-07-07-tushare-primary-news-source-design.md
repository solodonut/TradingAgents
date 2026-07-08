# Tushare 全面接管新闻资讯 — 设计文档

**日期**: 2026-07-07
**状态**: 已批准,待实现

## 背景与目标

当前新闻路由分两类,互相独立:

- `get_news`(个股新闻)—— tool_vendors 覆盖为 `akshare,eastmoney,longbridge`,工作正常。
- `get_global_news`(宏观/全局新闻)—— **无** tool_vendors 覆盖,回落到 category 级
  `news_data: "akshare,longbridge"`。但 akshare/longbridge 都**未实现** `get_global_news`,
  所以这条链在当前纯国内配置下是**断的**(`route_to_vendor` 会因"配置的 vendor 不可用"抛
  `ValueError`)。

目标:让 **Tushare** 成为个股新闻和全局新闻两类的**主要来源**,并保留现有源作为兜底。
Tushare Pro 账号为高级档(≥2000 分),`news` / `major_news` / `cctv_news` / `anns_d` 均可调用。

## 关键现实约束(非 bug,是数据源固有特性)

- Tushare 的快讯流(`news`、`major_news`)是**通用 feed,不支持按个股搜索**。做个股新闻只能拉
  通用流后按股票名/代码在正文里过滤,命中可能稀疏、有噪声(与 Longbridge news 的"无标的过滤"
  局限同源)。
- `anns_d`(公司公告)是唯一真正按 `ts_code` 的个股数据,但内容是**公告标题 + PDF 链接,无正文全文**。
- `news` 接口**单次只能传一个 `src`**(数据源),多源需逐个拉取后合并。
- `cctv_news`(新闻联播)按**单日**取数,窗口 N 天需遍历 N 次(有 1h 缓存兜底)。

## 架构

新增单个模块 `tradingagents/dataflows/tushare_news.py`,对齐现有 news vendor 模式
(参考 `akshare_news.py` / `yfinance_news.py` / `eastmoney_news.py`),暴露两个函数:

```python
def get_news(ticker, start_date, end_date) -> str
def get_global_news(curr_date, look_back_days=None, limit=None) -> str
```

复用 `tushare_utils` 已有基建:

- `get_tushare_client()` — Tushare Pro 客户端(带 token 校验)。
- `call_tushare(func)` — 统一把限流/权限/无 token 报错归一成
  `TushareRateLimitError` / `TushareNotConfiguredError`。
- `cached_call(key, ttl, fn)` — 1h TTL 缓存(与 akshare_news 一致)。
- `to_ts_code()` / `display_symbol()` / `is_a_share`。
- 个股中文名用 `ticker_name.resolve_ticker_name()` 做关键词。

### 契约(严格对齐现有 news vendor)

- 非 A 股(仅 `get_news`)→ 抛 `NoMarketDataError`,让 `route_to_vendor` 降级下一个源。
- 失败 → 返回 `Error fetching news for <label>: ...` 哨兵字符串(不抛异常穿透到 prompt)。
- 无结果 → `No news found for <label> ...`。
- 成功 → `## <label> News, from <start> to <end>:` 文档,每条 `### <标题> (source: ...)`。
- 日期做**前视安全过滤**(回测绝不泄露 `end_date` 之后发布的新闻)。

## `get_news`(个股)

非 A 股先抛 `NoMarketDataError`。A 股则两路取数后合并:

**A 路 — 公司公告 `anns_d`**(真·个股数据)
- 调 `pro.anns_d(ts_code=<ts_code>, start_date=YYYYMMDD, end_date=YYYYMMDD)`。
- 字段 `ann_date, name, title, url`。渲染 `### <title> (source: 公司公告)` + `Link: <url>`。
- 内容:业绩预告、重组、停复牌、股东变动等,信息质量最高。

**B 路 — 关键词过滤快讯 `news`**
- 用中文名(`resolve_ticker_name`)+ 6 位代码作关键词,在窗口内 `news` 快讯的标题/正文里
  做 `contains` 过滤。
- 渲染 `### <title> (source: 快讯/<src>)` + 正文摘要。
- 名字解析失败 → B 路直接跳过(只给公告),不报错。

**合并规则**
- 公告在前(更硬),快讯在后,按发布时间倒序。
- 合计截断到 `news_article_limit`(默认 20)。
- 两路都空 → `No news found for <label> between <start> and <end>`。
- 单路失败(异常)→ 用能拿到的那路降级;**两路都抛异常**才返回 `Error fetching news` 哨兵。

## `get_global_news`(全局)

窗口 = `[curr_date - look_back_days, curr_date]`,`look_back_days` 默认取
`global_news_lookback_days`(=7)。三路取数合并:

**1. `news`(滚动快讯)**
- `pro.news(src=<src>, start_date=..., end_date=...)`,单次一个 src。
- src 列表来自新增 config `tushare_news_flash_sources`,默认 `["sina", "wallstreetcn"]`,
  逐源拉取后合并。渲染 `### <title> (source: 快讯/<src>)` + 正文。

**2. `major_news`(长篇通讯)**
- `pro.major_news(start_date=..., end_date=...)`,渲染标题 + 正文摘要,source 标 `长篇`。

**3. `cctv_news`(新闻联播)**
- 遍历窗口内每一天调 `pro.cctv_news(date=YYYYMMDD)`(按天缓存)。
- 渲染 `### <title> (source: 新闻联播)` + 正文。

**合并规则**
- 三路汇总,按发布时间倒序;标题相同的去重合并。
- 截断到 `limit`(默认 `global_news_article_limit`=10)。
- 输出 `## Global News, from <start> to <end>:` 文档。
- 三路全部失败 → 返回错误提示串(与 yfinance 全局新闻返回风格一致)。

## 路由与配置接线

`interface.py::VENDOR_METHODS` 注册:

```python
"get_news":        { ..., "tushare": get_tushare_news },
"get_global_news": { ..., "tushare": get_tushare_global_news },
```

`default_config.py` 改动(开箱即用,Tushare 成为主新闻源):

- `tool_vendors["get_news"]`: `"akshare,eastmoney,longbridge"` → `"tushare,akshare,eastmoney"`
  (Tushare 打头,保留 akshare/eastmoney 兜底)。
- 新增 `tool_vendors["get_global_news"] = "tushare,yfinance"`(修好当前断掉的全局新闻链,
  Tushare 为主、yfinance 兜底)。
- 新增 `tushare_news_flash_sources = ["sina", "wallstreetcn"]`(快讯 src 列表)。

## 缓存与错误分层

- 所有拉取走 `tushare_utils.cached_call(key, 3600, fn)`,key 带 ts_code/src/date 区分。
- `cctv_news` 按天缓存(key 含日期),窗口重叠天然命中。
- `call_tushare()` 归一限流/权限/无 token 报错。`TushareNotConfiguredError` 让 router
  干净降级到下一个 vendor,而非把 traceback 塞进分析师 prompt。

## 测试(全部 mock,不打真实 API;遵循 `pytest -m "not integration"`)

`get_news`:
- 非 A 股抛 `NoMarketDataError`。
- 公告 + 快讯合并;公告在前、按时间倒序、limit 截断。
- 单路失败降级(只公告 / 只快讯);两路都失败 → `Error fetching news` 哨兵。
- 名字解析失败 → 只走公告路。
- 窗口前视过滤:`end_date` 之后的条目被丢弃。
- 两路皆空 → `No news found`。

`get_global_news`:
- 三源合并去重;`cctv_news` 按天遍历窗口。
- 窗口计算正确(`look_back_days`);limit 截断。
- 三路全失败 → 错误串。

路由:
- `route_to_vendor("get_news", "600519.SH", ...)` 命中 tushare。
- 非 A 股在 `get_news` 链上从 tushare 降级到下一个源。

## 文档

- `.env.example`:补 `TRADINGAGENTS_TUSHARE_NEWS_FLASH_SOURCES` 说明。
- `CHANGELOG.md`:`feat(dataflows): Tushare 全面接管新闻资讯`。

## 明确不做(YAGNI)

- 不给 `anns_d` 抓取公告 PDF 全文(只给标题 + 链接)。
- 不做快讯的语义/相关性排序(纯关键词 `contains` 过滤)。
- 不改动其它 vendor 或非新闻类路由。
- 不给 `cctv_news` 单独开关(默认参与全局新闻;如需省调用后续再加)。
