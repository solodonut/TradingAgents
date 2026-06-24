# TradingAgents A 股支持（AKShare 集成）

本文档说明如何在 TradingAgents 中分析中国 A 股（沪深京）。A 股数据通过新增的
**AKShare** vendor 提供，覆盖行情、技术指标、财务报表和公司新闻，全部免费、无需 token。

> 本功能为研究用途，非投资建议。

---

## 1. 快速开始

A 股 + IBM ICA 模型 + 中文报告，一步到位：

```python
import os
from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.default_config import DEFAULT_CONFIG

os.environ["IBM_ICA_API_KEY"] = "<你的 ICA key>"   # 或写进 .env / 提前 export

config = DEFAULT_CONFIG.copy()
config["llm_provider"]    = "ibm_ica"
config["deep_think_llm"]  = "claude-opus-4-8"      # 深度推理
config["quick_think_llm"] = "claude-haiku-4-5"     # 快速任务
config["output_language"] = "Chinese"              # 报告输出中文

ta = TradingAgentsGraph(config=config)
_, decision = ta.propagate("600519", "2024-12-31")  # 贵州茅台
print(decision)
```

CLI 同样可用：运行后在菜单选 **IBM ICA** provider、选 Claude 模型、语言选 **Chinese (中文)**，ticker 处输入 A 股代码即可：

```bash
tradingagents                 # 安装后的命令
python -m cli.main            # 或从源码运行
```

---

## 2. 支持的代码格式

输入以下任一形式都会被识别为同一只 A 股，系统自动推断交易所：

| 输入形式 | 示例 | 说明 |
|---|---|---|
| 纯 6 位代码 | `600519` | 最简形式，自动判断沪/深/京 |
| Yahoo 后缀 | `600519.SS` / `000001.SZ` | 与原框架基准（benchmark）兼容 |
| 券商前缀 | `sh600519` / `sz000001` | 大小写均可 |

交易所自动推断规则（按代码前缀）：

| 交易所 | 代码前缀 | 示例 |
|---|---|---|
| 上交所 SH（`.SS`） | `60`（主板）、`68`（科创板）、`5x/9x` | `600519`、`688981` |
| 深交所 SZ（`.SZ`） | `00`（主板）、`30`（创业板）、`1x/2x` | `000001`、`300750` |
| 北交所 BJ（`.BJ`） | `43`、`83`、`87`、`88`、`92` | `430047` |

美股（`AAPL`）、港股（`0700.HK`）、加密货币（`BTC-USD`）等**不会**被识别为 A 股，
继续走原有的 Yahoo / Alpha Vantage 路径。

---

## 3. 数据来源

| 数据类别 | AKShare 接口 | 内容 |
|---|---|---|
| 行情 OHLCV | `stock_zh_a_hist`（前复权 qfq） | 日线开高低收、成交量、成交额 |
| 技术指标 | 同上 + `stockstats` | SMA/EMA/MACD/RSI/BOLL/ATR/VWMA/MFI |
| 资产负债表 | `stock_balance_sheet_by_report_em` | 全科目，历史回溯至上市初期 |
| 利润表 | `stock_profit_sheet_by_report_em` | 营收、利润、各项费用 |
| 现金流量表 | `stock_cash_flow_sheet_by_report_em` | 经营/投资/筹资现金流 |
| 财务指标概况 | `stock_financial_analysis_indicator` | 每股收益、ROE、利润率、周转率等 |
| 公司新闻 | `stock_news_em` | 个股中文新闻（标题/内容/来源/链接） |

所有财报数据均带**防未来数据泄露（look-ahead）过滤**：传入 `curr_date` 后，
晚于该日期的报告期会被剔除，保证回测不会看到当时尚未公布的财报。

---

## 4. 自动路由

默认开启（`akshare_auto_route = True`）。当请求的 ticker 是 A 股时，price /
indicator / fundamental / news 调用会**优先**走 AKShare，无论 `data_vendors`
怎么配；非 A 股 ticker 不受影响。原有 vendor 仍作为回退链保留。

关闭自动路由（让所有市场都遵循 `data_vendors` 配置）：

```python
config = DEFAULT_CONFIG.copy()
config["akshare_auto_route"] = False
```

也可把 AKShare 设为某类数据的默认 vendor：

```python
config["data_vendors"]["fundamental_data"] = "akshare"
config["data_vendors"]["core_stock_apis"] = "akshare"
config["data_vendors"]["technical_indicators"] = "akshare"
# news_data 也支持 "akshare"
```

---

## 5. 代理（Proxy）注意事项

AKShare 抓取的是国内公开源（东方财富、新浪等）。如果你的环境设置了**企业/科学上网
代理**（`HTTP_PROXY` / `HTTPS_PROXY` / 系统级代理），这些代理通常**无法连接国内站点**。

本集成已自动处理：每次 AKShare 取数时，在 `no_proxy_session()` 内临时将
`requests.Session.trust_env` 设为 `False` 并清除代理环境变量，使请求直连国内源；
取数结束后立即恢复，**不影响 LLM API 调用走代理**。

> macOS 上仅清除环境变量不够（系统级代理仍生效），因此采用 `trust_env=False` 方案。

如果你处在**纯国内网络**且不需要代理访问 LLM，则无需任何额外配置。

---

## 6. 重试与缓存

- **重试**：东方财富接口偶发断连（`RemoteDisconnected`）。`ak_retry()` 对网络类
  异常做指数退避重试（1.5s → 3s → 6s，共 3 次），非网络异常（错误代码、解析失败）
  立即抛出，不浪费时间。
- **缓存**：结果按 symbol 缓存到磁盘（`~/.tradingagents/cache/akshare/`，或
  `TRADINGAGENTS_CACHE_DIR` 指定的目录），TTL 分级：
  - 行情：6 小时
  - 财报/财务指标：24 小时
  - 新闻：1 小时

  缓存可跨进程复用，重复运行同一标的几乎瞬时返回。只缓存成功结果，失败不会污染缓存。

---

## 7. alpha 基准（benchmark）

A 股的 alpha 计算基准已内置于 `default_config.py` 的 `benchmark_map`：

| 后缀 | 基准 | 指数 |
|---|---|---|
| `.SS` | `000001.SS` | 上证综指 |
| `.SZ` | `399001.SZ` | 深证成指 |

基准指数数据仍通过 Yahoo 获取（指数代码非个股，不走 AKShare）。

---

## 8. 涉及的文件

新增：

- `tradingagents/dataflows/akshare_utils.py` — 代码归一化、A 股识别、代理绕过、重试、缓存
- `tradingagents/dataflows/akshare_stock.py` — 行情
- `tradingagents/dataflows/akshare_indicator.py` — 技术指标
- `tradingagents/dataflows/akshare_fundamentals.py` — 三大报表 + 财务指标
- `tradingagents/dataflows/akshare_news.py` — 个股新闻

修改：

- `tradingagents/dataflows/interface.py` — 注册 akshare vendor + 自动路由
- `tradingagents/default_config.py` — `akshare_auto_route` 开关 + vendor 选项说明
- `tradingagents/llm_clients/anthropic_client.py` — ICA Anthropic Messages 客户端
- `tradingagents/llm_clients/factory.py` — 注册 `ibm_ica` 原生协议 provider
- `tradingagents/llm_clients/api_key_env.py` — `ibm_ica` → `IBM_ICA_API_KEY`
- `tradingagents/llm_clients/model_catalog.py` — ICA 模型列表
- `tradingagents/llm_clients/validators.py` — `ibm_ica` 接受任意模型名
- `cli/utils.py` — CLI provider 菜单加入 IBM ICA

依赖：`akshare`（已加入环境，安装：`pip install akshare`）。

---

## 9. LLM 用 IBM ICA

ICA 使用 Anthropic Messages API，并以命名 provider `ibm_ica` 接入统一 LLM 工厂。

| 配置项 | 值 |
|---|---|
| `llm_provider` | `ibm_ica` |
| baseURL（默认，内置） | `https://api.nextgen-beta.ica.ibm.com/ica` |
| 最终推理 URL | `.../ica/v1/messages` |
| API key 环境变量 | `IBM_ICA_API_KEY`（通过 `x-api-key` 发送） |
| baseURL 覆盖（可选） | `IBM_ICA_BASE_URL` |

### 当前启用的模型（默认配置）

`default_config.py` 默认启用以下两个模型：

| 角色 | 模型 ID | 描述 |
|---|---|---|
| **深思考** `deep_think_llm` | `claude-opus-4-8` | Claude 4.8 Opus，用于 Research Manager 和 Portfolio Manager |
| **快思考** `quick_think_llm` | `claude-haiku-4-5` | Claude 4.5 Haiku，用于四类分析师、Bull/Bear Researcher、Trader、三类风险分析师、反思和 Chat |

完整的 Provider 矩阵、Agent 模型分配、Chat/视觉/导出调用链、健康检查成本和 ICA 请求细节见 [LLM API 架构与调用参考](docs/llm-api-architecture.md)。

> ICA 走 Anthropic Messages API。LangChain/Anthropic SDK 会在 Base URL 后追加 `/v1/messages`，并使用标准 Anthropic tool use 支撑 Agent 的 ReAct 循环。

### 可选模型（实测可用）

- **深度推理**：`claude-opus-4-8`、`claude-opus-4-7`、`claude-sonnet-4-6`
- **快速任务**：`claude-haiku-4-5`、`claude-sonnet-4-6`
- 新发布或租户专用的 Claude 模型可在 CLI 选 “Custom model ID” 手填

> 注意：模型名是**裸名**（`claude-opus-4-8`），不带 opencode 的 `ibm_ica/` 前缀。

> ICA 走公司网络/代理可达——与 AKShare（国内源、需绕过代理）相反。两者互不干扰：
> AKShare 取数时临时绕过代理，LLM 调用仍正常走代理。

设置 key：

```bash
export IBM_ICA_API_KEY="<你的 ICA key>"
# 或写进项目根目录的 .env
```

---

## 10. 中文报告输出

设 `config["output_language"] = "Chinese"`（或环境变量 `TRADINGAGENTS_OUTPUT_LANGUAGE=Chinese`）。
全部 12 个产出报告的 agent（分析师、研究员辩论、交易员、风控、组合经理最终决策）
都会用中文输出，有回归测试保证不漏。

```python
config["output_language"] = "Chinese"
```

唯一例外：`reflection.py` 的复盘记忆（写入 `~/.tradingagents/memory/trading_memory.md`
并注入下次同标的运行）仍是英文短句，但不影响组合经理本身的中文决策输出。如需该部分也中文，
可在 `tradingagents/graph/reflection.py` 的 `_get_log_reflection_prompt()` 末尾追加
`get_language_instruction()`。

---

## 11. 已知限制

- 个股新闻 `stock_news_em` 仅返回最近一段时间的条目，深度历史回测时早期窗口可能无新闻。
- 行情 kline 接口（`push2his.eastmoney.com`）偶有区域性限流；重试会缓解，
  若持续失败请检查网络对国内站点的连通性。
- 财务指标概况以东财「主要财务指标」为准，字段为中文列名。
- `reflection.py` 复盘记忆为英文（见上节）。
