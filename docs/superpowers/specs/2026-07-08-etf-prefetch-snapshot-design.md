# ETF 预取快照(Prefetch Snapshot)设计

- **日期**: 2026-07-08
- **状态**: 设计已确认,待生成实施计划
- **范围**: WebUI 分析流程 + dataflows 取数 + 新增 ETF 详情页

## 1. 问题

分析过程中经常"丢数据",尤其是新闻。根因有两类,且**两类都存在**:

- **A(在线调用失败)**: 分析时实时调 tushare/akshare 拿新闻/行情,遇到限流、超时、
  网络错误,返回 `NO_DATA_AVAILABLE`,分析师带着缺失数据继续。
- **B(LLM 没主动调工具)**: 数据源本身可用,但分析师(ReAct 循环)没决定调
  `get_etf_news`,或调了没用上,导致报告缺失该项。

光把数据"存进 DB"只能兜住 A;B 必须改变**投喂方式**——把关键数据在分析开始时直接
塞进分析师上下文,而不是让它自己决定去 pull。

## 2. 目标

1. 每个 ETF 分析开始前,预取四类数据并落库,分析期间从库读(根治 A)。
2. 关键数据(新闻 + 行情快照)直接 push 进分析师上下文(根治 B)。
3. 新增独立「ETF 详情页」,按交易日查看四类数据快照。

## 3. 非目标(YAGNI)

- ❌ 常驻盘中定时刷新调度器(采用"每次 run 前预取"而非后台轮询)。
- ❌ 快照历史清理/归档策略(先无限留存,量小)。
- ❌ CLI 路径接入预取(这是 WebUI 功能)。
- ❌ 分时做成分析师工具(仅服务预取 + 详情页)。
- ❌ 改动 `route_to_vendor()` 签名或引入通用"快照优先路由"。

## 4. 关键决策(已与用户逐条确认)

| 维度 | 决策 |
|------|------|
| 丢数据根因 | A + B 都有 |
| 预取数据范围 | 四类全要:新闻 / 分时价格 / 技术指标(日线) / 基本面 |
| 刷新时机 | 分析开始前预取一次,不做常驻盘中调度器 |
| 预取粒度 | **C**: 每个 ETF 分析前单独预取(绑定每个队列项) |
| 失败处理 | **B**: 重试带退避,耗尽后标 `missing`("暂缺")并继续分析,不硬阻塞 |
| 投喂方式 | **③ 组合**: 新闻+行情 push 进上下文;细粒度指标/K线走 DB-backed 工具 pull |
| 详情页 | 独立页,四类全可视化,按日期看快照;历史日显示当时快照,当天无数据留空 |
| 整体架构 | **方案 A**: 预取内嵌 runner,快照存 webui.db 新表,不动核心链路 |
| 分时数据源 | tushare SDK `stk_mins`(已验证对 ETF 代码返回整天分钟 OHLCV) |

## 5. 数据模型

快照存进 **webui.db**(不在 startup-cache 清理的 `~/.tradingagents/cache/` 目录内)。
单张通用表,四类各占一行,payload 存 JSON:

```sql
CREATE TABLE IF NOT EXISTS etf_snapshots (
    ticker       TEXT NOT NULL,      -- 如 510300.SS
    trade_date   TEXT NOT NULL,      -- 快照归属交易日 YYYY-MM-DD
    category     TEXT NOT NULL,      -- news | intraday | indicators | fundamentals
    status       TEXT NOT NULL,      -- ok | partial | missing
    payload_json TEXT NOT NULL,      -- 该类数据本体
    fetched_at   TEXT NOT NULL,      -- 预取完成时刻(UTC iso)
    PRIMARY KEY (ticker, trade_date, category)
);
```

**为什么一张表 + JSON**: 四类结构差异大(新闻是列表、分时数百个点、指标/基本面是键值),
统一主键 `(ticker, date, category)` 最贴合"按日期看四类"的诉求;单日分时约 240 点,
JSON 放得下;新增第五类只是多一个 category 值,不改表。

**各 category 的 payload 形态**(示意):

- `news`: `[{title, source, time, url, section}]`,section ∈ fund / index-theme / holdings
- `intraday`: `{trade_date, freq, points:[{t, price, vol}]}`
- `indicators`: `{kline:[{date,o,h,l,c,vol}], ma5, ma20, macd, rsi, ...}`
- `fundamentals`: `{pe, pb, nav, share, ...}`

**status 语义**: 全拿到=`ok`;部分小节失败=`partial`;重试耗尽=`missing`(暂缺,
详情页显示空、分析上下文明确告知不可用)。

**写入时机**: 每次 run 的预取阶段,对该 (ticker, trade_date) 的四行做 upsert;
同一天重复分析**覆盖**为最新快照(不保留多份)。

**读取**: 详情页按 ticker 查 `DISTINCT trade_date` 填日期选择器;选中某天读那天四行;
当天没跑过分析 → 查不到 → 页面留空。

## 6. 预取模块 `prefetch_snapshot`(治根因 A)

新增 `tradingagents/dataflows/prefetch.py`:

```
prefetch_snapshot(ticker, trade_date, store) -> SnapshotSummary
```

流程(四类逐类抓取,互相独立、互不阻塞):

1. 每类调对应现有 dataflows 函数(新闻走 `get_etf_news`;指标/日线走
   `tushare_indicator` / `fund_daily`;基本面走 `tushare_etf_profile`;分时走**新增**
   `get_etf_intraday`,见第 8 节)。
2. **带退避重试**: 每类最多 N 次(默认 3),退避递增(1s/2s/4s)。仅针对疑似
   限流/超时等可恢复错误重试;拿到 `NO_DATA_AVAILABLE`(本就没这项数据)**不算失败、
   不重试**,直接记 `missing`。
3. 每类结果 upsert 进 `etf_snapshots`,带 `status`。
4. 返回 `SnapshotSummary`(各类 status + 用于 push 上下文的摘要)。

关键约束:

- **绝不抛异常** —— 延续项目"dataflows 只返回 sentinel、不 raise"哲学。任何单类失败
  被 `missing` 兜住,预取整体永远"完成",分析照跑。
- **限流友好** —— 四类之间可串行 + 小间隔(复用 `tushare_etf_news` 已有限流逻辑),
  避免预取自己把自己打限流。
- **可配置** —— 重试次数/退避间隔放 `DEFAULT_CONFIG`,走 `TRADINGAGENTS_*` 可覆盖,
  默认保守。

产出两样: ①落库四行快照(供详情页 + DB-backed 工具);②`SnapshotSummary`(供 push)。

## 7. runner 集成 + 投喂机制(治根因 B)

### 7a. runner 预取步骤

`api/runner.py` 中,每个队列项在构建/运行 graph **之前**插入:

```
summary = prefetch_snapshot(ticker, trade_date, store)   # 落库四类快照
initial_state["prefetched"] = summary.for_context()       # 摘要塞进初始 state
```

预取进度/耗时经现有 SSE 通道推给前端("正在预取 510300 的新闻/分时/指标/基本面…")。

### 7b. push 路径 —— 新闻 + 行情快照直接进上下文(根治 B)

- graph 初始 state 增加字段 `prefetched`(state TypedDict 加,承载新闻摘要 + 行情快照 +
  各类 status)。
- **新闻分析师、市场分析师** 的 prompt 组装处,把新闻摘要 / 当前行情快照**直接拼进
  首条消息**,不依赖 LLM 主动调工具。
- `missing` 项明确写成"⚠️ 此项数据本次预取暂缺,不可用",分析师照实报缺失、不编造
  (延续 anti-hallucination 原则)。

### 7c. pull 路径 —— 细粒度工具改读快照 DB(治 A 其余部分)

- `get_etf_news` 及指标/日线/基本面相关工具:分析期间**优先从 `etf_snapshots` 读**当前
  (ticker, date) 快照;存在就直接返回,不打在线 API;不存在才回落在线兜底。
- 工具如何知道"当前 ticker/date":通过已有 config 单例 / 运行上下文传入,**不改
  `route_to_vendor` 签名**,只在这几个 ETF 相关工具函数内部加一层"先查快照"短路。

**为什么 push + pull 都要**: push 保证"绝不能丢"的新闻+行情一定在上下文里(治 B);
pull 让指标/历史 K 线这类量大数据按需取、又不打在线(治 A 且不撑爆 token)。

## 8. 新增 ETF 分时取数能力

现有 dataflows 只有日线,无分钟级,这是唯一净新增取数能力。

- 新增 `get_etf_intraday(symbol, trade_date, freq="5min")`,底层调 **tushare SDK
  `stk_mins`**(已验证 ETF 代码通用),放进 `tushare_stock.py`(或新
  `tushare_intraday.py`)。
- 返回当日分钟 OHLCV 点列;分时线用每根 bar 的 `close`。`freq` 默认 5min(约 48 点/天),
  可配 1min(约 240 点)。
- 按约定**注册进 `VENDOR_METHODS`**,`.SS`/`.SZ` 的 ETF 走 tushare;拿不到返回
  `NO_DATA_AVAILABLE` sentinel。
- **仅服务预取 + 详情页**,不做成分析师工具(行情快照已通过 push 进上下文)。

**风险 —— tushare 积分权限**: `stk_mins` 分钟接口通常要较高积分(5000+)。若 App 的
`TUSHARE_TOKEN` 无分钟权限 → 按第 6 节记 `missing`、详情页留空、上下文标注暂缺,
不崩、不阻塞。**实施第一步**: 用 App 的 token 实测 `stk_mins` 能否稳定拿数。

**放弃的备选**: akshare(不稳)、TDX(`tdx.py` 是占位符,本工作区仅 MCP、App 运行时
无 pytdx 依赖)、longbridge(CLI 封装只有 news+quote 快照、无分钟,且有已知 bug)。

## 9. ETF 详情页

### 9a. 后端 API(`api/routes/` 新增,如 `snapshots.py`)

- `GET /api/etf/{ticker}/dates` → 该 ETF 有快照的交易日列表(填日期选择器)。
- `GET /api/etf/{ticker}/snapshot?date=YYYY-MM-DD` → 那天四类 payload + 各自 status;
  `missing` 类返回空 + 标记。
- 纯读 `etf_snapshots`,**不触发抓取**。

### 9b. 前端(`webui/`,Next.js 16 / React 19)

- watchlist 每个 ETF 可点进独立详情页(新路由 `/etf/[ticker]`)。
- 顶部日期选择器,默认最近一个有快照的日;选到无数据日 → 各块留空。
- 四区块可视化: ①分时价格折线图 ②新闻列表(标题/来源/时间/小节/原文链接)
  ③技术指标(近 N 日 K 线 + MA/MACD/RSI)④基本面(PE/PB/净值/份额键值卡片)。
- 每块独立处理 `missing`("本次预取暂缺"),互不影响。
- **实施约束**: 动 `webui/` 前先读 `webui/node_modules/next/dist/docs/` 和
  `webui/AGENTS.md`(Next.js 16 破坏性差异);图表库沿用现有依赖,不新引入。

## 10. 与现有机制的关系

- **startup-cache 清理**: 互不干扰。清的是 `~/.tradingagents/cache/` 里的 endpoint
  缓存文件;快照存 `~/.tradingagents/webui.db`,不在清理范围。二者定位不同——前者保证
  在线取数新鲜,后者是"按日期归档的分析快照"。

## 11. 测试(遵循 `pytest -m "not integration"`,无 key 可跑)

- 单元: `prefetch_snapshot` 的重试/退避/`missing` 标记(mock dataflows,不打网络);
  `etf_snapshots` upsert/覆盖;两个详情页 API 的读取 + 空快照返回。
- push 投喂: 验证 `prefetched` 摘要正确拼进新闻/市场分析师首条消息,`missing` 项带标注。
- 冒烟: 新路由注册(仿 `tests/webui/test_smoke.py`)。
- 分时联调: `get_etf_intraday` 真实拉数标 `integration`(需真 token,自动跳过)。

## 12. 影响的文件(预估)

- 新增: `tradingagents/dataflows/prefetch.py`、`api/routes/snapshots.py`、
  `webui/` 详情页路由与组件、分时取数(`tushare_stock.py` 或新 `tushare_intraday.py`)。
- 改动: `api/store.py`(新表 + 读写方法)、`api/runner.py`(预取步骤 + push)、
  `api/main.py`(注册路由)、`tradingagents/dataflows/interface.py`(`VENDOR_METHODS`
  注册 `get_etf_intraday`)、新闻/市场分析师 prompt 组装、相关 state TypedDict、
  ETF 相关工具函数(加快照短路)、`default_config.py`(重试/退避配置)。
