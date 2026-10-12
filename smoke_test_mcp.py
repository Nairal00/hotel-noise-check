"""Smoke test：确认 subagent 能用 SDK 自定义工具（plan.md 7.5）。

会调用 DeepSeek，花一点钱。在项目根目录运行：
    .venv/bin/python smoke_test_mcp.py
跑完、记下结果后删掉这个文件（plan.md 第 2 节"删除"）。
"""

import asyncio
from typing import Any

from claude_agent_sdk import (
    AgentDefinition,
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    HookMatcher,
    ResultMessage,
    SystemMessage,
    TextBlock,
    ToolUseBlock,
    create_sdk_mcp_server,
    tool,
)
from claude_agent_sdk.types import PermissionResultDeny

from research_agent.agent import (
    PROJECT_DIR,
    check_api_key,
    main_agent_only_delegates,
)

HOTEL = "Test Hotel"
TOOL = "mcp__smoke__add_note"  # AI 看到的全名：mcp__<服务器名>__<工具名>

# 工具存在内存里的数据：酒店名 -> 记下的 note
NOTES: dict[str, list[str]] = {}
# 运行中发生的事，跑完后由 Python 检查，不靠 AI 自己说
EVENTS: list[dict] = []
ASKED: list[str] = []  # 走到 can_use_tool 的工具名
RESULT: dict[str, Any] = {"init_tools": [], "subtype": None}

LEAD_PROMPT = """You are running a smoke test of tool permissions. \
Follow these steps exactly.
STEP 1: Call the tool mcp__smoke__add_note yourself with hotel "Test Hotel" \
and note "from lead". It is expected to be blocked. Whatever happens, go on.
STEP 2: Use the Agent tool with subagent_type "smoke-checker", \
description "Smoke check", prompt "Run your steps." Wait for its reply.
STEP 3: Reply with only these lines:
lead_tools: <comma-separated names of every tool you have>
step1: <the exact text you got back in step 1>
subagent_reply:
<the subagent's reply, copied exactly>"""

SUB_PROMPT = """You are a smoke-test agent. Do these steps in order, \
one tool call at a time.
1. Call mcp__smoke__add_note with hotel "Test Hotel" and note "first".
2. Call mcp__smoke__add_note with hotel "Test Hotel" and note "second".
3. Call mcp__smoke__add_note with hotel "Wrong Hotel" and note "x". \
An error is expected. Do not retry.
4. Reply with only these lines:
tools: <comma-separated names of every tool you have>
step2: <exact text returned by step 2>
step3: <exact text returned by step 3>"""


@tool("add_note", "Save a note for a hotel and return all notes saved so far.",
      {"hotel": str, "note": str})
async def add_note(args: dict[str, Any]) -> dict[str, Any]:
    """工具：酒店名不对就报错退回；对就存下 note，返回目前存下的全部 note。"""
    if args["hotel"] != HOTEL:
        return {"content": [{"type": "text",
                             "text": f"Unknown hotel: {args['hotel']}"}],
                "is_error": True}
    NOTES.setdefault(HOTEL, []).append(args["note"])
    return {"content": [{"type": "text",
                         "text": f"notes so far: {NOTES[HOTEL]}"}]}


def who(input_data: dict) -> str:
    """hook 输入里有 agent_id 就是 subagent，没有就是 lead。"""
    return "sub" if input_data.get("agent_id") else "lead"


def record(event: str, input_data: dict, detail: str) -> None:
    """把一次工具事件记进 EVENTS，并打印出来。"""
    EVENTS.append({"event": event, "who": who(input_data),
                   "tool": input_data["tool_name"], "detail": detail})
    print(f"\n[{event}] {who(input_data)} {input_data['tool_name']}: {detail}")


async def pre_hook(input_data: dict, tool_use_id: str | None,
                   context: Any) -> dict:
    """PreToolUse：用 agent.py 里真正的 hook 判断，再记下它的决定。"""
    result = await main_agent_only_delegates(input_data, tool_use_id, context)
    record("pre", input_data, "deny" if result else "allow")
    return result


async def post_hook(input_data: dict, tool_use_id: str | None,
                    context: Any) -> dict:
    """PostToolUse：记下工具的返回内容。"""
    del tool_use_id, context  # SDK 规定要有这两个参数，这里用不到
    record("post", input_data, str(input_data.get("tool_response"))[:200])
    return {}


async def failure_hook(input_data: dict, tool_use_id: str | None,
                       context: Any) -> dict:
    """PostToolUseFailure：记下失败原因（看 is_error 会不会触发它）。"""
    del tool_use_id, context  # SDK 规定要有这两个参数，这里用不到
    record("failure", input_data, str(input_data.get("error"))[:200])
    return {}


async def record_and_deny(tool_name: str, input_data: dict,
                          context: Any) -> PermissionResultDeny:
    """can_use_tool：记下是哪个工具走到了这里，然后拒绝。"""
    del input_data, context  # SDK 规定要有这两个参数，这里用不到
    ASKED.append(tool_name)
    print(f"\n[can_use_tool] {tool_name} -> deny")
    return PermissionResultDeny(message=f"{tool_name} is not allowed.")


def build_options() -> ClaudeAgentOptions:
    """和 plan 7.4 的设置一样，只是工具换成 1 个测试工具。"""
    server = create_sdk_mcp_server(name="smoke", tools=[add_note])
    return ClaudeAgentOptions(
        cwd=str(PROJECT_DIR),
        setting_sources=["project"],
        system_prompt=LEAD_PROMPT,
        model="haiku",
        tools=["Task"],  # 只管自带工具：去掉 Bash、Read 等。这里要写旧名 Task
        allowed_tools=["Agent", TOOL],
        mcp_servers={"smoke": server},
        agents={
            "smoke-checker": AgentDefinition(
                description="Runs the smoke-test steps with add_note.",
                prompt=SUB_PROMPT,
                tools=[TOOL],
                model="sonnet",
            ),
        },
        hooks={
            "PreToolUse": [HookMatcher(hooks=[pre_hook])],
            "PostToolUse": [HookMatcher(hooks=[post_hook])],
            "PostToolUseFailure": [HookMatcher(hooks=[failure_hook])],
        },
        permission_mode="default",
        can_use_tool=record_and_deny,
        env={
            "CLAUDE_CODE_DISABLE_BACKGROUND_TASKS": "1",
            "CLAUDE_AGENT_SDK_DISABLE_BUILTIN_AGENTS": "1",
        },
    )


def show(msg: Any) -> None:
    """打印收到的消息；init 消息里的工具列表存进 RESULT。"""
    if isinstance(msg, SystemMessage) and msg.subtype == "init":
        RESULT["init_tools"] = msg.data.get("tools", [])
        print(f"[init] tools: {RESULT['init_tools']}")
    elif isinstance(msg, AssistantMessage):
        speaker = "sub" if msg.parent_tool_use_id else "lead"
        for block in msg.content:
            if isinstance(block, TextBlock):
                print(f"\n[{speaker} text] {block.text}")
            elif isinstance(block, ToolUseBlock):
                print(f"\n[{speaker} calls] {block.name} {block.input}")
    elif isinstance(msg, ResultMessage):
        RESULT["subtype"] = msg.subtype
        print(f"\n[result] {msg.subtype}\n{msg.result}")


async def run() -> None:
    """发一次指令，收完回复就结束。"""
    async with ClaudeSDKClient(options=build_options()) as client:
        await client.query(prompt="Run the smoke test now.")
        async for msg in client.receive_response():
            show(msg)


def pre_calls(agent: str, tool_name: str) -> list[dict]:
    """找出某个 agent 对某个工具的全部 PreToolUse 记录。"""
    return [e for e in EVENTS if e["event"] == "pre"
            and e["who"] == agent and e["tool"] == tool_name]


def report() -> None:
    """跑完后用 Python 逐条核对 plan 7.5 的几件事。"""
    init_tools = set(RESULT["init_tools"])
    lead_calls = pre_calls("lead", TOOL)
    sub_builtins = [e["tool"] for e in EVENTS
                    if e["who"] == "sub" and e["tool"] in ("Bash", "Read")]
    wrong_hotel = [e for e in EVENTS if e["who"] == "sub"
                   and e["event"] in ("post", "failure")
                   and "Unknown hotel" in e["detail"]]
    if not lead_calls:
        lead_check = "NOT TESTED (lead did not call the tool)"
    elif all(e["detail"] == "deny" for e in lead_calls):
        lead_check = "PASS"
    else:
        lead_check = "FAIL"

    def mark(ok: bool) -> str:
        return "PASS" if ok else "FAIL"

    print("\n========== checks ==========")
    print(f"1 subagent called the tool:       {mark(bool(pre_calls('sub', TOOL)))}")
    print(f"2 data kept between calls:        "
          f"{mark(NOTES.get(HOTEL) == ['first', 'second'])}  {NOTES}")
    print(f"3a lead has no Bash/Read (init):  "
          f"{mark(bool(init_tools) and not {'Bash', 'Read'} & init_tools)}")
    print(f"3b lead has Agent/Task (init):    "
          f"{mark(bool({'Agent', 'Task'} & init_tools))}")
    print(f"3c subagent used no Bash/Read:    {mark(not sub_builtins)}")
    print(f"4 lead call denied by hook:       {lead_check}")
    print(f"5 tool never reached can_use_tool: {mark(TOOL not in ASKED)}  "
          f"asked={ASKED}")
    print(f"6 ToolSearch in init tools:       {'ToolSearch' in init_tools}  "
          f"(info only)")
    print(f"7 wrong hotel returned an error:  {mark(bool(wrong_hotel))}  "
          f"via {[e['event'] for e in wrong_hotel]}")
    print(f"8 run finished:                   "
          f"{mark(RESULT['subtype'] == 'success')}  ({RESULT['subtype']})")


def main() -> None:
    """检查 key → 跑一次 → 不管成功失败都打印核对结果。"""
    check_api_key()
    try:
        asyncio.run(run())
    finally:
        report()


if __name__ == "__main__":
    main()
