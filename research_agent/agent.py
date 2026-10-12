"""Hotel noise check: pick hotels with Python, then let the main agent dispatch hotel-checker."""

import argparse
import asyncio
import os
import sys
from pathlib import Path
from typing import Any, Callable

from claude_agent_sdk import (
    AgentDefinition,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    HookMatcher,
)
from claude_agent_sdk.types import PermissionResultDeny
from dotenv import load_dotenv

from research_agent.hotel_tools import (
    SERVER_NAME,
    TOOL_NAMES,
    create_server,
    load_hotels,
)
from research_agent.select_hotels import select_hotels
from research_agent.utils.message_handler import process_assistant_message
from research_agent.utils.subagent_tracker import SubagentTracker
from research_agent.utils.transcript import setup_session, TranscriptWriter

# Load environment variables
load_dotenv()

# Paths to prompt files
PROMPTS_DIR = Path(__file__).parent / "prompts"
# 项目根目录：本文件在 research_agent/ 里，上一级就是 research-agent/
PROJECT_DIR = Path(__file__).resolve().parent.parent


def load_prompt(filename: str) -> str:
    """Load a prompt from the prompts directory."""
    prompt_path = PROMPTS_DIR / filename
    with open(prompt_path, "r", encoding="utf-8") as f:
        return f.read().strip()


def parse_args() -> argparse.Namespace:
    """读命令行参数：CSV 路径、城市、评分、最低评论数、最多查几家。"""
    parser = argparse.ArgumentParser(description="检查酒店是否适合怕吵的客人")
    parser.add_argument("--csv", required=True, help="Hotel_Reviews.csv 的路径")
    parser.add_argument("--city", required=True, help="城市名，例如 Milan")
    parser.add_argument("--score", type=float, required=True,
                        help="Average_Score 正好等于这个值，例如 8.0")
    parser.add_argument("--min-reviews", type=int, required=True,
                        help="这家酒店在 CSV 里至少有几行评论")
    parser.add_argument("--max-hotels", type=int, default=1,
                        help="最多查几家，默认 1")
    return parser.parse_args()


def check_api_key() -> None:
    """检查 .env 里有没有 DeepSeek 的 key；没有就提示怎么设置并退出。"""
    if not os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        sys.exit("\nError: ANTHROPIC_AUTH_TOKEN not found.\n"
                 "Copy .env.example to .env and fill in your DeepSeek key.\n"
                 "Get your key at: https://platform.deepseek.com\n")


def filter_hotels(args: argparse.Namespace) -> list[dict]:
    """检查 CSV，按城市、评分、评论数筛出要查的酒店，连同差评一起返回。不花钱。

    出问题就打印原因并退出。
    """
    # 把 --csv 变成完整路径，后面切换文件夹也不会找错
    csv_path = Path(args.csv).resolve()
    if not csv_path.is_file():
        sys.exit(f"Error: CSV not found: {csv_path}")

    hotels = select_hotels(csv_path, args.city, args.score,
                           args.min_reviews, args.max_hotels)
    if not hotels:
        sys.exit(f"{args.city} {args.score}: 0 hotels found")
    print(f"\nHotels to check: {len(hotels)}")
    for h in hotels:
        print(f"  - {h['hotel']} ({h['reviews']} reviews)")
    return hotels


def build_user_prompt(args: argparse.Namespace, hotels: list[dict]) -> str:
    """把城市、评分和要查的酒店名拼成一段文字，发给主 agent。路径都不用给。"""
    lines = [
        f"Check these {len(hotels)} hotel(s) with the hotel-checker agent.",
        f"City: {args.city}",
        f"Score: {args.score:.1f}",
    ]
    for i, h in enumerate(hotels, 1):
        lines.append(f"Hotel {i}: {h['hotel']}")
    return "\n".join(lines)


def build_agents() -> dict[str, AgentDefinition]:
    """定义唯一的 subagent：hotel-checker，一次查一家酒店，只能用 4 个工具。"""
    return {
        "hotel-checker": AgentDefinition(
            description=(
                "Checks ONE hotel for noise-sensitive guests. "
                "Give it the hotel name, copied exactly."
            ),
            tools=TOOL_NAMES,
            prompt=load_prompt("hotel_checker.txt"),
            model="sonnet",
        ),
    }


def deny(input_data: dict, reason: str) -> dict:
    """hook 的"拒绝"回复：告诉 SDK 不许用这个工具，并说明原因。"""
    return {
        "hookSpecificOutput": {
            "hookEventName": input_data["hook_event_name"],
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }


async def main_agent_only_delegates(input_data: dict, tool_use_id: str | None,
                                    context: Any) -> dict:
    """hook：主 agent 只能用 Agent/Task 派活，其他工具一律拒绝。subagent 不管。"""
    del tool_use_id, context  # SDK 规定要有这两个参数，这里用不到
    is_subagent = bool(input_data.get("agent_id"))
    if is_subagent or input_data["tool_name"] in ("Agent", "Task"):
        return {}
    return deny(input_data,
                "The main agent may only delegate with the Agent tool.")


def make_pre_tool_use(tracker: SubagentTracker) -> Callable:
    """生成 PreToolUse hook：先用 main_agent_only_delegates 判断，再记日志。

    被拒绝的调用之后不会触发任何 post hook（已实测），所以拒绝要在这里记下。
    """
    async def pre_tool_use(input_data: dict, tool_use_id: str | None,
                           context: Any) -> dict:
        """hook：判断放行还是拒绝，把结果一起记进日志。"""
        result = await main_agent_only_delegates(input_data, tool_use_id,
                                                 context)
        await tracker.pre_tool_use_hook(input_data, tool_use_id, context,
                                        denied=bool(result))
        return result

    return pre_tool_use


async def deny_all_requests(tool_name: str, input_data: dict,
                            context: Any) -> PermissionResultDeny:
    """can_use_tool：走到这里的请求（联网、读项目外文件等）一律拒绝，不问人。"""
    del input_data, context  # SDK 规定要有这两个参数，这里用不到
    print(f"\n[auto-deny] {tool_name}")
    return PermissionResultDeny(message=f"{tool_name} is not allowed in this run.")


def build_claude_options(tracker: SubagentTracker) -> ClaudeAgentOptions:
    """组装 Claude 的设置单：模型、工具、subagent、hook、权限、环境变量。"""
    hooks = {
        "PreToolUse": [HookMatcher(hooks=[make_pre_tool_use(tracker)])],
        "PostToolUse": [HookMatcher(hooks=[tracker.post_tool_use_hook])],
        # 工具返回 is_error 时只触发这个，不触发 PostToolUse（已实测）
        "PostToolUseFailure": [HookMatcher(
            hooks=[tracker.post_tool_use_failure_hook])],
    }
    return ClaudeAgentOptions(
        cwd=str(PROJECT_DIR),
        setting_sources=["project"],
        system_prompt=load_prompt("lead_agent.txt"),
        model="haiku",
        # 只管自带工具：只留派活的工具，Bash、Read 等都去掉。
        # 这里要写旧名 Task（init 的工具列表里它叫 Task，已实测）
        tools=["Task"],
        # 不用问就放行：派活 + 4 个酒店工具。MCP 工具不受 tools 影响，
        # lead 也看得到它们，拦 lead 靠 main_agent_only_delegates
        allowed_tools=["Agent", *TOOL_NAMES],
        mcp_servers={SERVER_NAME: create_server()},
        agents=build_agents(),
        hooks=hooks,
        permission_mode="default",
        can_use_tool=deny_all_requests,
        env={
            "CLAUDE_CODE_DISABLE_BACKGROUND_TASKS": "1",
            "CLAUDE_AGENT_SDK_DISABLE_BUILTIN_AGENTS": "1",
        },
    )


async def run_claude(task: str, options: ClaudeAgentOptions,
                     tracker: SubagentTracker,
                     transcript: TranscriptWriter) -> None:
    """把指令发给主 agent 一次，边收回复边打印，主 agent 回复完就结束。"""
    transcript.write_to_file(f"\nTask:\n{task}\n")
    async with ClaudeSDKClient(options=options) as client:
        await client.query(prompt=task)
        transcript.write("\nAgent: ", end="")
        async for msg in client.receive_response():
            if type(msg).__name__ == "AssistantMessage":
                process_assistant_message(msg, tracker, transcript)
        transcript.write("\n")


def main() -> None:
    """按顺序：读参数 → 检查 key → 筛酒店、存进内存 → 切到项目根目录 → 启动 Claude 跑一次。"""
    args = parse_args()
    check_api_key()
    hotels = filter_hotels(args)
    load_hotels(hotels)
    # 必须在 filter_hotels 之后：它要先把相对路径换成完整路径
    os.chdir(PROJECT_DIR)

    transcript_file, session_dir = setup_session()
    transcript = TranscriptWriter(transcript_file)
    tracker = SubagentTracker(transcript_writer=transcript,
                              session_dir=session_dir)
    try:
        asyncio.run(run_claude(build_user_prompt(args, hotels),
                               build_claude_options(tracker),
                               tracker, transcript))
    finally:
        transcript.close()
        tracker.close()
        print(f"\nSession logs saved to: {session_dir}")
        print(f"Summary: {Path(hotels[0]['work_dir']).parent.parent / 'summary.csv'}")


if __name__ == "__main__":
    main()
