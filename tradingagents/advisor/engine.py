"""Conversation engine: tool-call loop yielding SSE-shaped event dicts."""

from collections.abc import Iterator

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from tradingagents.advisor.tools import is_no_data

_MAX_TOOL_ROUNDS = 6


def run_chat(
    chain,
    history_messages: list,
    user_message: str,
    tools_by_name: dict,
) -> Iterator[dict]:
    """Drive the tool-call loop.

    `chain` is `prompt | llm.bind_tools(tools)` and is invoked with a message
    list. Yields dicts: {"event": "tool_call"|"token"|"done"|"error", "data": {...}}.
    """
    messages = list(history_messages) + [HumanMessage(content=user_message)]
    executed_tool_calls: list[dict] = []

    try:
        result: AIMessage = chain.invoke(messages)
        rounds = 0
        while getattr(result, "tool_calls", None) and rounds < _MAX_TOOL_ROUNDS:
            rounds += 1
            messages.append(result)
            for call in result.tool_calls:
                name = call["name"]
                args = call.get("args", {})
                yield {"event": "tool_call", "data": {"tool": name, "args": args}}
                tool = tools_by_name.get(name)
                if tool is None:
                    output = f"NO_DATA_AVAILABLE: unknown tool {name}"
                else:
                    try:
                        output = tool.invoke(args)
                    except Exception as exc:  # noqa: BLE001
                        output = f"NO_DATA_AVAILABLE: tool error: {exc}"
                executed_tool_calls.append(
                    {"tool": name, "args": args, "unavailable": is_no_data(output)}
                )
                messages.append(
                    ToolMessage(content=str(output), tool_call_id=call.get("id", name))
                )
            result = chain.invoke(messages)

        text = result.content if isinstance(result.content, str) else str(result.content)
        for i in range(0, len(text), 24):
            yield {"event": "token", "data": {"content": text[i : i + 24]}}

        yield {
            "event": "done",
            "data": {"content": text, "tool_calls": executed_tool_calls},
        }
    except Exception as exc:  # noqa: BLE001
        yield {"event": "error", "data": {"message": str(exc)}}
