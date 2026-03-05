"""Minimal LangGraph chatbot service with OpenRouter streaming."""

from __future__ import annotations

import os
from typing import Any, AsyncIterator, TypedDict

from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph


class ChatState(TypedDict):
    messages: list[BaseMessage]


_GRAPH = None
_MODEL: ChatOpenAI | None = None


def _content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text", "")))
            elif isinstance(item, str):
                parts.append(item)
        return "".join(parts)
    return str(content or "")


def _build_model() -> ChatOpenAI:
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError("Missing OPENROUTER_API_KEY")

    headers: dict[str, str] = {}
    site_url = os.getenv("OPENROUTER_SITE_URL")
    app_name = os.getenv("OPENROUTER_APP_NAME", "AgriIntel")
    if site_url:
        headers["HTTP-Referer"] = site_url
    headers["X-Title"] = app_name

    return ChatOpenAI(
        model=os.getenv("OPENROUTER_MODEL", "openai/gpt-4o-mini"),
        api_key=api_key,
        base_url=os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
        temperature=0.2,
        streaming=True,
        default_headers=headers,
    )


def _build_graph():
    # Keep LangGraph in the flow: one minimal normalization node.
    async def normalize_node(state: ChatState):
        return {"messages": state["messages"]}

    builder = StateGraph(ChatState)
    builder.add_node("normalize", normalize_node)
    builder.set_entry_point("normalize")
    builder.set_finish_point("normalize")
    return builder.compile()


def _get_graph():
    global _GRAPH
    if _GRAPH is None:
        _GRAPH = _build_graph()
    return _GRAPH


def _get_model() -> ChatOpenAI:
    global _MODEL
    if _MODEL is None:
        _MODEL = _build_model()
    return _MODEL


async def stream_chat_response(
    user_message: str,
    history: list[dict[str, str]] | None = None,
) -> AsyncIterator[str]:
    graph = _get_graph()
    model = _get_model()

    messages: list[BaseMessage] = [
        SystemMessage(
            content=(
                "You are Agri Assistant for an agriculture dashboard. "
                "Keep answers short, practical, and in English unless user asks otherwise."
            )
        )
    ]

    for item in history or []:
        role = (item.get("role") or "").lower().strip()
        content = (item.get("content") or "").strip()
        if not content:
            continue
        if role == "assistant":
            messages.append(AIMessage(content=content))
        elif role == "user":
            messages.append(HumanMessage(content=content))

    messages.append(HumanMessage(content=user_message))
    state = await graph.ainvoke({"messages": messages})
    llm_messages = state["messages"]

    async for chunk in model.astream(llm_messages):
        if isinstance(chunk, AIMessageChunk):
            text = _content_to_text(chunk.content)
            if text:
                yield text


async def stream_chat_events(
    user_message: str,
    history: list[dict[str, str]] | None = None,
) -> AsyncIterator[dict[str, str]]:
    graph = _get_graph()
    model = _get_model()

    yield {"type": "stage", "stage": "prepare", "label": "Preparing context"}
    messages: list[BaseMessage] = [
        SystemMessage(
            content=(
                "You are Agri Assistant for an agriculture dashboard. "
                "Keep answers short, practical, and in English unless user asks otherwise."
            )
        )
    ]

    for item in history or []:
        role = (item.get("role") or "").lower().strip()
        content = (item.get("content") or "").strip()
        if not content:
            continue
        if role == "assistant":
            messages.append(AIMessage(content=content))
        elif role == "user":
            messages.append(HumanMessage(content=content))

    messages.append(HumanMessage(content=user_message))

    yield {"type": "stage", "stage": "graph", "label": "Running LangGraph"}
    state = await graph.ainvoke({"messages": messages})
    llm_messages = state["messages"]

    yield {"type": "stage", "stage": "model", "label": "Calling OpenRouter model"}
    yielded_any = False
    async for chunk in model.astream(llm_messages):
        if isinstance(chunk, AIMessageChunk):
            text = _content_to_text(chunk.content)
            if text:
                if not yielded_any:
                    yield {"type": "stage", "stage": "stream", "label": "Streaming response"}
                    yielded_any = True
                yield {"type": "delta", "delta": text}

    yield {"type": "stage", "stage": "done", "label": "Completed"}
