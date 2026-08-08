# HTTP API 参考(WebUI 后端)

WebUI 后端从 [api/main.py](../api/main.py) 挂载,路由定义在 [api/routes/](../api/routes/)。
本文只覆盖对外的 FastAPI HTTP 接口;**Agent 侧的数据获取方法**(`get_stock_data`
等)不是 HTTP 接口,见 [data-fetching-apis.md](./data-fetching-apis.md)。

> 单用户不变量:同一时刻只跑一个分析。忙时不再返回 409,而是入队(见
> [api/scheduler.py](../api/scheduler.py))。CORS 只放行 `localhost:3000`。

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
