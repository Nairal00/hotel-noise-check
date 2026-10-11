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
SKILL_DIR = PROJECT_DIR / ".claude" / "skills" / "hotel-check-10"


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


def filter_hotels(args: argparse.Namespace) -> tuple[Path, list[dict]]:
    """检查 CSV，按城市、评分、评论数筛出要查的酒店。不花钱。

    返回 (CSV 完整路径, 要查的酒店列表)；出问题就打印原因并退出。
    """
    # 把 --csv 变成完整路径，后面切换文件夹、交给 subagent 都不会找错
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
    return csv_path, hotels


def build_user_prompt(args: argparse.Namespace, csv_path: Path,
               hotels: list[dict]) -> str:
    """把要查的酒店和所需路径拼成一段文字，发给主 agent。"""
    lines = [
        f"Check these {len(hotels)} hotel(s) with the hotel-checker agent.",
        f"City: {args.city}",
        f"Score: {args.score:.1f}",
        f"CSV: {csv_path}",
        f"Skill dir: {SKILL_DIR}",
        f"Python: {sys.executable}",
    ]
    for i, h in enumerate(hotels, 1):
        lines.append(f"Hotel {i}: {h['hotel']}")
        lines.append(f"  Work dir: {h['work_dir']}")
    return "\n".join(lines)


def build_agents() -> dict[str, AgentDefinition]:
    """定义唯一的 subagent：hotel-checker，一次查一家酒店。"""
    return {
        "hotel-checker": AgentDefinition(
            description=(
                "Checks ONE hotel for noise-sensitive guests with the "
                "hotel-check-10 skill. Give it the hotel name, work dir, "
                "CSV path, skill dir, Python path, city and score."
            ),
            tools=["Skill", "Bash", "Read"],
            skills=["hotel-check-10"],
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


async def confirm_bash(input_data: dict, tool_use_id: str | None,
                       context: Any) -> dict:
    """hook：subagent 每条 Bash 命令先在终端打印，等你输入 y 才放行。"""
    del tool_use_id, context  # SDK 规定要有这两个参数，这里用不到
    # 不是 Bash，或者是主 agent 用的（已经被另一个 hook 拒绝）→ 不管
    if input_data["tool_name"] != "Bash" or not input_data.get("agent_id"):
        return {}
    command = input_data["tool_input"].get("command", "")
    print(f"\n[Bash] {command}")
    if input("Allow? (y/n): ").strip().lower() == "y":
        return {}
    return deny(input_data, "The user denied this command.")


def make_limit_read(csv_dir: Path) -> Callable:
    """生成 limit_read hook：subagent 只能用 Read 读项目文件夹和 CSV 所在文件夹。"""
    allowed = [PROJECT_DIR, csv_dir]

    async def limit_read(input_data: dict, tool_use_id: str | None,
                         context: Any) -> dict:
        """hook：Read 的路径不在允许的文件夹里就拒绝。"""
        del tool_use_id, context  # SDK 规定要有这两个参数，这里用不到
        if input_data["tool_name"] != "Read" or not input_data.get("agent_id"):
            return {}
        path = Path(input_data["tool_input"].get("file_path", "")).resolve()
        if any(path.is_relative_to(folder) for folder in allowed):
            return {}
        return deny(input_data, f"Reading outside the project and CSV folder "
                                f"is not allowed: {path}")

    return limit_read


async def deny_all_requests(tool_name: str, input_data: dict,
                            context: Any) -> PermissionResultDeny:
    """can_use_tool：走到这里的请求（联网、读项目外文件等）一律拒绝，不问人。"""
    del input_data, context  # SDK 规定要有这两个参数，这里用不到
    print(f"\n[auto-deny] {tool_name}")
    return PermissionResultDeny(message=f"{tool_name} is not allowed in this run.")


def build_claude_options(tracker: SubagentTracker,
                         csv_dir: Path) -> ClaudeAgentOptions:
    """组装 Claude 的设置单：模型、工具、subagent、hook、权限、环境变量。"""
    hooks = {
        # 超时 600 秒 = 10 分钟：试跑时等你输入 y/n，默认 60 秒太短
        "PreToolUse": [HookMatcher(timeout=600, hooks=[
            main_agent_only_delegates,
            confirm_bash,
            make_limit_read(csv_dir),
            tracker.pre_tool_use_hook,
        ])],
        "PostToolUse": [HookMatcher(hooks=[tracker.post_tool_use_hook])],
    }
    return ClaudeAgentOptions(
        cwd=str(PROJECT_DIR),
        setting_sources=["project"],
        system_prompt=load_prompt("lead_agent.txt"),
        model="haiku",
        allowed_tools=["Agent"],
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
    """按顺序：读参数 → 检查 key → 筛酒店 → 切到项目根目录 → 启动 Claude 跑一次。"""
    args = parse_args()
    check_api_key()
    csv_path, hotels = filter_hotels(args)
    # 必须在 filter_hotels 之后：它要先把相对路径换成完整路径
    os.chdir(PROJECT_DIR)

    transcript_file, session_dir = setup_session()
    transcript = TranscriptWriter(transcript_file)
    tracker = SubagentTracker(transcript_writer=transcript,
                              session_dir=session_dir)
    try:
        asyncio.run(run_claude(build_user_prompt(args, csv_path, hotels),
                               build_claude_options(tracker, csv_path.parent),
                               tracker, transcript))
    finally:
        transcript.close()
        tracker.close()
        print(f"\nSession logs saved to: {session_dir}")
        print(f"Summary: {Path(hotels[0]['work_dir']).parent.parent / 'summary.csv'}")


if __name__ == "__main__":
    main()
