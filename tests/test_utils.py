"""utils/ 里 subagent_tracker、message_handler、transcript 的测试。"""

# 这里专门测以 _ 开头的内部函数和 message_handler 的全局变量
# pylint: disable=protected-access

import io
import json
import logging
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from claude_agent_sdk import AssistantMessage, TextBlock, ToolUseBlock

from hotel_checker_agent.utils import message_handler
from hotel_checker_agent.utils.message_handler import process_assistant_message
from hotel_checker_agent.utils.subagent_tracker import SubagentTracker
from hotel_checker_agent.utils.transcript import (
    TranscriptWriter,
    setup_session,
)

TRACKER_LOGGER = "hotel_checker_agent.utils.subagent_tracker"


def temp_dir(case):
    """给测试建一个临时文件夹，测完自动删除。"""
    tmp = tempfile.TemporaryDirectory()  # pylint: disable=consider-using-with
    case.addCleanup(tmp.cleanup)
    return Path(tmp.name)


def message(*blocks):
    """把几个 block 包成一条 AssistantMessage。"""
    return AssistantMessage(content=list(blocks), model="haiku")


# ---------------- transcript.py ----------------

class TestSetupSession(unittest.TestCase):
    """setup_session：在当前目录的 logs/ 下建 session 文件夹。"""

    def setUp(self):
        tmp = temp_dir(self)
        self.addCleanup(os.chdir, os.getcwd())
        os.chdir(tmp)

    def test_creates_session_dir(self):
        """文件夹名带时间；只给 transcript 路径，不建文件。"""
        transcript_file, session_dir = setup_session()
        self.assertRegex(session_dir.as_posix(), r"^logs/session_\d{8}_\d{6}$")
        self.assertTrue(session_dir.is_dir())
        self.assertEqual(transcript_file, session_dir / "transcript.txt")
        self.assertFalse(transcript_file.exists())

    def test_quiet_urllib3(self):
        """urllib3 的日志调到 WARNING。"""
        setup_session()
        self.assertEqual(logging.getLogger("urllib3").level, logging.WARNING)


class TestTranscriptWriter(unittest.TestCase):
    """TranscriptWriter：同时写屏幕和文件，或只写文件。"""

    def setUp(self):
        self.path = temp_dir(self) / "transcript.txt"

    def read(self):
        """读 transcript 文件的内容。"""
        return self.path.read_text(encoding="utf-8")

    def test_write(self):
        """屏幕和文件都有，默认马上写进文件（不用等 close）。"""
        writer = TranscriptWriter(self.path)
        self.addCleanup(writer.close)
        with redirect_stdout(io.StringIO()) as out:
            writer.write("hi")
            writer.write("there", end="\n")
        self.assertEqual(out.getvalue(), "hithere\n")
        self.assertEqual(self.read(), "hithere\n")

    def test_write_to_file(self):
        """只写文件，屏幕上没有。"""
        writer = TranscriptWriter(self.path)
        self.addCleanup(writer.close)
        with redirect_stdout(io.StringIO()) as out:
            writer.write_to_file("secret\n")
        self.assertEqual(out.getvalue(), "")
        self.assertEqual(self.read(), "secret\n")

    def test_no_flush(self):
        """flush=False 时 close 之后也都写进去了。"""
        writer = TranscriptWriter(self.path)
        with redirect_stdout(io.StringIO()):
            writer.write("a", flush=False)
        writer.write_to_file("b", flush=False)
        writer.close()
        self.assertEqual(self.read(), "ab")

    def test_with_block(self):
        """with 结束时关闭文件；里面出的错照常抛出。"""
        with self.assertRaises(KeyError):
            with TranscriptWriter(self.path) as writer:
                writer.write_to_file("x")
                raise KeyError("boom")
        self.assertTrue(writer.file.closed)
        self.assertEqual(self.read(), "x")


# ---------------- message_handler.py ----------------

class TestProcessAssistantMessage(unittest.TestCase):
    """process_assistant_message：打印文字，登记 subagent。"""

    def setUp(self):
        # _tool_just_used 是模块级变量，每个测试前先复原
        message_handler._tool_just_used = False
        self.addCleanup(setattr, message_handler, "_tool_just_used", False)
        self.tracker = mock.Mock()
        self.tracker.register_subagent_spawn.return_value = "HOTEL-CHECKER-1"
        self.transcript = mock.Mock()

    def process(self, *blocks):
        """处理一条由 blocks 组成的消息。"""
        process_assistant_message(message(*blocks), self.tracker,
                                  self.transcript)

    def test_text(self):
        """文字原样写出，不加换行。"""
        self.process(TextBlock("Hello"), TextBlock(" world"))
        self.assertEqual(self.transcript.write.call_args_list,
                         [mock.call("Hello", end=""),
                          mock.call(" world", end="")])

    def test_spawn_registered(self):
        """Agent 和 Task 都算派活：登记 subagent，打印它的编号。"""
        for name in ("Agent", "Task"):
            with self.subTest(name=name):
                self.transcript.reset_mock()
                self.process(ToolUseBlock("t1", name, {
                    "subagent_type": "hotel-checker",
                    "description": "Check Hotel Mozart",
                    "prompt": "Hotel Mozart"}))
                self.tracker.register_subagent_spawn.assert_called_with(
                    tool_use_id="t1", subagent_type="hotel-checker",
                    description="Check Hotel Mozart", prompt="Hotel Mozart")
                self.transcript.write.assert_called_once_with(
                    "\n\n[Spawning HOTEL-CHECKER-1: Check Hotel Mozart]\n",
                    end="")

    def test_spawn_defaults(self):
        """派活时缺字段，用默认值。"""
        self.process(ToolUseBlock("t1", "Agent", {}))
        self.tracker.register_subagent_spawn.assert_called_once_with(
            tool_use_id="t1", subagent_type="unknown",
            description="no description", prompt="")

    def test_other_tools_ignored(self):
        """别的工具不登记，也不打印。"""
        self.process(ToolUseBlock("t1", "mcp__hotel__next_batch", {}))
        self.tracker.register_subagent_spawn.assert_not_called()
        self.transcript.write.assert_not_called()

    def test_newline_after_tool(self):
        """用过工具之后的第一段文字前面先换行，只换一次，跨消息也算。"""
        self.process(ToolUseBlock("t1", "mcp__hotel__next_batch", {}))
        self.process(TextBlock("a"), TextBlock("b"))
        self.assertEqual(self.transcript.write.call_args_list,
                         [mock.call("\n", end=""), mock.call("a", end=""),
                          mock.call("b", end="")])


# ---------------- subagent_tracker.py ----------------

class TestRegisterSubagentSpawn(unittest.TestCase):
    """register_subagent_spawn：给每个 subagent 编号并记下来。"""

    def setUp(self):
        self.tracker = SubagentTracker()

    def test_numbered_by_type(self):
        """同类型从 1 开始往上数，不同类型分开数。"""
        ids = [self.tracker.register_subagent_spawn(f"t{i}", kind, "d", "p")
               for i, kind in enumerate(["hotel-checker", "hotel-checker",
                                         "other"])]
        self.assertEqual(ids, ["HOTEL-CHECKER-1", "HOTEL-CHECKER-2",
                               "OTHER-1"])
        self.assertEqual(self.tracker.sessions["t1"].subagent_id,
                         "HOTEL-CHECKER-2")

    def test_prompt_preview(self):
        """prompt 超过 200 个字只留前 200 个加 ...，不超过的照抄。"""
        for prompt, preview in (("a" * 200, "a" * 200),
                                ("a" * 201, "a" * 200 + "...")):
            with self.subTest(length=len(prompt)):
                self.tracker.register_subagent_spawn("t", "x", "d", prompt)
                self.assertEqual(self.tracker.sessions["t"].prompt_preview,
                                 preview)


class TestAgentInfo(unittest.TestCase):
    """_agent_info：只看 hook 输入就知道是谁调用的工具。"""

    def setUp(self):
        self.tracker = SubagentTracker()

    def test_main_agent(self):
        """没有 agent_id（或为空）就是主 agent。"""
        for hook_input in ({}, {"agent_id": ""}, {"agent_id": None}):
            with self.subTest(hook_input=hook_input):
                self.assertEqual(self.tracker._agent_info(hook_input),
                                 ("MAIN_AGENT", "lead"))

    def test_labels_in_order(self):
        """按第一次出现的顺序编号，同一个 agent_id 一直用同一个编号。"""
        labels = [self.tracker._agent_info({"agent_id": a,
                                            "agent_type": "hotel-checker"})[0]
                  for a in ("x", "y", "x")]
        self.assertEqual(labels, ["HOTEL-CHECKER-1", "HOTEL-CHECKER-2",
                                  "HOTEL-CHECKER-1"])

    def test_missing_type(self):
        """没有 agent_type 时类型算 unknown。"""
        self.assertEqual(self.tracker._agent_info({"agent_id": "x"}),
                         ("UNKNOWN-1", "unknown"))


class TestFormatToolInput(unittest.TestCase):
    """_format_tool_input：把工具参数缩成一行好读的文字。"""

    def test_formats(self):
        """每种参数各有写法，太长的截断。"""
        cases = [
            ({}, ""),
            (None, ""),
            ({"query": "hotel noise"}, "query='hotel noise'"),
            ({"query": "q" * 101}, f"query='{'q' * 100}...'"),
            ({"file_path": "/a/b/c.txt", "content": "hello"},
             "file='c.txt' (5 chars)"),
            ({"file_path": "/a/b/c.txt"}, "path='/a/b/c.txt'"),
            ({"pattern": "*.py"}, "pattern='*.py'"),
            ({"subagent_type": "hotel-checker", "description": "Mozart"},
             "spawn=hotel-checker (Mozart)"),
            ({"hotel": "Mozart"}, "{'hotel': 'Mozart'}"),
            ({"hotel": "m" * 200}, str({"hotel": "m" * 200})[:100]),
        ]
        tracker = SubagentTracker()
        for tool_input, expected in cases:
            with self.subTest(tool_input=tool_input):
                self.assertEqual(tracker._format_tool_input(tool_input),
                                 expected)


class TestLogToolUse(unittest.TestCase):
    """_log_tool_use：有 transcript 就写 transcript，没有就打印。"""

    def test_with_writer(self):
        """屏幕和文件写一行，参数只写进文件。"""
        writer = mock.Mock()
        SubagentTracker(transcript_writer=writer)._log_tool_use(
            "HOTEL-CHECKER-1", "Read", {"file_path": "a.txt"})
        writer.write.assert_called_once_with("\n[HOTEL-CHECKER-1] → Read")
        writer.write_to_file.assert_called_once_with("    Input: path='a.txt'\n")

    def test_with_writer_no_input(self):
        """没有参数就不写 Input 行。"""
        writer = mock.Mock()
        SubagentTracker(transcript_writer=writer)._log_tool_use("X", "Read")
        writer.write_to_file.assert_not_called()

    def test_without_writer(self):
        """没有 transcript 就直接打印。"""
        with redirect_stdout(io.StringIO()) as out:
            SubagentTracker()._log_tool_use("X", "Read", {"file_path": "a"})
        self.assertEqual(out.getvalue(), "\n[X] → Read\n")


class TestTrackerHooks(unittest.IsolatedAsyncioTestCase):
    """三个 hook：记日志，写 tool_calls.jsonl。"""

    def setUp(self):
        self.session_dir = temp_dir(self)
        self.writer = mock.Mock()
        self.tracker = SubagentTracker(transcript_writer=self.writer,
                                       session_dir=self.session_dir)
        self.addCleanup(self.tracker.close)

    def events(self):
        """读出 tool_calls.jsonl 里的每一条记录。"""
        path = self.session_dir / "tool_calls.jsonl"
        with open(path, encoding="utf-8") as f:
            return [json.loads(line) for line in f]

    @staticmethod
    def hook_input(tool_name="mcp__hotel__next_batch", agent_id="a1", **extra):
        """造一份 hook 输入；agent_id 为 None 表示主 agent。"""
        data = {"tool_name": tool_name, "tool_input": {"hotel": "Mozart"},
                **extra}
        if agent_id:
            data.update(agent_id=agent_id, agent_type="hotel-checker")
        return data

    async def test_pre_main_agent_spawn_skipped(self):
        """主 agent 派活不在这里记（消息流里已经记了）。"""
        for tool in ("Agent", "Task"):
            result = await self.tracker.pre_tool_use_hook(
                self.hook_input(tool, agent_id=None), "t1", None)
            self.assertEqual(result, {"continue_": True})
        self.assertEqual(self.events(), [])
        self.writer.write.assert_not_called()

    async def test_pre_subagent(self):
        """subagent 的调用：打印编号和工具名，记一条 tool_call_start。"""
        result = await self.tracker.pre_tool_use_hook(self.hook_input(),
                                                      "t1", None)
        self.assertEqual(result, {"continue_": True})
        self.writer.write.assert_called_once_with(
            "\n[HOTEL-CHECKER-1] → mcp__hotel__next_batch")
        [event] = self.events()
        self.assertEqual(event.pop("event"), "tool_call_start")
        self.assertTrue(event.pop("timestamp"))
        self.assertEqual(event, {
            "tool_use_id": "t1", "agent_id": "HOTEL-CHECKER-1",
            "agent_type": "hotel-checker",
            "tool_name": "mcp__hotel__next_batch",
            "tool_input": {"hotel": "Mozart"}})

    async def test_pre_denied(self):
        """被拒绝的调用：工具名后面加 (denied)，记 tool_call_denied。"""
        await self.tracker.pre_tool_use_hook(
            self.hook_input("Read", agent_id=None), "t1", None, denied=True)
        self.writer.write.assert_called_once_with(
            "\n[MAIN AGENT] → Read (denied)")
        [event] = self.events()
        self.assertEqual((event["event"], event["agent_id"]),
                         ("tool_call_denied", "MAIN_AGENT"))

    async def test_post_success(self):
        """成功：success 为真，output_size 是结果转文字后的长度。"""
        response = {"content": "ok"}
        await self.tracker.post_tool_use_hook(
            self.hook_input(tool_response=response), "t1", None)
        [event] = self.events()
        self.assertEqual(event["event"], "tool_call_complete")
        self.assertEqual((event["success"], event["error"],
                          event["output_size"]),
                         (True, None, len(str(response))))

    async def test_post_other_responses(self):
        """结果不是字典或者没有：不算出错；没有结果时大小是 0。"""
        for response, size in (("text", 4), (None, 0)):
            with self.subTest(response=response):
                await self.tracker.post_tool_use_hook(
                    self.hook_input(tool_response=response), "t1", None)
                event = self.events()[-1]
                self.assertEqual((event["success"], event["output_size"]),
                                 (True, size))

    async def test_post_error(self):
        """结果里有 error：success 为假，打一条 warning。"""
        with self.assertLogs(TRACKER_LOGGER, logging.WARNING) as logs:
            await self.tracker.post_tool_use_hook(
                self.hook_input(tool_response={"error": "bad"}), "t1", None)
        self.assertIn("error: bad", logs.output[0])
        [event] = self.events()
        self.assertEqual((event["success"], event["error"]), (False, "bad"))

    async def test_post_main_agent_spawn_skipped(self):
        """主 agent 派活的结果不记。"""
        await self.tracker.post_tool_use_hook(
            self.hook_input("Agent", agent_id=None, tool_response="x"),
            "t1", None)
        self.assertEqual(self.events(), [])

    async def test_failure(self):
        """工具失败：打 warning，transcript 记原因，记 tool_call_failed。"""
        with self.assertLogs(TRACKER_LOGGER, logging.WARNING):
            result = await self.tracker.post_tool_use_failure_hook(
                self.hook_input(error="Unknown hotel"), "t1", None)
        self.assertEqual(result, {"continue_": True})
        self.writer.write_to_file.assert_called_once_with(
            "    Failed: Unknown hotel\n")
        [event] = self.events()
        self.assertEqual((event["event"], event["error"]),
                         ("tool_call_failed", "Unknown hotel"))

    async def test_failure_without_writer(self):
        """没有 transcript、没有日志文件时也不出错。"""
        tracker = SubagentTracker()
        with self.assertLogs(TRACKER_LOGGER, logging.WARNING):
            await tracker.post_tool_use_failure_hook(self.hook_input(),
                                                     "t1", None)


class TestClose(unittest.TestCase):
    """close：关掉 tool_calls.jsonl。"""

    def test_close(self):
        """有日志文件就关掉；没有也不出错。"""
        tracker = SubagentTracker(session_dir=temp_dir(self))
        tracker.close()
        self.assertTrue(tracker.tool_log_file.closed)
        SubagentTracker().close()


if __name__ == "__main__":
    unittest.main()
