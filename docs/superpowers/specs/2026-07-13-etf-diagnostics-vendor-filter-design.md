# ETF 诊断页:供应商多选 + 选择持久化 + 功能说明

**日期**:2026-07-13
**状态**:设计已定稿,待实现
**关联**:[2026-07-13-etf-endpoint-diagnostics-design.md](2026-07-13-etf-endpoint-diagnostics-design.md)(原始诊断页)

## 背景

现有 ETF 端点诊断页(`/etf/diagnostics`)会**串行**遍历 `VENDOR_METHODS` 里全部
`(method, vendor)` 格子并逐格发起**真实网络请求**,通过 SSE 流式返回四态结果。当前无法只
测部分供应商,页面也没有对每个功能的说明,同一功能的多个供应商在组内平铺、功能名重复出现。

## 目标

1. **供应商多选**:用户勾选要测试哪些供应商,未选中的**后端直接跳过、不发请求**(省时、避免限流)。
2. **持久化上次选择**:下次打开页面自动恢复上次勾选的供应商。
3. **每个功能一句说明**:14 个方法各配一句中文说明,显眼展示。

## 非目标(YAGNI)

- 不做「按 method 过滤」(只做按 vendor 过滤)。
- 不持久化 code / ref_date(只持久化供应商选择)。
- 不做 vendor 级别的逐一说明(只做 method 级)。

## 设计

### 决策 A:元数据由后端提供(单一数据源)

供应商名单和方法说明都从 `tradingagents/dataflows/diagnostics.py` 派生,与
`METHOD_GROUP` / `METHOD_PROBES` 放在一起,新增 `METHOD_DESC` 映射。前端首屏 fetch 一次,
避免硬编码漂移(与仓库既有「单一注册表」约定 `VENDOR_METHODS`/`MODEL_OPTIONS` 一致)。

新增只读端点 `GET /api/diagnostics/etf/meta`:

```json
{
  "vendors": ["akshare", "alpha_vantage", "eastmoney", "fred",
              "longbridge", "polymarket", "tdx", "tushare", "yfinance"],
  "methods": [
    { "name": "get_stock_data", "group": "ETF 核心", "desc": "日线 OHLCV 历史行情" }
  ]
}
```

- `vendors`:遍历 `VENDOR_METHODS` 聚合去重后排序。
- `methods`:遍历 `METHOD_GROUP`,附 `METHOD_DESC[name]`。

`METHOD_DESC`(14 条,一句话):

| method | desc |
| --- | --- |
| get_stock_data | 日线 OHLCV 历史行情 |
| get_indicators | 技术指标(如 close_50_sma) |
| get_etf_profile | ETF 基本档案(规模 / 费率 / 跟踪指数) |
| get_etf_intraday | ETF 分时行情(默认 5min) |
| get_etf_news | ETF 相关新闻 |
| get_news | 标的相关新闻 |
| get_fundamentals | 基本面概况 |
| get_balance_sheet | 资产负债表(年报) |
| get_cashflow | 现金流量表(年报) |
| get_income_statement | 利润表(年报) |
| get_insider_transactions | 内部人交易 |
| get_global_news | 全球宏观新闻 |
| get_macro_indicators | 宏观经济指标(如 CPI) |
| get_prediction_markets | 预测市场行情(Polymarket) |

### 决策 B:后端按供应商过滤(跳过不请求)

- `iter_probes(code, ref_date, vendors: set[str] | None = None)`:`vendors=None` 跑全部;
  给定集合则 `if vendor not in vendors: continue`。
- `count_probes(vendors: set[str] | None = None)`:只计选中的格子(进度条 total 准确)。
- SSE 路由 `stream_etf_diagnostics` 新增 `vendors: str | None = Query(None)` 查询参数,
  逗号分隔解析为集合;空 / 缺省 = 全选(传 `None`)。空字符串也按全选处理。
- 未知供应商名(不在 `VENDOR_METHODS` 里的)静默忽略,不报错。

### 决策 C:前端改动

**输入区新增供应商勾选框行** [webui/app/etf/diagnostics/page.tsx](../../../webui/app/etf/diagnostics/page.tsx)

- 首屏 `fetch(/api/diagnostics/etf/meta)` 拿 `vendors` + `methods`。
- 一排 checkbox(默认全选),含「全选 / 清空」两个快捷按钮。
- 至少选 1 个才能点「测试」(全不选时禁用,提示需选择)。

**localStorage 持久化**

- key:`etf-diag-vendors`,存 JSON 字符串数组。
- 首屏:读 localStorage,与 meta 返回的 `vendors` 取**交集**(过滤已下线的供应商);
  无记录时默认全选。
- 选择变化即写入。

**发起请求**:`etfDiagnosticsStreamUrl` / `subscribeEtfDiagnostics` 新增 `vendors: string[]`
参数,拼进 URL 的 `?vendors=` (逗号分隔)。全选时可省略参数。

**说明展示:组内按 method 二级分组**

当前组内是 `method+vendor` 扁平行。改为:组内先按 method 分组,method 作小标题
(`method — desc`),其下缩进列出各 vendor 的状态行(图标 / vendor / 耗时,点击展开 raw)。
方法名只出现一次,说明有归属。method 的排序按 `methods` 元数据顺序;vendor 行按到达顺序。

`DiagnosticCell` 已含 `method` / `group`,分组在前端完成,不改 SSE cell 结构。

### 数据流

```
页面加载 → GET /meta → 渲染勾选框(localStorage∩vendors)+ 缓存 methods 说明
点「测试」→ SSE /etf/{code}?vendors=a,b → start/cell/done
         → 前端按 group→method 二级分组渲染,method 挂 desc
勾选变化 → 写 localStorage
```

## 错误处理

- `/meta` fetch 失败:显示错误提示,勾选框区退化为空(无法选择则「测试」禁用)。不阻塞页面其余部分。
- `vendors` 参数含未知名:后端忽略。
- 全不选:前端禁用「测试」,不发请求。

## 测试

后端 [tests/dataflows/test_diagnostics.py](../../../tests/dataflows/test_diagnostics.py):
- `count_probes(vendors={...})` 只计选中格子;`vendors=None` 等于全部。
- `iter_probes(..., vendors={...})` 只产出选中供应商的 cell;空集合产出 0 个。
- `METHOD_DESC` 覆盖 `METHOD_GROUP` 全部 key 且非空(防漏写)。

路由测试(用 `app.state` 注入 fake,遵循现有模式):
- meta 端点返回 vendors 非空、methods 每项有 desc。
- `?vendors=` 参数被解析并透传给 `count`/`iter`(断言收到的集合)。

前端:localStorage 持久化为纯 UI,不强制测试;若已有 page 测试则补勾选交互。

## 影响面

- 后端:`tradingagents/dataflows/diagnostics.py`(+`METHOD_DESC`、`iter_probes`/`count_probes`
  加 `vendors` 参数、+ meta 数据构造函数)、`api/routes/diagnostics.py`(+meta 端点、
  SSE 加 `vendors` 参数)。
- 前端:`webui/app/etf/diagnostics/page.tsx`、`webui/lib/api.ts`、`webui/lib/types.ts`(+meta 类型)。
- 文档:`CHANGELOG.md`。

## 向后兼容

- SSE 端点不带 `vendors` 时行为不变(全跑)。
- cell / start / done 事件结构不变。
