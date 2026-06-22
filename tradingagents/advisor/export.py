"""Generate and persist confirmed chat conclusions as Markdown reports."""

from __future__ import annotations

import unicodedata
from datetime import date
from pathlib import Path

from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

_NO_CONFIRMED_CONTENT = "NO_CONFIRMED_CONTENT"
_INVALID_FILENAME_CHARS = frozenset('/\\:*?"<>|')

_REPORT_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """Create a self-contained Markdown report from the complete conversation history.

Scope: {scope}

Include only final confirmed conclusions and action items. When statements conflict, a newer explicit confirmation
overrides earlier content. Exclude misunderstandings, denied, superseded,
or trial content, as well as the correction process itself. Stay strictly within the stated scope,
do not invent facts, and exclude export-control chatter (including requests or discussion about
creating, naming, saving, or downloading the report).

Output Markdown only. If there is no confirmed content in scope, output exactly:
NO_CONFIRMED_CONTENT""",
        ),
        MessagesPlaceholder(variable_name="messages"),
    ]
)


class NoConfirmedContentError(ValueError):
    """Raised when a conversation has no confirmed report content."""


def _response_text(response: object) -> str:
    content = getattr(response, "content", response)
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        texts: list[str] = []
        for block in content:
            if isinstance(block, str):
                texts.append(block)
            elif (
                isinstance(block, dict)
                and block.get("type") == "text"
                and isinstance(block.get("text"), str)
            ):
                texts.append(block["text"])
        return "\n".join(texts).strip()
    return ""


def _require_confirmed_content(markdown: str) -> str:
    normalized = markdown.strip()
    if not normalized or normalized == _NO_CONFIRMED_CONTENT:
        raise NoConfirmedContentError("No confirmed content is available to export")
    return normalized


def generate_report_markdown(llm, messages: list, scope: str) -> str:
    """Summarize confirmed in-scope conclusions from a complete chat history."""

    rendered_prompt = _REPORT_PROMPT.invoke({"messages": messages, "scope": scope})
    response = llm.invoke(rendered_prompt)
    return _require_confirmed_content(_response_text(response))


def _safe_title(session_title: str) -> str:
    title = "".join(
        character
        for character in session_title
        if character not in _INVALID_FILENAME_CHARS
        and unicodedata.category(character) != "Cc"
    )
    title = title.strip().rstrip(".").rstrip()[:80].rstrip(".").rstrip()
    return title or "chat-report"


def save_report(
    markdown: str,
    session_title: str,
    report_dir: Path,
    *,
    today: date | None = None,
) -> Path:
    """Save a report without overwriting an existing or concurrently-created file."""

    report = _require_confirmed_content(markdown)
    report_dir = Path(report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    base_name = f"{(today or date.today()).isoformat()}-{_safe_title(session_title)}"

    suffix = 1
    while True:
        filename = f"{base_name}.md" if suffix == 1 else f"{base_name}-{suffix}.md"
        candidate = report_dir / filename
        try:
            file = candidate.open("x", encoding="utf-8")
        except FileExistsError:
            suffix += 1
            continue

        try:
            with file:
                file.write(report if report.endswith("\n") else f"{report}\n")
        except BaseException:
            candidate.unlink(missing_ok=True)
            raise
        return candidate
