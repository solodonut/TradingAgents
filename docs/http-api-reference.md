# HTTP API 参考(WebUI 后端)

WebUI 后端从 [api/main.py](../api/main.py) 挂载,路由定义在 [api/routes/](../api/routes/)。
本文只覆盖对外的 FastAPI HTTP 接口;**Agent 侧的数据获取方法**(`get_stock_data`
等)不是 HTTP 接口,见 [data-fetching-apis.md](./data-fetching-apis.md)。

> 单用户后端,但队列可并行:同一时刻最多跑 `max_parallel_runs` 个分析(默认 2,可在
> WebUI 队列面板下拉框或 `PUT /api/queue/parallelism` 改,1–4)。忙时不返回 409,而是入队
> (见 [api/scheduler.py](../api/scheduler.py))。CORS 只放行 `localhost:3000`。

## 运行时 HTTP 路由

| Method | Path | 用途 |
| --- | --- | --- |
| `GET` | `/api/config/options` | 返回可选的 model/provider/config 选项。 |
| `POST` | `/api/analysis` | 入队单个分析并启动调度器。 |
| `POST` | `/api/analysis/{run_id}/cancel` | 取消正在运行的分析。 |
| `GET` | `/api/analysis/{run_id}/status` | 返回 DB 状态 + 实时 LLM 遥测。 |
| `GET` | `/api/analysis/{run_id}/stream` | 通过 SSE 流式推送分析事件。 |
| `GET` | `/api/analysis/{run_id}/report` | 下载已完成的运行为 Markdown。 |
| `POST` | `/api/queue` | 批量入队多个 ticker。 |
| `GET` | `/api/queue` | 返回当前 running/pending 队列。 |
| `DELETE` | `/api/queue/{run_id}` | 移除一个 pending 队列项。 |
| `DELETE` | `/api/queue` | 清空所有 pending 队列项。 |
| `PATCH` | `/api/queue/order` | 重排 pending 队列顺序。 |
| `GET` | `/api/queue/parallelism` | 返回当前并发运行上限。 |
| `PUT` | `/api/queue/parallelism` | 设置并发运行上限(1–4),调高立即启动等待中的 run。 |
| `GET` | `/api/history` | 列出历史分析运行。 |
| `GET` | `/api/history/reports.zip` | 打包下载选定/全部已完成报告。 |
| `GET` | `/api/history/{run_id}` | 返回单条历史运行。 |
| `DELETE` | `/api/history/{run_id}` | 删除单条历史运行。 |
| `POST` | `/api/chat/sessions` | 创建投顾对话会话。 |
| `GET` | `/api/chat/sessions` | 列出投顾对话会话。 |
| `DELETE` | `/api/chat/sessions` | 批量删除投顾对话会话。 |
| `GET` | `/api/chat/sessions/{session_id}` | 返回单个会话及其消息。 |
| `PATCH` | `/api/chat/sessions/{session_id}` | 重命名会话。 |
| `PUT` | `/api/chat/sessions/{session_id}/reports` | 替换绑定到会话的已完成分析运行。 |
| `DELETE` | `/api/chat/sessions/{session_id}` | 删除单个会话。 |
| `POST` | `/api/chat/sessions/{session_id}/portfolio` | 从上传图片中抽取持仓。 |
| `PUT` | `/api/chat/sessions/{session_id}/portfolio` | 保存手动编辑的持仓。 |
| `GET` | `/api/chat/sessions/{session_id}/portfolio` | 返回已保存的持仓。 |
| `GET` | `/api/chat/sessions/{session_id}/profile` | 返回会话的投顾画像。 |
| `PUT` | `/api/chat/sessions/{session_id}/profile` | 保存会话的投顾画像。 |
| `POST` | `/api/chat/sessions/{session_id}/stream` | 通过 SSE 流式推送投顾对话响应。 |
| `GET` | `/api/health/services/stream` | 通过 SSE 流式推送服务健康探测结果。 |
| `GET` | `/api/health/services/{service_id}` | 探测单个服务健康项。 |
| `GET` | `/api/ticker/{code}` | 把 ticker/代码解析为显示名。 |
| `GET` | `/api/watchlist` | 返回持久化自选列表。 |
| `PUT` | `/api/watchlist` | 替换持久化自选列表。 |

## 队列并行

一个 run 的墙钟时间几乎全花在等 LLM 和数据源上,所以队列可以同时跑多个标的。
并发数存在 `webui.db` 的 `app_settings` 表(键 `max_parallel_runs`,默认 2,上限 4),
WebUI 队列面板头部的「并发」下拉框即读写 `/api/queue/parallelism`;调高立即启动等待中的
run,调低只影响之后的启动(不会打断在跑的)。

每个 run 跑在**独立子进程**里(`multiprocessing` spawn,`api/run_worker.py`),因为
`dataflows` 的配置单例、预取上下文、以及 AKShare 的 `no_proxy_session()` 猴补丁都是进程级的,
同进程并行会互相污染。子进程冷启动约 1.8s,相对分钟级的 run 可忽略。SSE / 取消 / 遥测
经父进程的桥接线程转发,接口形状不变。

`GET /api/queue` 的 `running` 是**数组**(所有在跑的 run,最早的在前);`POST /api/queue`
返回 `running_run_ids`。WebUI 的实时面板仍只跟随一个 run,队列面板每个 running 行的
「观察」按钮可切换跟随对象,「停止」只取消那一行。

并行的三条已知代价:

- **数据源配额按并发数翻倍**。tushare/AKShare 有分钟级限流,调高并发前先确认额度。
- **每个子进程有独立的 AKShare 熔断器**(进程级状态)。好处是坏 endpoint 不再跨 run 传染,
  坏处是 N 个进程会各自把同一个坏 endpoint 再踩一遍。
- **同一个 ticker 同时入队两次会撞 checkpoint 库**(`~/.tradingagents/cache/checkpoints/<TICKER>.db`
  按 ticker 分库)。checkpoint 在 WebUI 路径下默认关闭,所以只记文档、代码不做防护。
