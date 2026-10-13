"""agent.py 的测试。

不会真的调用 DeepSeek：ClaudeSDKClient 一律换成 FakeClient。
import 时把 load_dotenv 换掉，测试不读 .env，也不受它影响。
"""

import argparse
import asyncio
import io
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock
from claude_agent_sdk.types import PermissionResultDeny

with mock.patch("dotenv.load_dotenv"):
    from hotel_checker_agent import agent  # pylint: disable=wrong-import-position
from hotel_checker_agent.utils.hotel_tools import (  # pylint: disable=wrong-import-position
    HOTELS,
    TOOL_NAMES,
)
from hotel_checker_agent.utils.transcript import (  # pylint: disable=wrong-import-position
    TranscriptWriter,
)

CSV = Path(__file__).parent / "data" / "milan_score_8_over_100_reviews.csv"
# 测试 CSV 里 Milan、8.0、>=100 条评论的酒店，按评论数从少到多
FIRST, SECOND = "Atahotel Linea Uno", "Hotel Carrobbio"


def make_args(**changes):
    """命令行参数的默认值：测试 CSV、Milan、8.0、>=100 条、最多 1 家。"""
    values = {"csv": str(CSV), "city": "Milan", "score": 8.0,
              "min_reviews": 100, "max_hotels": 1}
    values.update(changes)
    return argparse.Namespace(**values)


def assistant(text):
    """造一条只有文字的 AssistantMessage。"""
    return AssistantMessage(content=[TextBlock(text)], model="haiku")


class FakeClient:
    """假的 ClaudeSDKClient：记下收到的指令，按顺序吐出 MESSAGES。"""

    MESSAGES = []
    instances = []

    def __init__(self, options):
        self.options = options
        self.prompts = []
        FakeClient.instances.append(self)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False

    async def query(self, prompt):
        """记下发给主 agent 的指令。"""
        self.prompts.append(prompt)

    async def receive_response(self):
        """依次给出事先准备好的消息。"""
        for message in self.MESSAGES:
            yield message


class TestLoadPrompt(unittest.TestCase):
    """load_prompt：读 prompts/ 里的文件，去掉首尾空白。"""

    def test_reads_prompt(self):
        """内容和文件一致，只是去掉了首尾空白。"""
        raw = (agent.PROMPTS_DIR / "lead_agent.txt").read_text(encoding="utf-8")
        self.assertEqual(agent.load_prompt("lead_agent.txt"), raw.strip())

    def test_missing_file(self):
        """文件不存在就报错。"""
        with self.assertRaises(FileNotFoundError):
            agent.load_prompt("nope.txt")


class TestParseArgs(unittest.TestCase):
    """parse_args：读命令行参数。"""

    def parse(self, *argv):
        """用 argv 当命令行参数调用 parse_args。"""
        with mock.patch("sys.argv", ["agent.py", *argv]):
            return agent.parse_args()

    def test_all_args(self):
        """参数转成对应类型。"""
        args = self.parse("--csv", "a.csv", "--city", "Milan", "--score", "8",
                          "--min-reviews", "100", "--max-hotels", "3")
        self.assertEqual(vars(args), {"csv": "a.csv", "city": "Milan",
                                      "score": 8.0, "min_reviews": 100,
                                      "max_hotels": 3})

    def test_max_hotels_default(self):
        """不给 --max-hotels 时默认 1。"""
        args = self.parse("--csv", "a.csv", "--city", "Milan", "--score", "8",
                          "--min-reviews", "100")
        self.assertEqual(args.max_hotels, 1)

    def test_missing_or_bad_args(self):
        """少了必填参数、数字写错，都退出。"""
        cases = [("--csv", "a.csv"),
                 ("--csv", "a.csv", "--city", "Milan", "--score", "high",
                  "--min-reviews", "100")]
        for argv in cases:
            with self.subTest(argv=argv):
                with redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit):
                        self.parse(*argv)

    def test_max_hotels_must_be_positive(self):
        """--max-hotels 是 0、负数、小数、文字都退出，错误信息指出这个参数。"""
        for value in ("0", "-1", "1.5", "abc"):
            with self.subTest(value=value):
                stderr = io.StringIO()
                with redirect_stderr(stderr):
                    with self.assertRaises(SystemExit):
                        self.parse("--csv", "a.csv", "--city", "Milan",
                                   "--score", "8", "--min-reviews", "100",
                                   "--max-hotels", value)
                self.assertIn("--max-hotels", stderr.getvalue())


class TestPositiveInt(unittest.TestCase):
    """positive_int：只接受 >= 1 的整数。"""

    def test_valid(self):
        """正整数转成 int。"""
        for text, expected in (("1", 1), ("25", 25)):
            with self.subTest(text=text):
                self.assertEqual(agent.positive_int(text), expected)

    def test_invalid(self):
        """0、负数、小数、文字、空字符串都报错。"""
        for text in ("0", "-1", "1.5", "abc", ""):
            with self.subTest(text=text):
                with self.assertRaises((argparse.ArgumentTypeError,
                                        ValueError)):
                    agent.positive_int(text)


class TestCheckApiKey(unittest.TestCase):
    """check_api_key：没有 ANTHROPIC_AUTH_TOKEN 就退出。"""

    def test_key_present(self):
        """有 key 时什么都不做。"""
        with mock.patch.dict(os.environ, {"ANTHROPIC_AUTH_TOKEN": "x"},
                             clear=True):
            self.assertIsNone(agent.check_api_key())

    def test_key_missing_or_empty(self):
        """没有或为空都退出，提示里写着变量名。"""
        for env in ({}, {"ANTHROPIC_AUTH_TOKEN": ""}):
            with self.subTest(env=env):
                with mock.patch.dict(os.environ, env, clear=True):
                    with self.assertRaisesRegex(SystemExit,
                                                "ANTHROPIC_AUTH_TOKEN"):
                        agent.check_api_key()


class TestFilterHotels(unittest.TestCase):
    """filter_hotels：检查 CSV 路径，筛酒店并打印清单。"""

    def test_hotels_listed(self):
        """返回筛出的酒店，并逐家打印名字和评论数。"""
        out = io.StringIO()
        with redirect_stdout(out):
            hotels = agent.filter_hotels(make_args(max_hotels=2))
        self.assertEqual([h["hotel"] for h in hotels], [FIRST, SECOND])
        self.assertIn("Hotels to check: 2", out.getvalue())
        self.assertIn(f"  - {FIRST} (119 reviews)", out.getvalue())

    def test_relative_path(self):
        """相对路径也能找到 CSV。"""
        with redirect_stdout(io.StringIO()):
            hotels = agent.filter_hotels(make_args(csv=os.path.relpath(CSV)))
        self.assertEqual(len(hotels), 1)

    def test_csv_missing(self):
        """CSV 不存在（或者给的是文件夹）就退出。"""
        for path in ("no_such.csv", str(CSV.parent)):
            with self.subTest(path=path):
                with self.assertRaisesRegex(SystemExit, "CSV not found"):
                    agent.filter_hotels(make_args(csv=path))

    def test_no_hotels(self):
        """一家都没筛出来就退出。"""
        with self.assertRaisesRegex(SystemExit, "Paris 8.0: 0 hotels found"):
            agent.filter_hotels(make_args(city="Paris"))


class TestBuildUserPrompt(unittest.TestCase):
    """build_user_prompt：发给主 agent 的指令。"""

    def test_prompt(self):
        """酒店数、城市、一位小数的评分，每家酒店一行。"""
        hotels = [{"hotel": FIRST}, {"hotel": SECOND}]
        prompt = agent.build_user_prompt(make_args(score=8), hotels)
        self.assertEqual(prompt.splitlines(), [
            "Check these 2 hotel(s) with the hotel-checker agent.",
            "City: Milan", "Score: 8.0",
            f"Hotel 1: {FIRST}", f"Hotel 2: {SECOND}"])


class TestBuildAgents(unittest.TestCase):
    """build_agents：只有一个 hotel-checker。"""

    def test_hotel_checker(self):
        """只能用 4 个酒店工具，用 hotel_checker.txt 当 prompt。"""
        agents = agent.build_agents()
        self.assertEqual(list(agents), ["hotel-checker"])
        checker = agents["hotel-checker"]
        self.assertEqual(checker.tools, TOOL_NAMES)
        self.assertEqual(checker.model, "sonnet")
        self.assertEqual(checker.prompt,
                         agent.load_prompt("hotel_checker.txt"))


class TestHooks(unittest.IsolatedAsyncioTestCase):
    """hook：主 agent 只能派活；PreToolUse 同时记日志。"""

    async def test_main_agent_may_delegate(self):
        """主 agent 用 Agent 或 Task：放行。"""
        for tool in ("Agent", "Task"):
            with self.subTest(tool=tool):
                result = await agent.main_agent_only_delegates(
                    {"tool_name": tool, "hook_event_name": "PreToolUse"},
                    None, None)
                self.assertEqual(result, {})

    async def test_main_agent_other_tools_denied(self):
        """主 agent 用别的工具（agent_id 为空也算主 agent）：拒绝。"""
        for extra in ({}, {"agent_id": ""}):
            with self.subTest(extra=extra):
                data = {"tool_name": TOOL_NAMES[0],
                        "hook_event_name": "PreToolUse", **extra}
                result = await agent.main_agent_only_delegates(data, "t1",
                                                               None)
                self.assertEqual(result, agent.deny(
                    data, "The main agent may only delegate with the Agent "
                          "tool."))

    async def test_subagent_allowed(self):
        """subagent 的调用这里不管。"""
        result = await agent.main_agent_only_delegates(
            {"tool_name": "Bash", "agent_id": "a1",
             "hook_event_name": "PreToolUse"}, None, None)
        self.assertEqual(result, {})

    def test_deny_shape(self):
        """拒绝回复的格式。"""
        self.assertEqual(agent.deny({"hook_event_name": "PreToolUse"}, "no"), {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": "no",
            }})

    async def test_pre_tool_use_logs_decision(self):
        """先判断，再把是否被拒绝告诉 tracker，返回判断结果。"""
        tracker = mock.Mock(pre_tool_use_hook=mock.AsyncMock())
        hook = agent.make_pre_tool_use(tracker)
        denied = {"tool_name": "Read", "hook_event_name": "PreToolUse",
                  "tool_input": {}}
        allowed = dict(denied, tool_name="Agent")
        self.assertIn("hookSpecificOutput", await hook(denied, "t1", "ctx"))
        self.assertEqual(await hook(allowed, "t2", "ctx"), {})
        self.assertEqual(tracker.pre_tool_use_hook.await_args_list, [
            mock.call(denied, "t1", "ctx", denied=True),
            mock.call(allowed, "t2", "ctx", denied=False)])

    async def test_deny_all_requests(self):
        """can_use_tool 一律拒绝，并打印工具名。"""
        out = io.StringIO()
        with redirect_stdout(out):
            result = await agent.deny_all_requests("WebFetch", {}, None)
        self.assertIsInstance(result, PermissionResultDeny)
        self.assertEqual(result.message, "WebFetch is not allowed in this run.")
        self.assertIn("[auto-deny] WebFetch", out.getvalue())


class TestBuildClaudeOptions(unittest.TestCase):
    """build_claude_options：Claude 的设置单。"""

    @classmethod
    def setUpClass(cls):
        cls.options = agent.build_claude_options(mock.Mock())

    def test_tools_and_permissions(self):
        """自带工具只留 Task；免问的是派活 + 4 个酒店工具；其他一律拒绝。"""
        self.assertEqual(self.options.tools, ["Task"])
        self.assertEqual(self.options.allowed_tools, ["Agent", *TOOL_NAMES])
        self.assertEqual(self.options.permission_mode, "default")
        self.assertIs(self.options.can_use_tool, agent.deny_all_requests)

    def test_model_prompt_and_dirs(self):
        """主 agent 用 haiku 和 lead_agent.txt，在项目根目录运行。"""
        self.assertEqual(self.options.model, "haiku")
        self.assertEqual(self.options.system_prompt,
                         agent.load_prompt("lead_agent.txt"))
        self.assertEqual(self.options.cwd, str(agent.PROJECT_DIR))
        self.assertEqual(self.options.setting_sources, ["project"])

    def test_servers_agents_env(self):
        """酒店 MCP 服务器、hotel-checker、两个关闭开关都在。"""
        self.assertEqual(list(self.options.mcp_servers), ["hotel"])
        self.assertEqual(list(self.options.agents), ["hotel-checker"])
        self.assertEqual(self.options.env, {
            "CLAUDE_CODE_DISABLE_BACKGROUND_TASKS": "1",
            "CLAUDE_AGENT_SDK_DISABLE_BUILTIN_AGENTS": "1"})

    def test_hooks(self):
        """三种 hook 各一个。"""
        self.assertEqual(set(self.options.hooks),
                         {"PreToolUse", "PostToolUse", "PostToolUseFailure"})
        for matchers in self.options.hooks.values():
            self.assertEqual(len(matchers), 1)
            self.assertEqual(len(matchers[0].hooks), 1)


class AgentTestCase(unittest.TestCase):
    """把 ClaudeSDKClient 换成 FakeClient，并准备一个临时文件夹。"""

    def setUp(self):
        FakeClient.MESSAGES = []
        FakeClient.instances = []
        patcher = mock.patch.object(agent, "ClaudeSDKClient", FakeClient)
        patcher.start()
        self.addCleanup(patcher.stop)
        tmp = tempfile.TemporaryDirectory()  # pylint: disable=consider-using-with
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.addCleanup(HOTELS.clear)


class TestRunClaude(AgentTestCase):
    """run_claude：发一次指令，只处理 AssistantMessage。"""

    def test_run(self):
        """指令记进文件，回复打印出来，非 AssistantMessage 跳过。"""
        FakeClient.MESSAGES = [
            assistant("Done."),
            ResultMessage(subtype="success", duration_ms=1, duration_api_ms=1,
                          is_error=False, num_turns=1, session_id="s"),
        ]
        options = object()
        transcript = TranscriptWriter(self.tmp / "t.txt")
        with redirect_stdout(io.StringIO()) as out, \
                mock.patch.object(agent, "process_assistant_message",
                                  wraps=agent.process_assistant_message) as spy:
            asyncio.run(agent.run_claude("Check it", options, mock.Mock(),
                                         transcript))
        transcript.close()
        client = FakeClient.instances[0]
        self.assertIs(client.options, options)
        self.assertEqual(client.prompts, ["Check it"])
        self.assertEqual(spy.call_count, 1)
        self.assertEqual(out.getvalue(), "\nAgent: Done.\n")
        self.assertEqual((self.tmp / "t.txt").read_text(encoding="utf-8"),
                         "\nTask:\nCheck it\n\nAgent: Done.\n")


class TestMain(AgentTestCase):
    """main：从读参数到跑完 Claude 的整个流程（Claude 是假的）。"""

    def setUp(self):
        super().setUp()
        self.session_dir = self.tmp / "session"
        self.session_dir.mkdir()
        argv = ["agent.py", "--csv", str(CSV), "--city", "Milan",
                "--score", "8", "--min-reviews", "100"]
        for patcher in (
                mock.patch("sys.argv", argv),
                mock.patch.dict(os.environ, {"ANTHROPIC_AUTH_TOKEN": "x"}),
                mock.patch.object(agent.os, "chdir"),
                mock.patch.object(agent, "setup_session", return_value=(
                    self.session_dir / "transcript.txt", self.session_dir))):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_main(self):
        """酒店装进内存，指令发给主 agent，最后打印日志和总表的位置。"""
        FakeClient.MESSAGES = [assistant("All done.")]
        out = io.StringIO()
        with redirect_stdout(out):
            agent.main()
        agent.os.chdir.assert_called_once_with(agent.PROJECT_DIR)
        self.assertEqual(list(HOTELS), [FIRST])
        self.assertIn(f"Hotel 1: {FIRST}", FakeClient.instances[0].prompts[0])
        self.assertTrue(
            (self.session_dir / "tool_calls.jsonl").exists())
        self.assertIn("All done.", (self.session_dir / "transcript.txt")
                      .read_text(encoding="utf-8"))
        summary = agent.PROJECT_DIR / "runs" / "Milan" / "summary.csv"
        self.assertIn(f"Session logs saved to: {self.session_dir}",
                      out.getvalue())
        self.assertIn(f"Summary: {summary}", out.getvalue())

    def test_files_closed_on_error(self):
        """Claude 出错时，两个日志文件照样关好，错误照常抛出。"""
        made = []

        def keep(cls):
            """照常创建对象，同时记下来，测完检查文件关了没有。"""
            def create(*args, **kwargs):
                made.append(cls(*args, **kwargs))
                return made[-1]
            return create

        with redirect_stdout(io.StringIO()), \
                mock.patch.object(FakeClient, "query",
                                  side_effect=RuntimeError("boom")), \
                mock.patch.object(agent, "TranscriptWriter",
                                  side_effect=keep(TranscriptWriter)), \
                mock.patch.object(agent, "SubagentTracker",
                                  side_effect=keep(agent.SubagentTracker)):
            with self.assertRaisesRegex(RuntimeError, "boom"):
                agent.main()
        self.assertEqual(len(made), 2)
        self.assertTrue(made[0].file.closed)
        self.assertTrue(made[1].tool_log_file.closed)

    def test_no_key_stops_early(self):
        """没有 key 时在筛酒店之前就退出，不启动 Claude。"""
        with mock.patch.dict(os.environ, {"ANTHROPIC_AUTH_TOKEN": ""}):
            with self.assertRaises(SystemExit):
                agent.main()
        self.assertEqual(FakeClient.instances, [])
        self.assertEqual(HOTELS, {})


if __name__ == "__main__":
    unittest.main()
