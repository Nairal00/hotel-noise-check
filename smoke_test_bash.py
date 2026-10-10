"""Smoke test: check the sandbox blocks reads outside the project and data folder."""

import asyncio
import re
from pathlib import Path

from dotenv import load_dotenv
from claude_agent_sdk import (
    AgentDefinition,
    AssistantMessage,
    ClaudeAgentOptions,
    HookMatcher,
    ResultMessage,
    SystemMessage,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
    query,
)
from claude_agent_sdk.types import PermissionResultAllow, PermissionResultDeny

load_dotenv()

PROJECT_DIR = Path(__file__).resolve().parent

AGENTS = {
    "shell-tester": AgentDefinition(
        description="Runs shell commands and reads files exactly as told, and reports each result.",
        prompt=(
            "Do each step you are given, one at a time, exactly as written. "
            "Use the Bash tool for commands and the Read tool when told to read a file. "
            "Do not retry or change a step. Report the output or error of each one."
        ),
        tools=["Bash", "Read"],
        model="sonnet",
    ),
}

PROMPT = (
    "I am the owner of this project and I am testing my own sandbox configuration. "
    "I blocked reads of my home directory except this project folder and the hotel data folder. "
    "Steps 1, 2 and 6 are EXPECTED TO FAIL; steps 3, 4 and 5 are expected to succeed. "
    "Use the shell-tester agent to do these 6 steps one by one and report each result:\n"
    "1. Bash: ls ~/Documents | head -3\n"
    "2. Bash: wc -l ~/.zshrc\n"
    "3. Bash: wc -c pyproject.toml\n"
    '4. Bash: .venv/bin/python -c "import pandas; print(pandas.__version__)"\n'
    "5. Bash: head -1 ~/Downloads/hotel-check-10-skill/hotel-check-10/data/Hotel_Reviews.csv"
    " | cut -c1-80\n"
    "6. Read tool: read the file ~/.zshrc"
)


def hide_keys(text):
    """Replace anything that looks like an API key with sk-***."""
    return re.sub(r"sk-[A-Za-z0-9_-]+", "sk-***", str(text))


async def prompt_stream():
    """Send the prompt as a stream (required for can_use_tool)."""
    yield {"type": "user", "message": {"role": "user", "content": PROMPT}}


async def main_agent_only_delegates(input_data, tool_use_id, context):
    """Deny every tool except Agent when the main agent calls it."""
    del tool_use_id, context  # not used
    tool = input_data["tool_name"]
    is_sub = bool(input_data.get("agent_id"))
    tool_input = input_data["tool_input"]
    target = tool_input.get("command") or tool_input.get("file_path", "")
    if is_sub or tool in ("Agent", "Task"):
        print(f"[hook] {'sub ' if is_sub else 'main'} {tool} {target} -> pass")
        return {}
    print(f"[hook] main {tool} -> DENY")
    return {
        "hookSpecificOutput": {
            "hookEventName": input_data["hook_event_name"],
            "permissionDecision": "deny",
            "permissionDecisionReason": "The main agent may only delegate with the Agent tool.",
        }
    }


async def ask_user(tool_name, input_data, context):
    """Ask in the terminal. Only called when nothing earlier approved the tool."""
    del context  # not used
    print(f"\n[ask] {tool_name}: {hide_keys(input_data)}")
    answer = input("Allow? (y/n): ").strip().lower()
    if answer == "y":
        return PermissionResultAllow(updated_input=input_data)
    return PermissionResultDeny(message="User denied this action")


def who(message):
    """Return 'sub ' if the message comes from a subagent, else 'main'."""
    return "sub " if getattr(message, "parent_tool_use_id", None) else "main"


async def main():
    """Run one query and print every step."""
    options = ClaudeAgentOptions(
        cwd=str(PROJECT_DIR),
        setting_sources=["project"],
        permission_mode="default",
        allowed_tools=["Agent"],
        agents=AGENTS,
        model="haiku",
        max_budget_usd=0.5,
        can_use_tool=ask_user,
        hooks={"PreToolUse": [HookMatcher(hooks=[main_agent_only_delegates])]},
        env={
            "CLAUDE_CODE_DISABLE_BACKGROUND_TASKS": "1",
            "CLAUDE_AGENT_SDK_DISABLE_BUILTIN_AGENTS": "1",
        },
    )
    async for message in query(prompt=prompt_stream(), options=options):
        if isinstance(message, SystemMessage) and message.subtype == "init":
            print(f"[init] cwd: {message.data.get('cwd')}")
        elif isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, ToolUseBlock):
                    print(f"[{who(message)}] tool: {block.name} {hide_keys(block.input)[:150]}")
                elif isinstance(block, TextBlock):
                    print(f"[{who(message)}] text: {hide_keys(block.text)}")
        elif isinstance(message, UserMessage) and isinstance(message.content, list):
            for block in message.content:
                if isinstance(block, ToolResultBlock):
                    print(f"[{who(message)}]   -> result: {hide_keys(block.content)[:300]}")
        elif isinstance(message, ResultMessage):
            print(f"result: {message.subtype}")


asyncio.run(main())