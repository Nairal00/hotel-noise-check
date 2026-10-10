"""Smoke test: check DeepSeek can run a subagent with a preloaded skill."""

import asyncio
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

load_dotenv()

PROJECT_DIR = Path(__file__).resolve().parent

AGENTS = {
    "skill-reader": AgentDefinition(
        description="Answers questions using the executive-briefing skill and project files.",
        prompt=(
            "Answer using the executive-briefing skill and the Read tool. "
            "Reply in one line per question."
        ),
        tools=["Skill", "Read"],
        skills=["executive-briefing"],
        model="sonnet",
    ),
}

PROMPT = (
    "Step 1: run `ls` yourself with the Bash tool. "
    "Step 2: use the skill-reader agent to answer two questions: "
    "(a) in the executive-briefing skill, what is the exact title of the section "
    "right after 'Activation Triggers'? "
    "(b) read pyproject.toml in the current directory and report the value of `name`. "
    "Reply with both answers."
)


async def main_agent_only_delegates(input_data, tool_use_id, context):
    """Deny every tool except Agent when the main agent calls it."""
    del tool_use_id, context  # not used
    tool = input_data["tool_name"]
    is_sub = bool(input_data.get("agent_id"))
    if is_sub or tool in ("Agent", "Task"):
        print(f"[hook] {'sub ' if is_sub else 'main'} {tool} -> allow")
        return {}
    print(f"[hook] main {tool} -> DENY")
    return {
        "hookSpecificOutput": {
            "hookEventName": input_data["hook_event_name"],
            "permissionDecision": "deny",
            "permissionDecisionReason": "The main agent may only delegate with the Agent tool.",
        }
    }


def who(message):
    """Return 'sub ' if the message comes from a subagent, else 'main'."""
    return "sub " if getattr(message, "parent_tool_use_id", None) else "main"


async def main():
    """Run one query and print every step."""
    print(f"PROJECT_DIR: {PROJECT_DIR}")
    options = ClaudeAgentOptions(
        cwd=str(PROJECT_DIR),
        setting_sources=["project"],
        permission_mode="default",
        allowed_tools=["Agent", "Skill", "Read"],
        agents=AGENTS,
        model="haiku",
        max_budget_usd=0.5,
        hooks={"PreToolUse": [HookMatcher(hooks=[main_agent_only_delegates])]},
        env={
            "CLAUDE_CODE_DISABLE_BACKGROUND_TASKS": "1",
            "CLAUDE_AGENT_SDK_DISABLE_BUILTIN_AGENTS": "1",
        },
    )
    async for message in query(prompt=PROMPT, options=options):
        if isinstance(message, SystemMessage) and message.subtype == "init":
            data = message.data
            print(f"[init] cwd: {data.get('cwd')}")
            print(f"[init] permissionMode: {data.get('permissionMode')}")
            print(f"[init] agents: {data.get('agents')}")
        elif isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, ToolUseBlock):
                    print(f"[{who(message)}] tool: {block.name} {str(block.input)[:200]}")
                elif isinstance(block, TextBlock):
                    print(f"[{who(message)}] text: {block.text}")
        elif isinstance(message, UserMessage) and isinstance(message.content, list):
            for block in message.content:
                if isinstance(block, ToolResultBlock):
                    print(f"[{who(message)}]   -> result: {str(block.content)[:200]}")
        elif isinstance(message, ResultMessage):
            print(f"result: {message.subtype}")
            print(f"answer: {message.result}")


asyncio.run(main())