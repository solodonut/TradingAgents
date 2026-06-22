@AGENTS.md

## Claude Code 专属说明

> 公共项目约定见上面引入的 `AGENTS.md`。以下只补充 Claude Code 在本仓库运行时的工具使用习惯。

- **回复一律用中文**：与用户的所有对话回复都使用中文，不要用日文或英文。
- **Python 一律走项目 venv**：系统 `python`/`python3` 可能是 3.10 以下，会报 union 语法错误。
  用 Bash 工具跑任何 Python/pytest/uvicorn 命令时，显式使用 `.venv/bin/python`
  （而不是裸 `python3`、`pytest`、`uvicorn`），避免 NumPy 1.x/2.x 冲突崩溃。
- **改前端前先读 Next.js 16 文档**：`webui/` 用 Next.js 16 + React 19，与训练数据有破坏性差异。
  动 `webui/` 代码前先看 `webui/node_modules/next/dist/docs/`，参考 `webui/AGENTS.md`。
- **没有 CI，收尾前手动验证**：改完代码后自己跑 `ruff check .` 和 `pytest -m "not integration"`，
  不要假设有流水线兜底。需要真实 API key 的 `integration` 测试会自动跳过。
- **提交规范**：Conventional Commits（`feat(scope):` / `fix(scope):` / `test(scope):`），
  并同步维护 `CHANGELOG.md`（Keep a Changelog 格式）。只有用户明确要求时才提交或推送。
