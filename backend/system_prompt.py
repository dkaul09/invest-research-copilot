"""Builds the system prompt for the standalone (non-Claude-Code) agent loop.

Concatenates CLAUDE.md's hard boundaries/tool contract with the
equity-research skill's workflow, so the web/Telegram frontends follow the
exact same rules and steps as a Claude Code session in this project —
there is only one place those rules are written down.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def build_system_prompt() -> str:
    claude_md = (REPO_ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    skill_md = (REPO_ROOT / ".claude" / "skills" / "equity-research" / "SKILL.md").read_text(encoding="utf-8")

    return (
        "You are the investment research copilot described below. Follow these "
        "documents exactly — they are this project's actual project memory and "
        "workflow spec, not a summary of them.\n\n"
        "=== CLAUDE.md (project memory) ===\n"
        f"{claude_md}\n\n"
        "=== .claude/skills/equity-research/SKILL.md (the workflow) ===\n"
        f"{skill_md}\n"
    )
