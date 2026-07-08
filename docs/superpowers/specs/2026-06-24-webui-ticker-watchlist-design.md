# WebUI 代码清单（Ticker Watchlist）设计

日期：2026-06-24
状态：待实现

## 背景与目标

当前「新分析配置」（`webui/components/ConfigCard.tsx`）用一个多代码 `<textarea>` 输入标的：
用户把多个代码用空格/逗号分隔写在一起，提交后由 `parsedTickers` 解析去重，调用
`enqueueAnalysis(tickers[])` → `POST /api/queue` 批量入队，后端 `QueueScheduler` 串行分析。

用户希望把这个一次性输入框，改造成一个**可长期保存、可编辑、可排序的代码清单**：

- 输入框一次输入一个代码，点「添加」加入清单；
- 清单每行显示**代码 + 名称（公司名）**；
- 可随时添加 / 删除 / 调整顺序；
- 清单**长期保存**，下次打开内容不变，除非手动删改；
- 点「开始分析」时，按清单顺序把所有代码入队，一个一个分析。

## 关键决策（已与用户确认）

1. **名称来源**：后端新增轻量查询接口；前端添加代码时异步带出名称。
2. **共存方式**：替换现有多代码 textarea，改为「单代码输入框 + 持久清单」模式。
3. **查不到名称不阻断**：接口对无效/查不到代码返回 `valid:false, name:null`，前端仍允许添加（名称留空、行内显示代码本身）。
4. **持久化用 localStorage**：换浏览器/设备会丢，可接受（与现有 `ta:` key 模式一致）。
5. **分析后清单保留**：入队后清单不清空、不变。

## 架构

### 后端：名称查询接口

新增 `GET /api/ticker/{code}`，返回：

```json
{ "ticker": "NVDA", "name": "NVIDIA Corporation", "valid": true }
```

- 复用既有 `tradingagents/agents/utils/agent_utils.py::resolve_instrument_identity(ticker)`
  （带 `lru_cache`、fail-open、永不抛异常，返回 `dict`，含 `company_name`）。
- 实现：`name = identity.get("company_name")`；`valid = bool(name)`。
- 路由文件新增 `api/routes/ticker.py`，在 `api/main.py` 按现有 `include_router` 模式注册
  （沿用文件末尾 `# noqa: E402` 的延迟 import + `app.include_router(...)` 写法）。
- **已知降级**：`domestic_china_only` 模式下 `resolve_instrument_identity` 返回 `{}`，
  A 股名称会留空（`valid:false`）。符合「查不到不阻断」约定，本期不为 A 股单独加 AKShare 名称回退。

接口设计为只读、单代码、无副作用，便于独立测试（注入 fake / monkeypatch identity 解析）。

### 前端：改造 ConfigCard.tsx

替换现有 Instrument 区块的多代码 `<textarea>`（当前第 182-189 行）为：

**(a) 单代码输入框 + 添加按钮**
- 一个 `<input>` + 「添加」按钮；回车（Enter）等同点添加。
- 添加流程：trim + 转大写 → 若清单已存在则忽略（去重）→ 先以 `name:""`、`pending:true`
  乐观插入清单 → 调 `lookupTicker(code)` → 返回后回填 `name`、`pending:false`；
  查询失败/无名称则 `pending:false` 且 `name` 留空。
- 输入框添加后清空，焦点保留，便于连续录入。

**(b) 清单（替换 textarea 下方）**
- 数据结构：`TickerItem = { ticker: string; name: string }`，状态 `tickers: TickerItem[]`。
- 每行：左侧「代码 + 名称（或查询中… / 仅代码）」，右侧 ↑ / ↓ / ✕ 三个按钮。
- 排序与移除复用 `QueuePanel.tsx`（第 74-114 行）的交互写法：`move(index, delta)` +
  ChevronUp / ChevronDown / X，**不引入拖拽库**（项目现无 dnd 依赖，保持一致）。
- 空清单时给出占位提示文案。

**(c) 提交**
- `onSubmit` 的 `tickers` 来源从 `parsedTickers` 改为 `tickers.map(t => t.ticker)`（保持清单顺序）。
- 「开始分析」按钮禁用条件中的 `parsedTickers.length === 0` 改为 `tickers.length === 0`。
- 入队链路（`onStart` → `enqueueAnalysis` → `POST /api/queue`）**零改动**，原样复用。

### 前端：API 客户端

`webui/lib/api.ts` 新增：

```ts
export async function lookupTicker(
  code: string,
): Promise<{ ticker: string; name: string | null; valid: boolean }> {
  const r = await fetch(`${BASE}/api/ticker/${encodeURIComponent(code)}`);
  if (!r.ok) return { ticker: code, name: null, valid: false };
  return r.json();
}
```

失败也返回 `valid:false`（不抛），保证前端永远能把代码加入清单。

### 持久化

- localStorage key：`ta:ticker_list`，值为 `TickerItem[]` 的 JSON。
- 沿用现有内联模式（不新建 hook/util 封装层，与现有三个 `ta:` key 风格一致）：
  - 读：挂载时 `useEffect` 读取并 `JSON.parse`（解析失败则回退默认 `[]` 或 `[{ticker:"NVDA",name:""}]`）。
  - 写：每次清单变化（添加 / 删除 / 排序 / 回填名称）后 `localStorage.setItem`。
- 入队后**不修改** localStorage，清单保留。

## 数据流

```
用户输入单代码 → 添加
  → 乐观插入 tickers[] (pending) → 写 localStorage
  → GET /api/ticker/:code → resolve_instrument_identity()
  → 回填 name → 写 localStorage

用户点「开始分析」
  → onStart({ tickers: tickers.map(t=>t.ticker), ...config })
  → enqueueAnalysis() → POST /api/queue
  → QueueScheduler 串行逐个分析（清单不变）
```

## 错误处理

- 名称查询失败 / 超时 / 无名称：静默降级，行内只显示代码，不阻断添加，不弹错。
- localStorage 读取 `JSON.parse` 失败：回退默认清单，不崩溃。
- 重复代码：添加时去重，静默忽略。
- 空清单：提交按钮禁用（沿用现有禁用样式与逻辑）。

## 测试

- **后端**：`tests/webui/` 新增 `test_ticker_lookup`：
  - 路由注册（smoke）。
  - monkeypatch `resolve_instrument_identity` 返回含 `company_name` → 断言 `valid:true` + 正确 name。
  - monkeypatch 返回 `{}` → 断言 `valid:false`、`name:null`，HTTP 200（不报错）。
- **前端**：无单测框架，手动验证清单：
  1. 添加单代码 → 出现行，名称异步补上；
  2. 添加无效代码 → 仍加入、名称留空；
  3. 删除 / 上移 / 下移正常；
  4. 刷新页面 → 清单保留；
  5. 点开始分析 → 队列按清单顺序逐个分析，分析后清单不变。
- 收尾跑 `ruff check .` 与 `pytest -m "not integration"`（用 `.venv/bin/python`）。

## 影响范围 / 改动文件

- 新增：`api/routes/ticker.py`、`tests/webui/test_ticker_lookup.py`
- 修改：`api/main.py`（注册 router）、`webui/lib/api.ts`（`lookupTicker`）、
  `webui/components/ConfigCard.tsx`（输入框 → 单代码 + 清单 + 持久化）
- 文档：`CHANGELOG.md`

## 非目标（YAGNI）

- 不做拖拽排序（用上下按钮）。
- 不做名称的后端持久化 / 跨设备同步（localStorage 足够）。
- 不为 A 股单独加 AKShare 名称回退（本期接受 yfinance 查不到时名称留空）。
- 不保留旧的多代码 textarea 双入口。
