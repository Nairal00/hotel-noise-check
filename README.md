# 酒店静不静（怕吵星人专用）

Agent帮怕吵的人挑酒店：自动读差评，判断这家酒店到底吵不吵。

## 项目亮点

1. **靠代码把关，而不是靠Agent**
   - **证据必须是原话：** AI 每判定一条真实噪音相关差评，都要引用原文，代码会去原文里核对，对不上就打回。
   - **不能乱填：** 分类只能从固定选项里选
   - **数据不经 Agent 转手：** 评论直接从 CSV 交给工具，agent 之间只传酒店名，名字写错会直接报错。
2. **每一步都方便事后追溯和审核**
   - **判断有据可查：** 生成报告每条判断都附上原文引用、理由，以及在原数据的行号。
   - **关键词有来由：** AI 补充的每个关键词，都写明了为什么选它、新增关键词多找到了几条评论。
   - **操作全程留痕：** 日志记录每个 agent 的每一步操作，包括被拦下、被打回的。

## 后续计划

1. **多家酒店横向比较：** 主 agent 汇总各家酒店的结果，放在一起比较，再给出推荐。
2. **接入 Google Maps 交叉验证：** 通过 MCP 连上 Google Maps
   - **多一个独立信源：** 不只依赖这份数据集里的评论，还能用 Google Maps上的信息来对照。
   - **看得到周边和交通：** 比如附近有没有大马路、铁路、酒吧街，帮助判断和验证噪音从哪里来。
## 工作流程

1. **[脚本] 筛酒店：** 按你设定的条件（城市、酒店平均评分和实际评论数），挑出要查的酒店。
2. **[主 agent] 派活：** 每家酒店交给一个 subagent。
3. **[subagent] 找差评：** 先用 3 个固定关键词搜，再自己补 7 个关键词，把漏掉的差评找出来。
4. **[subagent] 逐条判断：** 这条是不是在说噪音？如果是，换个房间能不能解决（可以 / 不可以 / 无法判断）？
5. **[脚本] 出报告：** 生成 Excel 报告。


## Workflow:

[Script]Filter hotels: Script filters hotels by city, average score and number of reviews by users' criteria
[Main agent]Hand out the work: for each hotel, the main agent hands the work to a specialized subagent.
[Subagent]Find reviews: the subagent finds the relevant negative reviews, using a fixed set of keywords(3  words) plus keywords (7 words) it adds itself.
[Subagent]Judge each review: one by one, is it about noise? If so, can a guest avoid it by changing rooms (avoidable, unavoidable or unclear)?
[Script]Report: Script calculates the verdict and writes an Excel report with the subagent’s summary.



## Quick Start

```bash
# Create a virtual environment (Python 3.10+, tested with 3.12)
python3.12 -m venv .venv

# Install dependencies
.venv/bin/pip install -r requirements-lock.txt

# Set your API key: copy the template, then fill in your DeepSeek key
cp .env.example .env

# Run the agent (from the project root)
.venv/bin/python -m hotel_checker_agent.agent \
    --csv path/to/Hotel_Reviews.csv \
    --city Milan --score 8.0 --min-reviews 100
```

- **Data:** `Hotel_Reviews.csv` (238 MB) Download it from Kaggle: [515K Hotel Reviews Data in Europe](https://www.kaggle.com/datasets/jiashenliu/515k-hotel-reviews-data-in-europe).
- **Model:** the code asks for `sonnet` / `haiku`, and `.env` maps both to DeepSeek models. `.env` needs the 7 variables from [DeepSeek: Integrate with Claude Code](https://api-docs.deepseek.com/quick_start/agent_integrations/claude_code) (`ANTHROPIC_BASE_URL`, `ANTHROPIC_AUTH_TOKEN`, `ANTHROPIC_MODEL`, `ANTHROPIC_DEFAULT_OPUS_MODEL`, `ANTHROPIC_DEFAULT_SONNET_MODEL`, `ANTHROPIC_DEFAULT_HAIKU_MODEL`, `CLAUDE_CODE_SUBAGENT_MODEL`). To switch back to Claude, change `.env` only.
- **Run with `-m` from the project root.** `python hotel_checker_agent/agent.py` fails with `ModuleNotFoundError`.
- **Cost:** every run calls the DeepSeek API. Check the real cost in the DeepSeek console; the SDK's cost estimate is not reliable for DeepSeek models.

## How It Works

1. **Python picks the hotels** (no API cost): city, exact `Average_Score`, and at least `--min-reviews` reviews. Hotels with the fewest reviews come first. If none match, it exits without starting Claude.
2. **Lead Agent** sends the hotels to **hotel-checker** one at a time, and waits for each to finish.
3. **hotel-checker** judges reviews in batches of up to 50:
   - Round 0: negative reviews that match the initial keywords `nois|wall|hear|siren`.
   - Rounds 1-7: LLM must add one new keyword per round, to find noise complaints the earlier words missed.
   - For each review, the LLM decides whether it is really about noise (`is_noise`) and whether switching rooms would avoid it (`category`), copies exact quotes, and gives a reason. The tool rejects the whole batch if a quote is not in the review or a field is invalid.
4. **Python computes the result**, not the AI:
   - `occurrence_rate` = noise reviews / all reviews of the hotel
   - `unavoidable_rate` = `unavoidable` reviews / noise reviews
   - **OK to book** only if `occurrence_rate` < 20% **and** `unavoidable_rate` < 30%. Otherwise: **Not suitable for noise-sensitive guests**.

Categories (can a guest avoid the noise by changing rooms?):

| Category | Meaning |
|----------|---------|
| `unavoidable` | Thin or not soundproof walls; still noisy after changing rooms; ordinary sounds from next door |
| `avoidable` | Only some rooms: near the lift, facing the street, ground floor, near ventilation units, a broken window |
| `unclear` | Source not stated, or not enough detail to tell |

## Agents

| Agent | Tools | Purpose |
|-------|-------|---------|
| **Lead Agent**  | `Agent` | Sends one hotel at a time to hotel-checker, then reports all results. A hook blocks every other tool |
| **hotel-checker** | `next_batch`, `add_judgments`, `add_keyword`, `build_report` | Checks one hotel. The 4 tools run in-process (`hotel_checker_agent/utils/hotel_tools.py`); it has no Bash, Read or Write |

## Command-Line Options

| Option | Description |
|--------|-------------|
| `--csv` | Path to `Hotel_Reviews.csv` (required) |
| `--city` | City name, e.g. `Milan`, not case sensitive (required) |
| `--score` | `Average_Score` must equal this value exactly, e.g. `8.0` (required) |
| `--min-reviews` | Minimum number of reviews a hotel has in the CSV (required) |
| `--max-hotels` | Maximum number of hotels to check (default `1`) |

## Example

```bash
.venv/bin/python -m hotel_checker_agent.agent \
    --csv ../hotel-check-10/data/Hotel_Reviews.csv \
    --city Milan --score 8.0 --min-reviews 100
```

hotel-checker replies with 6 lines per hotel:

A sample output
```
hotel: Atahotel Linea Uno
verdict: OK to book
occurrence_rate: 9.2%
unavoidable_rate: 9.1%
rounds: 8
report: .../runs/Milan/8.0/Atahotel_Linea_Uno/hotel_noise_analysis_log.xlsx
```

`rounds: 8` = round 0 plus the 7 keyword rounds.

## Output Structure

```
runs/
└── Milan/
    ├── summary.csv                        # One row per hotel checked in this city
    └── 8.0/
        └── Atahotel_Linea_Uno/
            └── hotel_noise_analysis_log.xlsx

logs/
└── session_YYYYMMDD_HHMMSS/
    ├── transcript.txt      # Human-readable conversation
    └── tool_calls.jsonl    # Structured tool usage log
```

The Excel report has 4 sheets:

| Sheet | Content |
|-------|---------|
| `summary` | Verdict, both rates, keywords used, the agent's inference |
| `log` | One row per round: keyword, why it was chosen, new hits, rates so far |
| `judgments` | Every review the agent read, with its judgment, quotes and reason |
| `all negative reviews` | Every negative review of the hotel, including ones no keyword matched |

`summary.csv` columns: `city, score, hotel, verdict, occurrence_rate, unavoidable_rate, rounds, report`. Checking the same hotel again replaces its row.

## Subagent Tracking with Hooks

The system tracks all tool calls using SDK hooks.

### What Gets Tracked

- **Who**: Which agent (`MAIN_AGENT`, `HOTEL-CHECKER-1`, etc.)
- **What**: Tool name (`mcp__hotel__next_batch`, `mcp__hotel__add_judgments`, etc.)
- **When**: Timestamp
- **Input/Output**: Parameters and output size
- **Denied / failed calls**: Tools the lead agent was not allowed to use, and batches a hotel tool rejected

### How It Works

Hooks run before and after every tool call:

```python
hooks = {
    "PreToolUse": [HookMatcher(hooks=[make_pre_tool_use(tracker)])],
    "PostToolUse": [HookMatcher(hooks=[tracker.post_tool_use_hook])],
    "PostToolUseFailure": [HookMatcher(
        hooks=[tracker.post_tool_use_failure_hook])],
}
```

- `PreToolUse` does two things: it denies any tool the lead agent tries to use except `Agent` / `Task`, then logs the call.
- The hook input has an `agent_id` only when a subagent makes the call. Each new `agent_id` gets the next label: `HOTEL-CHECKER-1`, `HOTEL-CHECKER-2`, ...
- When a hotel tool rejects a batch (`is_error`), only `PostToolUseFailure` fires, so the error is logged there.
- Anything else that needs permission (network, files outside the project) is denied by `can_use_tool` without asking.

### Log Output

**transcript.txt** - Human-readable:
```
[Spawning HOTEL-CHECKER-1: Check Atahotel Linea Uno]

[HOTEL-CHECKER-1] → mcp__hotel__next_batch    Input: {'hotel': 'Atahotel Linea Uno'}

[HOTEL-CHECKER-1] → mcp__hotel__add_keyword    Input: {'hotel': 'Atahotel Linea Uno', 'word': 'traffic', ...
```

**tool_calls.jsonl** - Structured JSON:
```json
{"event":"tool_call_start","agent_id":"HOTEL-CHECKER-1","agent_type":"hotel-checker","tool_name":"mcp__hotel__next_batch",...}
{"event":"tool_call_complete","agent_id":"HOTEL-CHECKER-1","tool_name":"mcp__hotel__next_batch","success":true,"output_size":1470,...}
```
