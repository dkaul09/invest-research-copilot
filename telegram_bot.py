"""Telegram bot: backup interface to the same research backend as the web UI.

Calls backend.app.run_research directly (in-process, no HTTP hop) so the web
frontend and this bot share the exact same agent loop, tool set, and safety
checks — one core, two interfaces, as with the MCP server and this backend
sharing src/tool_router.py.

Run with: python telegram_bot.py
Requires TELEGRAM_BOT_TOKEN (and ANTHROPIC_API_KEY) in .env.

If TELEGRAM_ALLOWED_CHAT_ID is set, the bot ignores messages from any other
chat — this bot has no login system of its own, so that's the only access
control it has. Leave it unset only if you're fine with anyone who finds the
bot's username being able to use it (it can still never place a trade —
that's enforced below the interface layer, not here).
"""

from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()

from telegram import Update  # noqa: E402
from telegram.ext import Application, ContextTypes, MessageHandler, filters  # noqa: E402

from backend.app import run_research  # noqa: E402

ALLOWED_CHAT_ID = os.environ.get("TELEGRAM_ALLOWED_CHAT_ID", "").strip()

# Telegram messages cap out around 4096 characters; split long research
# notes rather than truncating them silently.
TELEGRAM_MAX_LEN = 4000


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = str(update.effective_chat.id)
    if ALLOWED_CHAT_ID and chat_id != ALLOWED_CHAT_ID:
        await update.message.reply_text(
            f"This bot is restricted to a specific chat. Your chat id is {chat_id} — "
            "set TELEGRAM_ALLOWED_CHAT_ID to this value if this is you."
        )
        return

    question = update.message.text
    await update.message.reply_text("Researching…")

    response = run_research(question)
    text = response.answer
    if response.blocked:
        text = f"⚠️ {text}"

    for i in range(0, len(text), TELEGRAM_MAX_LEN):
        await update.message.reply_text(text[i : i + TELEGRAM_MAX_LEN])


def main() -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN is not set. Copy .env.example to .env, create a bot with "
            "@BotFather on Telegram, and set the token before running this bot."
        )

    app = Application.builder().token(token).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("Telegram bot running. Press Ctrl+C to stop.")
    app.run_polling()


if __name__ == "__main__":
    main()
