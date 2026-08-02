"""FastAPI backend for the web + Telegram frontends.

Runs the equity-research workflow outside Claude Code by driving the
Anthropic Messages API directly with the same system prompt (CLAUDE.md +
the equity-research skill) and the same eight read-only tools from
``src/tool_router.py``. This is the shared core both ``web/`` and
``telegram_bot.py`` call — one agent loop, two interfaces.

Safety notes:
  - There is no write-capable tool to call in the first place (see
    src/tool_router.py) — the PreToolUse-hook-style protection Claude Code
    sessions get is structurally redundant here, but this loop also has no
    execution-shaped tool to misuse.
  - Every final response is checked against the same banned-language list
    the Stop hook uses (src/safety.py) before it's returned to a client. If
    the first attempt trips it, the model gets one instruction to rewrite;
    if it still trips after that, the response is replaced with a safe
    refusal rather than ever sent through.
"""

from __future__ import annotations

import os
import uuid
from typing import Any

from dotenv import load_dotenv

load_dotenv()

from anthropic import Anthropic  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from backend.system_prompt import build_system_prompt
from src import tool_router
from src.safety import contains_banned_language
from src.state.session_store import get_default_store

MODEL = "claude-sonnet-5"
MAX_TOOL_ITERATIONS = 8
WEB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web")

app = FastAPI(title="Investment Research Copilot")
_client: Anthropic | None = None
_system_prompt = build_system_prompt()


def get_client() -> Anthropic:
    global _client
    if _client is None:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not set. Copy .env.example to .env and set your key, "
                "or export ANTHROPIC_API_KEY before starting the backend."
            )
        _client = Anthropic(api_key=api_key)
    return _client


class AskRequest(BaseModel):
    question: str


class AskResponse(BaseModel):
    answer: str
    tool_calls: list[str]
    blocked: bool = False


def run_research(question: str) -> AskResponse:
    """Drive the tool-use loop for one question and return the final note."""
    client = get_client()
    store = get_default_store()
    run_id = str(uuid.uuid4())
    store.start_run(run_id, question)

    messages: list[dict[str, Any]] = [{"role": "user", "content": question}]
    tool_calls_made: list[str] = []

    for _ in range(MAX_TOOL_ITERATIONS):
        response = client.messages.create(
            model=MODEL,
            max_tokens=4096,
            system=_system_prompt,
            tools=tool_router.TOOL_SCHEMAS,
            messages=messages,
        )

        if response.stop_reason != "tool_use":
            final_text = "".join(block.text for block in response.content if block.type == "text")
            final_text, blocked = _enforce_safety(client, messages, response, final_text)
            store.finish_run()
            return AskResponse(answer=final_text, tool_calls=tool_calls_made, blocked=blocked)

        messages.append({"role": "assistant", "content": response.content})
        tool_results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            tool_calls_made.append(block.name)
            result = tool_router.call_tool(block.name, block.input)
            tool_results.append(
                {"type": "tool_result", "tool_use_id": block.id, "content": _to_text(result)}
            )
        messages.append({"role": "user", "content": tool_results})

    store.finish_run()
    return AskResponse(
        answer="Reached the maximum number of tool calls for this question without a final answer. Try narrowing the question.",
        tool_calls=tool_calls_made,
        blocked=False,
    )


def _to_text(result: Any) -> str:
    import json

    try:
        return json.dumps(result, default=str)
    except TypeError:
        return str(result)


def _enforce_safety(client: Anthropic, messages: list[dict[str, Any]], response: Any, final_text: str) -> tuple[str, bool]:
    """Check final_text for a fabricated trade-execution claim; give the model one chance to rewrite.

    Stating a view or rating (bullish/neutral/bearish, buy/hold/sell) is not
    checked here and is allowed — only a claim that a trade was actually
    placed, executed, or filled, which is always false in this project.
    """
    if not contains_banned_language(final_text):
        return final_text, False

    messages.append({"role": "assistant", "content": response.content})
    messages.append(
        {
            "role": "user",
            "content": (
                "Your last response claimed a trade was actually placed, executed, or filled. "
                "This tool has no ability to do that — no tool anywhere in this project can place, "
                "modify, or cancel a trade. Rewrite it to state your view/rating as an opinion "
                "grounded in the metrics and citations, without claiming any action was taken."
            ),
        }
    )
    retry = client.messages.create(
        model=MODEL, max_tokens=4096, system=_system_prompt, messages=messages
    )
    retry_text = "".join(block.text for block in retry.content if block.type == "text")

    if contains_banned_language(retry_text):
        return (
            "This response was blocked twice for claiming a trade was actually executed, and has "
            "been withheld. Please rephrase your question.",
            True,
        )
    return retry_text, False


@app.post("/api/ask", response_model=AskResponse)
def ask(request: AskRequest) -> AskResponse:
    return run_research(request.question)


@app.get("/api/portfolio")
def portfolio() -> dict[str, Any]:
    return tool_router.get_portfolio_snapshot()


# Registered after the /api/* routes above: explicit path operations are
# matched first, so this catch-all mount only ever serves the static
# frontend (and index.html for "/") without shadowing the API.
app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
