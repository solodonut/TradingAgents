# ETF 数据端点诊断页 — 设计文档

- 日期:2026-07-13
- 状态:已确认(待实现)

## 1. 目标与背景

给定一个 ETF 代码,逐格测试**所有数据源方法**(`VENDOR_METHODS` 矩阵),精确监控每个
`(方法, vendor)` 组合是否能返回值。无返回时,把原因归入三类:

1. **输入条件不对** — 代码/日期/参数导致查不到数据(空结果、标的不覆盖、数据过期)。
2. **服务不可用** — 上游宕机、网络不可达、被限流。
3. **无权限** — 缺 API key/token、积分不足、付费档位不够。

除状态外,页面还要能看到**每格的实际返回全文**(或错误详情),供人工核对与三分类的兜底判断。

### 为什么绕过 `route_to_vendor`

生产路由 `route_to_vendor(method, ...)` 只尝试**已配置**的 vendor,且**首个成功即停**。
诊断工具的目的恰恰相反:要单独测试每一个 `(method, vendor)` 格子,包括未配置的、会失败的。
因此诊断层**刻意绕过** `route_to_vendor`,直接调用 `VENDOR_METHODS[method][vendor]`。
这是本设计里对 AGENTS.md「数据访问一律走 `route_to_vendor`」约定的**唯一、经用户批准的例外**;
诊断层**只读**,不写 checkpoint、不碰单跑锁、不改全局 config。

## 2. 分类规则(四态)

| 状态 | UI | 判定来源 |
|---|---|---|
| `ok` | ✅ 成功 | 实现函数返回正常内容(非 sentinel、非错误前缀) |
| `no_data` | ⚠️ 无数据·输入不对 | 抛 `NoMarketDataError`,或返回以 `NO_DATA_AVAILABLE:` 开头的字符串,或 `get_news` 的 `Error fetching news` 前缀 |
| `no_perm` | 🔒 无权限 | 抛 `VendorNotConfiguredError`,或返回文本命中 `PERMISSION_HINTS` 关键词 |
| `unavailable` | ❌ 不可用 | 抛 `VendorRateLimitError`、命中 `_NETWORK_ERRORS`,或返回以 `DATA_SOURCE_UNAVAILABLE:` 开头的字符串 |

判定优先级(自上而下,先命中先定):

1. 异常类型:`VendorNotConfiguredError` → `no_perm`;`VendorRateLimitError` → `unavailable`;
   `NoMarketDataError` → `no_data`;`_NETWORK_ERRORS`(`requests` 的 Connection/Proxy/Timeout/ChunkedEncoding)
   → `unavailable`;其它异常 → `unavailable`(捕获后归为不可用,并保留 `repr(e)` 全文)。
2. 若函数**未抛异常**而返回字符串,按前缀/关键词判定:
   - `NO_DATA_AVAILABLE:` → `no_data`
   - `DATA_SOURCE_UNAVAILABLE:` / `DATA_SOURCE_DISABLED:` → `unavailable`
   - 命中 `PERMISSION_HINTS` → `no_perm`
   - `Error fetching news`(get_news 专用哨兵)→ `no_data`
   - 否则 → `ok`

### `PERMISSION_HINTS`(无权限关键词表)

缺 key 通常抛 `VendorNotConfiguredError`(已由异常路径处理),但**积分/付费档**类问题往往由 vendor
以普通错误文本返回,无法靠异常识别。用一张小关键词表做启发式匹配(大小写不敏感),命中即 `no_perm`:

```
积分不足, 权限不足, 没有权限, 抱歉,您没有,      # tushare 中文提示
premium, subscription, api key, apikey,        # Alpha Vantage / 通用
rate limit exceeded for your plan,
unauthorized, forbidden, 401, 403,
token 无效, invalid token, 请开通
```

关键词表**不是权威判定**,只是把「像权限问题」的格子高亮出来;**任何情况下都完整保留原始返回全文**,
让人工在展开视图里最终确认。表内容随实测补充,集中在 `diagnostics.py` 顶部一处维护。

## 3. 后端模块 `tradingagents/dataflows/diagnostics.py`

只读、无副作用。核心数据结构与函数:

### `CellResult`(dataclass)

```
method: str            # e.g. "get_etf_profile"
vendor: str            # e.g. "tushare"
category: str          # get_category_for_method(method) 的结果
status: str            # ok | no_data | no_perm | unavailable
elapsed_ms: float
raw: str               # 返回全文或 repr(exception)(截断上限见下)
error_type: str | None # 异常类名(若抛异常),否则 None
```

`raw` 截断上限 8000 字符(超出加 `… (truncated)` 后缀),避免超大表格/长新闻把 SSE 撑爆。

### `METHOD_PROBES`(参数构造表)

各方法签名不一,用一张固定的 lambda 表把 `(code, ref_date)` 映射成每个方法的实参。分三类:

| 方法 | 参数(由 code, ref_date 构造) | UI 分区 |
|---|---|---|
| `get_stock_data` | `(code, start, ref_date)` | ETF 核心 |
| `get_indicators` | `(code, "close_50_sma", ref_date, 30)` | ETF 核心 |
| `get_etf_profile` | `(code, ref_date)` | ETF 核心 |
| `get_etf_intraday` | 按源码实测签名填 | ETF 核心 |
| `get_etf_news` | `(code, start, ref_date)` | ETF 核心 |
| `get_news` | `(code, start, ref_date)` | ETF 核心 |
| `get_fundamentals` | `(code, ref_date)` | 股票基本面 |
| `get_balance_sheet` | `(code, "annual", ref_date)` | 股票基本面 |
| `get_cashflow` | `(code, "annual", ref_date)` | 股票基本面 |
| `get_income_statement` | `(code, "annual", ref_date)` | 股票基本面 |
| `get_insider_transactions` | `(code,)` | 股票基本面 |
| `get_global_news` | `(ref_date, 7, 20)` | 参考·与 ETF 无关 |
| `get_macro_indicators` | `("CPI", ref_date, 90)` | 参考·与 ETF 无关 |
| `get_prediction_markets` | `("stock market", 10)` | 参考·与 ETF 无关 |

`start` = `ref_date` 往前 30 天。`get_etf_intraday` 的确切签名在实现时读源码确认,不臆测。
非 symbol 类方法(global_news/macro/prediction)用固定参数,**不注入 ETF code**,归入独立分区。

### 函数

- `probe_cell(method, vendor, code, ref_date) -> CellResult`
  取 `VENDOR_METHODS[method][vendor]`,用 `METHOD_PROBES[method]` 构造实参,计时调用,
  按第 2 节规则判定 `status`,组装 `CellResult`。异常全部捕获,绝不外抛(呼应「never raises」)。
- `iter_probes(code, ref_date) -> Iterator[CellResult]`
  遍历 `VENDOR_METHODS` 所有 `(method, vendor)`,**串行** yield 每个 `probe_cell` 结果。
  串行是刻意的:多源并发会触发限流、且难以逐格计时;诊断是低频人工操作,不需要并发。
- `count_probes() -> int`
  返回格子总数,供前端 `start` 事件预铺骨架。

## 4. SSE 协议与 API 路由 `api/routes/diagnostics.py`

`GET /api/diagnostics/etf/{code}?ref_date=YYYY-MM-DD`(ref_date 可选,缺省今天),
用 `sse_starlette.EventSourceResponse`(与 `cache.py`/`health.py` 一致)。
**不经过单跑锁 / 队列**,分析进行中也能跑(只读)。

事件序列:

- `start` — `{ "total": <int>, "code": <str>, "ref_date": <str> }`,前端据 `total` 预铺 pending 骨架。
- `cell`(N 次)— 一个 `CellResult` 的 JSON,`{method, vendor, category, status, elapsed_ms, raw, error_type}`。
- `done` — `{ "ok": n1, "no_data": n2, "no_perm": n3, "unavailable": n4, "elapsed_ms": <总耗时> }`。
- `error` — 仅在诊断框架自身异常时发(如 code 为空);正常的 vendor 失败走 `cell` 的状态,不走 `error`。

生成器逐个消费 `iter_probes`,每格发一个 `cell`;客户端断开(`await request.is_disconnected()`)时停止,
不再无谓调用后续数据源。路由在 `api/main.py` 用 `app.include_router` 注册。

## 5. 前端页面 `webui/app/etf/diagnostics/page.tsx`

复用现有 glass 风格与 `lib/api` SSE 消费模式(Next.js 16 / React 19 / Tailwind 4;
动代码前先读 `webui/node_modules/next/dist/docs/`)。

**布局**
- 顶部:ETF 代码输入框 + 参考日期选择器(默认今天)+「测试」按钮。跑动时按钮变
  「测试中… (12/38)」,提供「停止」(关闭 EventSource)。
- 汇总条:`✅3  ⚠️5  🔒2  ❌1 · 用时 48.2s`,四个数字用对应色(来自 `done` 事件)。
- 按 group 分区(ETF 核心 / 股票基本面 / 参考·与 ETF 无关),每区一张表:
  - 行 = 方法,列 = 该方法下各 vendor。
  - 每格:状态徽标(✅/⚠️/🔒/❌)+ `elapsed_ms`;点击展开看**原始返回全文或错误详情 + 实参 + 函数名**。
  - 开跑先按 `start.total` 铺灰色 `pending` 骨架;`cell` 事件到达后原地变色回填。

**状态色**(不与项目红涨绿跌语义冲突):✅=绿 `#6affb0`;⚠️=黄 `#ffcf70`;🔒=蓝/紫;❌=红 `#ff6b6b`。

**API 封装**:`lib/api.ts` 加 `openEtfDiagnostics(code, refDate, handlers)`,封装 `EventSource`,
把 `start/cell/done/error` 回调出去;类型加到 `lib/types.ts`。

**导航**:在 `/etf/[ticker]` 快照页或主导航加入口链接到诊断页。

## 6. 测试

**后端单元** `tests/dataflows/test_diagnostics.py`(mock `VENDOR_METHODS` 实现函数,不联网、不需 key):
- `probe_cell` 四态各一例:正常返回→`ok`;抛 `NoMarketDataError`/返回 `NO_DATA_AVAILABLE:`→`no_data`;
  抛 `VendorNotConfiguredError`/文本命中 `PERMISSION_HINTS`→`no_perm`;
  抛 `VendorRateLimitError`/`_NETWORK_ERRORS`/返回 `DATA_SOURCE_UNAVAILABLE:`→`unavailable`。
- `iter_probes`:遍历所有格子;非 symbol 方法用固定参数、不注入 code;`elapsed_ms` 有值。
- 断言只读:`probe_cell` 不写 checkpoint、不碰单跑锁、不改全局 config。

**API smoke** 追加到 `tests/webui/test_smoke.py`:诊断路由已注册(路径在 `app.routes` 中)、
SSE 响应头 `text/event-stream`;用 `app.state` 注入假 probe 生成器,断言 `start`→`cell`×N→`done`
事件序列结构,不跑真实数据源。

**前端**:无自动化测试(webui 现状),手动开页面点一次验证。

**收尾**:`.venv/bin/ruff check .` + `.venv/bin/python -m pytest -m "not integration"` 全绿。

## 7. 范围外(YAGNI)

- 不做历史留存/趋势图:诊断是即时人工操作,不入库。
- 不做并发探测:串行足够,且避开限流。
- 不做告警/定时轮询:与现有服务健康页(`/api/health`)职责区分,本页是人工按需深检。
- 不改 `route_to_vendor` 及生产数据路径。
