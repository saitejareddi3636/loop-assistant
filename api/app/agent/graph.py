from __future__ import annotations

from typing import Annotated, Literal, TypedDict

from langchain_core.messages import AIMessage, BaseMessage, SystemMessage, ToolMessage
from langchain_core.tools import StructuredTool
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode

from app.agent.llm import ainvoke_with_retries, get_chat_model
from app.agent.tools import SYSTEM_PROMPT
from app.config import get_settings


class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    cycle: int


VOICE_STYLE = """

VOICE MODE: your reply is spoken aloud by text-to-speech.
- Answer in at most 3 short sentences.
- Plain text only: no markdown, bullets, asterisks, or tables.
- Spell out amounts naturally (for example "twenty-nine dollars")."""


def build_agent_graph(tools: list[StructuredTool], *, voice: bool = False):
    """LangGraph planner that dynamically selects tools via model tool-calling."""
    settings = get_settings()
    system_prompt = SYSTEM_PROMPT + (VOICE_STYLE if voice else "")
    model = get_chat_model().bind_tools(tools)
    tool_node = ToolNode(tools)

    async def planner(state: AgentState) -> dict:
        cycle = int(state.get("cycle", 0)) + 1
        if cycle > settings.agent_max_cycles:
            return {
                "messages": [
                    AIMessage(
                        content=(
                            "I reached my tool-step limit for this turn. "
                            "I can escalate this to a human specialist if you'd like."
                        )
                    )
                ],
                "cycle": cycle,
            }

        history = [SystemMessage(content=system_prompt), *state["messages"]]
        response = await ainvoke_with_retries(model, history)
        return {"messages": [response], "cycle": cycle}

    def route_after_planner(state: AgentState) -> Literal["tools", "__end__"]:
        last = state["messages"][-1]
        if isinstance(last, AIMessage) and last.tool_calls:
            if int(state.get("cycle", 0)) > settings.agent_max_cycles:
                return END
            return "tools"
        return END

    graph = StateGraph(AgentState)
    graph.add_node("planner", planner)
    graph.add_node("tools", tool_node)
    graph.add_edge(START, "planner")
    graph.add_conditional_edges("planner", route_after_planner, {"tools": "tools", END: END})
    graph.add_edge("tools", "planner")
    return graph.compile()


def extract_final_text(messages: list[BaseMessage]) -> str:
    for message in reversed(messages):
        if isinstance(message, AIMessage) and message.content and not message.tool_calls:
            if isinstance(message.content, str):
                return message.content
            # Anthropic/Groq may return list content blocks
            if isinstance(message.content, list):
                parts = []
                for block in message.content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        parts.append(str(block.get("text", "")))
                    else:
                        parts.append(str(block))
                text = "\n".join(p for p in parts if p).strip()
                if text:
                    return text
            return str(message.content)
        if isinstance(message, ToolMessage):
            continue
    return "I wasn't able to complete that request. Please try again."
