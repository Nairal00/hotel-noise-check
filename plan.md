# 改造计划：把 research-agent 改成酒店噪音检查 agent (Sprint 1 / MVP)

## 0. 目标

输入：城市 + 评分 + 最低评论数，全部是命令行参数，不写死在代码里
- 评分：酒店的 `Average_Score` **正好等于** `--score`
- 评论数：这家酒店在 CSV 里的行数 **≥** `--min-reviews`(不用 `Total_Number_of_Reviews` 这一列)

输出：每家酒店一份 Excel 报告 + 一张城市汇总表 `summary.csv`(不在终端打印汇总)

这次的例子：Milan、8.0、评论数 ≥ 100，符合的有 4 家(已用数据核对过)：

| 酒店 | 评论数 |
|---|---|
| Atahotel Linea Uno | 119 |
| Hotel Carrobbio | 131 |
| Novotel Milano Linate Aeroporto | 189 |
| Hotel Mozart | 512 |

Sprint 1 默认只跑 1 家(`--max-hotels` 默认 1)，按评论数从少到多排，所以先跑的是 Atahotel Linea Uno。

---

## 1. 先看懂原项目：research-agent 是怎么搭起来的

```
research-agent/
├── research_agent/
│   ├── agent.py                  <- 入口程序：定义主 agent、subagent、hooks，然后开始对话
│   ├── prompts/
│   │   ├── lead_agent.txt        <- 主 agent 的"岗位说明书"
│   │   ├── researcher.txt        <- subagent 1：上网搜资料
│   │   ├── data_analyst.txt      <- subagent 2：画图
│   │   └── report_writer.txt     <- subagent 3：写 PDF
│   └── utils/
│       ├── subagent_tracker.py   <- 记录"哪个 agent 调用了哪个工具"，写 tool_calls.jsonl
│       ├── transcript.py         <- 把屏幕输出同时存进 logs/ 文件夹
│       └── message_handler.py    <- 把 Claude 的回复打印到屏幕
├── .claude/
│   ├── skills/pdf/               <- 给 report-writer 用的 PDF skill
│   ├── skills/executive-briefing/
│   └── commands/*.md             <- /research 之类的斜杠命令
├── pyproject.toml                <- 依赖：claude-agent-sdk、python-dotenv
└── .env.example                  <- 放 ANTHROPIC_API_KEY 的模板
```

**核心概念(在 `agent.py` 里)：**

| 概念 | 原项目里的样子 | 一句话解释 |
|---|---|---|
| `AgentDefinition` | `agent.py:53-91` 定义了 3 个 | 一种 subagent 的"工种"：干什么、能用哪些工具、用哪个模型 |
| `tools=[...]` | researcher 只能用 `WebSearch`、`Write` | 工具白名单，没列出来的工具它就不能用 |
| `model="haiku"` | 全部用 haiku | 每个 agent 可以单独选模型，越便宜的模型越省钱 |
| `allowed_tools=["Task"]` | `agent.py:113` | 列出的工具**不用问就放行**，但**不限制**其他工具(官方文档原话 "does not restrict Claude to only these tools"，已实测：主 agent 照样能用 Bash)。原项目以为这样能让主 agent 只派活，其实不能，新做法见第 2 节 agent.py 第 6 点。**新版 SDK 这个工具已改名叫 `Agent`** |
| `setting_sources=["project"]` | `agent.py:111` | 只读项目里的 `.claude/` 设置和 skill，**不读**你的全局 `~/.claude/settings.json` |
| `hooks` | `agent.py:94-107` | 每次调用工具"之前/之后"自动执行一段代码，这里用来记日志 |
| `ClaudeSDKClient` | `agent.py:127` | 真正启动 Claude、开始对话的地方 |

**utils 和 skill 的记录不重复：** skill 记的是分析结果(`judgments.csv`、`log.csv`、xlsx)；utils 记的是程序运行过程(调用了什么工具、哪条命令报错)，出问题时用来查原因。每次运行新建一个 `logs/session_时间/`，不会自动删除。

---

## 2. 保留 / 修改 / 删除 / 新增

### 保留(不改)

| 文件 | 原因 |
|---|---|
| `utils/transcript.py` | 照样把输出存到 `logs/session_时间/` |

### 修改

| 文件 | 改什么 |
|---|---|
| `agent.py` | 见下面"agent.py 的改动" |
| `.env.example` | 原来只有 `ANTHROPIC_API_KEY`，改成 DeepSeek 的 7 个变量(`ANTHROPIC_BASE_URL`、`ANTHROPIC_AUTH_TOKEN`、`ANTHROPIC_MODEL`、`ANTHROPIC_DEFAULT_OPUS_MODEL`、`ANTHROPIC_DEFAULT_SONNET_MODEL`、`ANTHROPIC_DEFAULT_HAIKU_MODEL`、`CLAUDE_CODE_SUBAGENT_MODEL`)，key 用占位符 `your_deepseek_api_key_here`，不放真 key |
| `utils/message_handler.py:37` | `block.name == 'Task'` 改成同时认 `Task` 和 `Agent`(官方建议，新旧版本 SDK 都能用) |
| `utils/subagent_tracker.py:219` | `tool_name != 'Task'` 同上，同时认两个名字 |
| `prompts/lead_agent.txt` | 整个重写，很短：**一家一家**派 `hotel-checker`，上一家跑完再派下一家；每次把 Python 给的信息原样转交；subagent 回复 `error:` 时记下来，**不重试**，接着派下一家；全部跑完后回复一句完成 + `summary.csv` 路径 + 失败的酒店和原因 |
| `pyproject.toml` | 改项目名；依赖加 `openpyxl`、`pandas`；开发依赖加 `pytest`、`pytest-cov`、`pylint` |
| `.gitignore` | 加上 `runs/`(生成的报告不提交，也避免把电脑路径传到 GitHub) |
| `README.md` | 改成酒店项目的使用说明，写明环境搭建步骤(Python 3.12、建 venv、装库、按 `.env.example` 填 `.env`)、"先 `cd research-agent` 再运行"，以及**git 备份**：第一次 `git init`，之后每次试跑前提交一次。sandbox 允许 agent 写 `research-agent/`，代码可能被改坏或删掉，有提交就能一条命令恢复 |

**agent.py 的改动：**

1. **命令行参数**：`--csv`、`--city`、`--score`、`--min-reviews`、`--max-hotels`(默认 1)。
2. **开头先做 3 件事，都在启动 Claude 之前(不花钱)：**
   - 把 `--csv` 转成完整路径，并检查文件存在；不存在就报错退出
   - 切换到项目根目录(由 `agent.py` 自己的位置算出来)，让 `logs/`、`runs/` 一定建在 `research-agent/` 下面
   - 调 `select_hotels.py` 筛酒店；一家都没有就打印"0 家"并退出
3. **跑一次就结束**：去掉原来"一直对话"的循环，只发一次指令。
4. **交给主 agent 的信息**(全部由 Python 算好，主 agent 原样转交)：每家酒店的原名、工作目录完整路径、CSV 完整路径、skill 目录完整路径、Python 完整路径(`sys.executable`，即 venv 里的 Python)、城市、评分。
5. **subagent 定义**：只有 1 种 `hotel-checker`
   - `tools=["Skill", "Bash", "Read"]`，不给 `Write`(判断用 Bash 里的 Python 追加，漏读由 `log_round.py` 的核对兜底)
   - `skills=["hotel-check-10"]`：启动时直接加载 skill
   - `model="sonnet"`
6. **主 agent**：`model="haiku"`，`allowed_tools=["Agent"]`。
   - 注：用 DeepSeek 时，代码里照写 `sonnet`/`haiku`，实际都由 `.env` 映射成 `deepseek-flash`，两者没有区别。以后换回 Claude 只改 `.env`，不改代码。
   - **只靠 `allowed_tools` 拦不住主 agent**(见第 1 节)。另加一个 `PreToolUse` hook：调用来自 subagent(hook 输入里有 `agent_id`)就放行；来自主 agent 时只放行 `Agent`/`Task`，其他一律 `deny`。hook 在所有权限检查之前运行，deny 一定生效。已实测有效，且不会误拦 subagent。
   - 不用 `disallowed_tools=["Bash"]`：它对整个会话生效，会把 subagent 要用的 Bash 一起禁掉。
   - 这个 hook 和原来记日志的 hook 是两个，都要挂上。
7. **权限**。去掉 `bypassPermissions`，**写明 `permission_mode="default"`**(不写的话默认可能是 auto 模式，由 AI 自动批准 Bash，已实测出现过)。
   - **Bash 不会走到 `can_use_tool`**(已实测)：sandbox 默认开着 `autoAllowBashIfSandboxed`，在 sandbox 里跑的 Bash 命令(不管只读还是写文件)一律自动放行，不会来问你。所以"每条 Bash 按 y/n"**不能**用 `can_use_tool` 做，要放在 `PreToolUse` hook 里做：hook 排在所有检查最前面，每条 Bash 一定经过它。
   - **第一次试跑：hook 里人工确认**。subagent 每次用 Bash，hook 在终端打印命令，等你输入 `y`/`n`。目的是看清 subagent 实际会跑哪些命令。
   - **之后：hook 白名单**。白名单里的命令(用 venv 的 Python 跑 skill 的 4 个脚本、`cat > inference.txt`)自动放行，其他的拒绝。这样平时不用守在终端前。sandbox 已经限死了最坏情况，所以白名单够用。白名单的具体规则等第一次试跑后再定。
   - **`can_use_tool` 只剩一个用处：自动拒绝网络请求**。已实测：sandbox 里的命令要上网时，会以 `SandboxNetworkAccess` 的名字来问 `can_use_tool`(不是问 Bash)。`can_use_tool` 遇到它直接返回拒绝，不问你，免得手快按了 `y`。其他意外走到这里的请求也一律拒绝。
   - 用 `can_use_tool` 时 Python 有两个要求(官方文档)：问题要用 async generator 传给 `query()`，且至少挂一个 `PreToolUse` hook。第 6 点的 hook 正好满足。
   - `Read` 的规则见第 13 点。
8. **`env` 里放两个变量**：
   - `CLAUDE_CODE_DISABLE_BACKGROUND_TASKS=1`：强制前台运行。SDK 默认可能把 subagent 放在后台跑，主 agent 不等结果就往下走；设了这个就一定一家跑完再下一家。
   - `CLAUDE_AGENT_SDK_DISABLE_BUILTIN_AGENTS=1`：去掉 SDK 自带的 5 个 subagent(`claude`、`Explore`、`general-purpose`、`Plan`、`statusline-setup`)，主 agent 只能派 `hotel-checker`。已实测有效。
10. **`cwd=项目根目录`，必须写**。已实测：不写时，即使在 `research-agent/` 里运行，SDK 也把工作目录定成了外层 `hotel-check-10-skill/`，结果找不到 `.claude/skills/`，skill 加载失败。原因不确定(可能因为外层也有 `.claude/`)。
11. **sandbox 不写在代码里**，统一放在 `.claude/settings.json`(见"新增")。
12. **API key 检查改名**：原代码 `agent.py:32` 检查 `ANTHROPIC_API_KEY`，没有就退出。改用 DeepSeek 后这个变量不存在，要改成检查 `ANTHROPIC_AUTH_TOKEN`，提示文字里的 console.anthropic.com 也改成 platform.deepseek.com。
13. **`Read` 只能读项目文件夹和 CSV 文件夹**。`Read` 是 Claude Code 自带的工具，**不受 sandbox 管**(官方文档原话：`denyRead` doesn't stop the Read tool)。
    - 现状(已实测)：读项目外的文件会来问你 y/n，答 `y` 就能读到。如果把 `Read` 写进 `allowed_tools`，连问都不问就能读(最早的 smoke test 里 subagent 读过 `~/.claude/skills/...`)。
    - 做法：`Read` **不写进** `allowed_tools`；在第 6 点的 hook 里加规则：subagent 用 `Read` 时，路径不在 `research-agent/` 或 `--csv` 所在文件夹里，就直接 `deny`，不问你。
    - 已实测：`Read` 读项目外文件时会经过 hook(输出里有 `[hook] sub Read ...`)，所以这条规则可行。只有碰到 `settings.json` 的 deny 规则(如 `.env`)时，`Read` 会在 hook 之前就被拒绝，不影响。

### 删除

| 文件 | 原因 |
|---|---|
| `prompts/researcher.txt`、`data_analyst.txt`、`report_writer.txt` | 这 3 种 subagent 用不上 |
| `.claude/skills/pdf/`、`.claude/skills/executive-briefing/` | 输出 Excel，不需要 PDF |
| `.claude/commands/*.md` | 都是调研用的斜杠命令，用不上 |
| `smoke_test.py`、`smoke_test_bash.py` | 试验 DeepSeek、权限和 sandbox 用的临时脚本(见第 5 节)，正式代码写完后删 |

### 新增

| 文件 | 内容 |
|---|---|
| `.claude/settings.json` | **已建好，已实测。** 见下面"settings.json 的内容" |
| `.claude/skills/hotel-check-10/` | 从 `hotel-check-10/` **复制** `SKILL.md` + 4 个脚本(`prepare`、`add_keyword`、`log_round`、`build_report`)。改动见下面"skill 副本的改动" |
| `prompts/hotel_checker.txt` | subagent 的说明书，很短：按 skill 做，一次只查一家，用给它的完整路径和 Python 路径，最后只回 6 行结果(出错回 2 行)。怎么查都写在 skill 里，这里不重复 |
| `research_agent/select_hotels.py` | 筛酒店，**不交给 Claude**。从 donor code `list_hotels.py` 改过来，见下面"select_hotels.py 的规则" |
| `tests/` | 所有代码的测试，见第 3 节 |
| `tests/data/` | 测试用的小 CSV，由你提供 |

**settings.json 的内容：**

| 设置 | 作用 |
|---|---|
| `sandbox.enabled`、`allowUnsandboxedCommands: false`、`failIfUnavailable: true` | 开 sandbox；不许跳出 sandbox；sandbox 启动不了就停，不裸跑 |
| 写 | 默认只能写 `research-agent/` 和临时目录，也改不了 `.claude/skills/` 等设置文件。已实测：写桌面被挡(`Operation not permitted`) |
| `filesystem.denyRead: ["~/", "~/.ssh", "~/.aws", "./.env"]` | 整个用户主目录都不能读 |
| `filesystem.allowRead: [".", "~/Downloads/hotel-check-10-skill/hotel-check-10/data"]` | 但项目文件夹和 CSV 所在文件夹可以读。规则冲突时范围小的说了算，所以 `./.env` 在项目里也仍然读不到。已实测：读 `~/Documents`、`~/.zshrc` 被挡；读项目文件、跑 venv 的 Python + pandas、读 CSV 都正常。**CSV 换位置要同步改这一行**，`--csv` 给的文件必须在这个文件夹里 |
| `permissions.deny: ["Read(./.env)"]` | **`.env` 防护 ①(读文件)**：禁止 `Read` 工具读 `.env`。这种规则同时并入 sandbox，Bash 也读不到。已实测：`wc -c .env` 和 `Read .env` 都被挡 |
| `credentials.envVars: ANTHROPIC_AUTH_TOKEN deny` | **`.env` 防护 ②(环境变量)**：`load_dotenv()` 把 key 放进了程序的环境变量，Bash 命令默认会继承一份。这条让 Claude Code 在启动每条 Bash 命令前把这个变量删掉。Claude Code 自己仍有 key，能正常连 DeepSeek。已实测：Bash 里 `${#ANTHROPIC_AUTH_TOKEN}` 为 0 |
| 网络 | sandbox 默认不能上网，有请求时会问 `can_use_tool`，由它自动拒绝(第 2 节 agent.py 第 7 点)。已实测：`curl` 被挡 |

**select_hotels.py 的规则：**

| 项目 | 规则 |
|---|---|
| 读数据 | 用 pandas，只读需要的列；CSV 路径用 `--csv` 参数，不写死 |
| 城市 | 地址倒数第二个词(如 `... 20123 Milan Italy` 取 `Milan`)，不分大小写。已核对：Milan 用这个方法和"地址包含 Milan"结果一样，都是 162 家 |
| 评分 | 转成数字后比较(CSV 里存的是 `8`，不是 `8.0`)，正好等于 `--score` |
| 评论数 | 这家酒店的行数 ≥ `--min-reviews` |
| 排序 | 按评论数从少到多，一样多时按酒店名 |
| 截取 | 取前 `--max-hotels` 家 |
| 酒店名 | 去掉首尾空格(有些酒店名末尾带空格，`prepare.py` 比较前也会去掉) |
| 工作目录 | `runs/<城市>/<评分>/<酒店文件夹名>/` 的完整路径 |
| 城市文件夹名 | 用地址里的写法(`Milan`)，你输入 `milan` 也进同一个文件夹 |
| 评分文件夹名 | 保留一位小数：`8.0`(不用区间) |
| 酒店文件夹名 | 空格和特殊字符换成 `_`，连续的只留一个，如 `Hotel_Mozart` |

**skill 副本的改动(只改 research-agent 里那份)：**

1. 文件夹结构：`<评分区间>`(例 `8.0-8.5`)改成 `<评分>`(例 `8.0`)；`summary.csv` 的 `score_band` 列改成 `score`。
2. `summary.csv` 的 `report` 列改成相对 `runs/<城市>/` 的路径，如 `8.0/Hotel_Mozart/hotel_noise_analysis_log.xlsx`，不带电脑用户名。
3. 命令里的 `python` 改成调用方给的 Python 完整路径。"输入"一节加上：调用方还会给 skill 目录和 Python 路径。
4. 第 5 步：先用 `cat > inference.txt <<'EOF' ... EOF` 把 [Inference] 写进工作目录的 `inference.txt`，再运行 `build_report.py`。中间文件表加一行 `inference.txt`。(用文件不用命令参数，是因为文字里的引号会把命令弄乱。)
5. `build_report.py`：读 `inference.txt`，写进 Excel 的 `summary` 表；文件不存在就报错停下。

**有意分叉：** 原来的 `hotel-check-10/` 和你 Claude 账号里装的 `hotel-check-10` skill 都不动，sprint 1 不同步。程序只会加载 research-agent 里那份。

**行号**：仍按 SKILL.md 的定义，`row` = `Hotel_Reviews.csv` 里的真实行号(表头是第 1 行)，和原数据集一一对应(已核对：文件 515,739 行 = 1 行表头 + 515,738 条评论，没有跨行的评论)。donor code `search_reviews.py` 的行号算法(不算表头)不沿用。

**donor code**：`list_hotels.py`、`search_reviews.py` 只作参考，不复制进项目。

---

## 3. 测试

- 用 `unittest` 写(PyUnit 语法)，用 pytest 跑，统计覆盖率。
- **所有代码覆盖率 ≥ 95%**：`select_hotels.py`、`agent.py`、utils 3 个文件、skill 副本的 4 个脚本。
- `agent.py` 和 utils 用 `unittest.mock` 造假的 Claude，不调用真 API，不花钱。只能证明代码逻辑对，真实行为靠第 5 节的试跑。
- 测试 CSV 由你提供，放在 `tests/data/`。要求：列和原数据一样；几十到一两百行；至少两个城市；同城有评分等于和不等于的；有一家评论数正好等于门槛、一家少于门槛(测试里 `--min-reviews` 设小一点，如 3)；有酒店名末尾带空格的；差评里有空的、`No Negative`、命中噪音词的、没命中的。
- 所有代码跑 Pylint。

---

## 4. 改完之后怎么运行

```
cd research-agent
<venv 的 python> -m research_agent.agent --csv ../hotel-check-10/data/Hotel_Reviews.csv \
    --city Milan --score 8.0 --min-reviews 100
```

运行流程：

```
agent.py
  │ 1. 检查 CSV、切到项目根目录
  │ 2. select_hotels.py 筛出酒店，按评论数从少到多，取前 --max-hotels 家(默认 1)
  │    0 家就退出，不启动 Claude
  ▼
主 agent (haiku，工具：Agent)
  │ 3. 派 hotel-checker 查第 1 家 → 等它跑完(出错就记下，接着下一家)
  │ 4. ……一家一家查完，回复 summary.csv 路径 + 失败名单
  ▼
hotel-checker (sonnet，工具：Skill, Bash, Read)
  │ 按 skill 做，每条 Bash 命令都要你在终端按 y 确认
  ▼
输出文件：
  runs/Milan/summary.csv
  runs/Milan/8.0/Atahotel_Linea_Uno/hotel_noise_analysis_log.xlsx
  logs/session_xxx/transcript.txt、tool_calls.jsonl
```

---

## 5. 还没定 / 要实测的

**你来搭(环境)：**
- [x] Python 3.12(`brew install python@3.12`)，在 `research-agent/` 里建 venv，装依赖
- [x] 模型改用 DeepSeek(不用 Anthropic API，Claude Pro 订阅额度不能给 SDK 程序用)：在 platform.deepseek.com 申请 key，按 DeepSeek 官方的 Claude Code 接入说明把 7 个变量放进 `.env`

**待定：**
- [ ] `max_budget_usd` 设多少(不可靠，主要靠 DeepSeek 余额控制，见第 2 节 agent.py 第 9 点)
- [ ] Bash 白名单的具体规则(第一次试跑看完实际命令后定，见第 2 节 agent.py 第 7 点)

**已用 `smoke_test.py` 实测(2026-10-09)：** 主 agent 派 1 个 subagent，subagent 预加载 `executive-briefing` skill 回答问题，并用 Read 读 `pyproject.toml`。
- [x] DeepSeek 能跑 `Agent` 工具派 subagent、subagent 能用 Read
- [x] `skills=[...]` 预加载生效(前提是 `cwd` 写对)：subagent 没调 `Skill`、没读 SKILL.md 就答对了
- [x] `cwd` 不写会定错目录(见第 2 节 agent.py 第 10 点)
- [x] `allowed_tools` 不限制工具，改用 hook 拦主 agent，有效(第 6 点)
- [x] 去掉自带 subagent 的环境变量有效(第 8 点)
- [x] `permission_mode="default"` 生效，init 消息里显示 `default`
- [x] 花费估算不准：启动时出现 `unrecognized_model deepseek-flash`，SDK 不认识这个模型，`total_cost_usd` 不可信。真实花费看 DeepSeek 后台；`max_budget_usd` 也因此不可靠

**已用 `smoke_test_bash.py` 实测(2026-10-09 ~ 10-10)：** subagent 有 Bash 和 Read，挂了 `can_use_tool`。
- [x] Bash 不走 `can_use_tool`：`ls`、`touch`(项目内)都没问就跑了(第 2 节 agent.py 第 7 点)
- [x] sandbox 挡住写项目外(`touch ~/Desktop/...`)
- [x] sandbox 挡住上网：`curl` 以 `SandboxNetworkAccess` 来问，答 n 后被挡
- [x] `.env` 两道防护都有效：`wc -c .env`、`Read .env` 被挡；Bash 里 key 的环境变量为空
- [x] 主目录禁读有效：`~/Documents`、`~/.zshrc` 被挡；项目文件、venv 的 Python + pandas、CSV 都能用
- [x] `Read` 读项目外文件会问 y/n，不受 sandbox 管，要用 hook 管(第 13 点)
- 测试时发现：主 agent 看到 sandbox 禁读 `.env`，会把"读 `.env`"当成偷 key 而**拒绝派活**；说明清楚是主人在测自己的配置后才执行。模型自己的安全意识不可靠，不能代替写死的规则

**第一次试跑时还要确认的：**
1. hook 里的 `Read` 路径规则、Bash 人工确认、`can_use_tool` 自动拒绝网络，写进 `agent.py` 后是否都生效
2. 前台运行的设置是否真的让主 agent 等每一家跑完(smoke test 只派了 1 次，没测出区别)
3. DeepSeek 跑真正的 hotel-check-10 skill 时，判断质量是否可用

**已知但 sprint 1 不处理：**
- `prepare.py` 每查一家都把 238 MB 的 CSV 整个读一遍，会慢、占内存。跑一次看看多慢再说
- subagent 回复"成功"但判断本身错了，程序查不出来，要你打开 Excel 的 `judgments` 表抽查

---

## 6. 费用

不确定，要先跑一家才能估出来：
1. 默认 `--max-hotels 1`，先跑 Atahotel Linea Uno(119 条)，看 DeepSeek 后台(platform.deepseek.com)花了多少钱
2. 没问题再跑全部 4 家。Hotel Mozart(512 条)大约是第一家的 4 倍

已查到的 SDK 文档：
- [Subagents in the SDK](https://code.claude.com/docs/en/agent-sdk/subagents)
- [Claude Code subagents](https://code.claude.com/docs/en/sub-agents)
- [Sandboxing](https://code.claude.com/docs/en/sandboxing)
- [Python SDK reference](https://code.claude.com/docs/en/agent-sdk/python)
- [Configure permissions](https://code.claude.com/docs/en/agent-sdk/permissions)：`allowed_tools` 不限制工具、权限检查顺序、只读 Bash 自动批准
- [Handle approvals and user input](https://code.claude.com/docs/en/agent-sdk/user-input)：`can_use_tool` 的写法和 Python 的两个要求
- [Hooks](https://code.claude.com/docs/en/agent-sdk/hooks)：`PreToolUse` hook 的写法、`agent_id` 区分主 agent 和 subagent
- [DeepSeek: Integrate with Claude Code](https://api-docs.deepseek.com/quick_start/agent_integrations/claude_code)：`.env` 的 7 个变量


Future Sprints ideas：
lead agent比较几家酒店，写一段总结：最值得加，也最容易
怎么做：每家酒店查完后，hotel-checker 本来就会回复 6 行（结论、两个指标、轮数、报告路径）。lead agent 已经拿到了这些内容，不需要任何新工具，只要在 lead_agent.txt 末尾加一条规则就行。例如："全部完成后，按 occurrence_rate 从低到高排列，用一两句话说明哪家最适合怕吵的人"。
要注意：
--max-hotels 默认是 1，只查一家的话没东西可比，这一项要等你一次查几家时才有用。
它只能根据那两个指标来比。这是 AI 的判断（[Inference]），不能当成事实。
总结只会打印在终端和 transcript 里。如果想存成文件，lead agent 需要写文件的工具，那样又得放开权限，事情会复杂很多。

## 7. Sprint 2：第一次试跑后的改动（2026-10-11）

### 7.1 试跑结果
Atahotel Linea Uno 跑通：Not suitable for noise-sensitive guests，occurrence_rate 10.9%，unavoidable_rate 38.5%（5/13），8 轮（含第 0 轮），27 次 Bash，约 5 分钟。
没被关键词命中的差评已抽查，没发现漏掉的噪音抱怨。prepare.py 读 238MB 实测 2.8 秒，不慢（第 5 节"已知但不处理"那条可以划掉）。

### 7.2 发现的问题
| # | 问题 | 后果 |
|---|---|---|
| 1 | SKILL.md 让 subagent 自己写 Python（追加 judgments、写 summary.csv）；它还自己写 python -c 打印 new_hits | Bash 白名单没法放行"任意代码" |
| 2 | summary.csv 的结论、指标、轮数由 AI 手抄 | 可能抄错 |
| 3 | judgments 的内容没人检查 | 写成 Unavoidable（大写）会被悄悄算错，不报错 |
| 4 | 多余调用：开头 2 次 ls、1 次 cat prepare.py，结尾 2～3 次检查 xlsx | 浪费时间和钱 |
| 5 | 6 个中间文件；"第几轮读了哪些行"存了 4 遍（todo 的 query_hit、new_hits.csv、judgments 的 round、log 的 hit_rows 等） | 几份记录可能对不上 |
| 6 | log.csv 存的是指标快照，build_report 用快照下结论 | 最后一轮后又改了判断，结论还是旧的 |
| 7 | tool_calls.jsonl 不记被 hook 拒绝的命令 | 这次 2 条命令只有开始没有结束，查不出原因 |
| 8 | 结论对个别判断敏感：改判 2 条（如 495853、495928）就翻成 OK to book。关键词也影响结论：hear、wall 两轮把 unavoidable_rate 从 27% 推到 38%，所以**不要加"提前停止"的规则**，提前停这家就会判成 OK to book | 结论不稳 |
| 9 | 每个脚本是独立程序，数据只能靠文件传；路径、数字靠 AI 在命令里转抄 | 文件多、容易抄错 |

### 7.3 改动方向：脚本改成 SDK 自定义工具，保留 lead agent
用 SDK 的 @tool + create_sdk_mcp_server，把脚本改成 Python 函数，注册成工具，**只给 hotel-checker 用**。
- 函数在 agent.py 这个程序里运行（不另起程序、不走网络），能直接用 agent.py 的变量
- MCP 只是 Claude Code 接收外来工具的格式；AI 看到的工具名是 mcp__hotel__<工具名>
- 工具函数放在新文件 research_agent/hotel_tools.py，由 agent.py import
- 保留 lead agent，为了之后让它比较几家酒店（见 Future Sprints）

**运行流程：**
1. agent.py：读一次 CSV，筛酒店（原 select_hotels），并把每家酒店的全部评论准备好（原 prepare）存进内存，按酒店名分开。全程不花钱
2. lead agent（haiku，只能用 Agent）：一家一家派 hotel-checker，**只转交酒店名**，路径都不用转了
3. hotel-checker（sonnet，只能用下面 4 个工具，没有 Bash、Read、Skill）：读差评、判断、加词，最后生成报告，回复 6 行
4. lead agent 收齐结果后回复：完成几家、失败几家及原因

**4 个工具（每个都带 hotel 参数）：**
hotel 必须和 agent.py 选中的酒店名**完全一致**，不一致就报错退回。这样酒店名虽然是 AI 转抄的，抄错了也会被当场发现。

| 工具 | 作用 |
|---|---|
| next_batch(hotel) | 返回本轮还没判断的下一批（最多 50 条，行号 + 原文）；本轮读完时返回"已读完" + 当前两个指标 |
| add_judgments(hotel, items) | 存一批判断。先检查：行号属于本轮、没有重复、is_noise 只能 yes/no、category 只能三种之一（no 时必须空），有一条不对整批退回。存完返回下一批 |
| add_keyword(hotel, word, reasoning) | 先检查上一轮已读完、没满 7 轮；记下本轮关键词和理由；把含新词、还没命中过的差评标为新一轮；返回新增条数和第一批 |
| build_report(hotel, inference) | 检查全部读完；现算每轮指标和结论；生成 xlsx；写 summary.csv；返回 6 行结果（hotel、verdict、两个指标、rounds、report 路径） |

原来的 4 个脚本对应关系：
- prepare → agent.py 启动前直接调用
- add_keyword → add_keyword 工具
- log_round → 拆掉：漏读检查放进 add_keyword 和 build_report，记录关键词放进 add_keyword，打印指标放进"本轮已读完"的返回值
- build_report → build_report 工具
- 新增 next_batch、add_judgments，代替 AI 自己写的 Python

**数据存在内存里（每家酒店一份），中间文件全部不要：**
- reviews：每条评论一行，含 row, round, text, is_noise, category, quote, reason；total = 条数
- rounds：每轮一行，含 round, keyword, reasoning
- 输出只剩 xlsx 和 summary.csv。代价：中途出错要重跑这家（logs/ 里仍有过程记录）
- 所有工具都在同一个程序里按顺序运行，写 summary.csv 不再需要文件锁。但同一城市、不同评分的酒店共用 runs/<城市>/summary.csv，不要同时开两个终端跑同一个城市，否则可能写冲突

**输出格式不变：**
- xlsx 仍是 4 个工作表，列和现在一样；log 表后 6 列在生成时现算；summary 表加一行 unavoidable_reviews
- summary.csv 列不变；city、score 由 agent.py 直接填；rounds = 轮数（含第 0 轮）

### 7.4 文件的变化
| 文件 | 改动 |
|---|---|
| .claude/skills/hotel-check-10/（SKILL.md + 4 个脚本） | 不再使用。判断规则（is_noise 定义、分类表、判定规则、inference 要求）搬进 prompts/hotel_checker.txt；脚本逻辑搬进 hotel_tools.py |
| 分类表 | 补两个例子：听到邻居/别的房间 → ?；交通噪音 + 隔音差 → ?【待你定】 |
| research_agent/hotel_tools.py | 新增：读 CSV + 准备数据、4 个工具、生成 xlsx 和 summary.csv |
| select_hotels.py | 合并进 hotel_tools.py，或者保留并由它顺便读出 Negative_Review，保证 CSV 只读一次 |
| prompts/hotel_checker.txt | 重写：判断规则 + 工具的使用顺序（next_batch → add_judgments，重复到本轮读完 → add_keyword 或 build_report）+ 回复格式 |
| prompts/lead_agent.txt | 只转交酒店名；收齐每家的 6 行结果 |
| agent.py 的 build_user_prompt | 只给城市、评分、酒店名，不再给各种路径 |
| agent.py 的 subagent 定义 | tools 只写 4 个工具的全名；去掉 skills |
| agent.py 的设置 | mcp_servers 挂上工具；tools=["Agent"]，关掉其他自带工具（Bash、Read 等）；allowed_tools 写 Agent + 4 个工具全名（不写的话会走到 can_use_tool 被拒）。注意 tools 只管自带工具，MCP 工具不受影响，lead 仍看得到 4 个工具，拦 lead 靠 hook |
| hooks | 保留 main_agent_only_delegates（防止 lead 自己调工具）；删掉 confirm_bash、limit_read；记日志的 hook 保留，并加上记录被拒绝的调用；加 PostToolUseFailure hook 记录执行失败的调用 |
| can_use_tool | 保留"一律拒绝"，作为保险 |
| env 两个变量 | 保留（前台运行；去掉自带 subagent） |
| settings.json sandbox | 没有 Bash 后基本用不上，保留不影响 |
| 第 5 节"Bash 白名单"待定项 | 不再需要 |
| tests | 重写，覆盖率 ≥ 95%，跑 Pylint。hotel_tools.py 分两层写：逻辑写成普通函数（返回 Python 数据，出错抛 ValueError），大部分测试测这一层；@tool 包装层只负责把结果转成文字、把 ValueError 转成 is_error，用 unittest.IsolatedAsyncioTestCase + await 工具.handler({...}) 测几条（原因见 7.5 查文档结果） |

### 7.5 先查文档，再做 smoke test
**查文档**（确定写法，避免 smoke test 写错）：
- [ ] Subagents 页：subagent 怎么使用自定义工具（tools 里写全名，还是要配合 AgentDefinition.mcpServers）
- [x] Custom Tools 页：@tool、create_sdk_mcp_server 的写法

**已查（2026-10-11）：** Custom Tools 页、Python SDK reference 页、.venv 里装的 SDK（0.2.165）源码
- @tool 返回一个 SdkMcpTool 对象（字段：name、description、input_schema、handler、annotations），不是原来的函数。要执行得写 await 工具.handler({...})。来源：文档原话 "returns an SdkMcpTool instance"；源码 claude_agent_sdk/__init__.py:324-333，装饰器只是把函数放进 handler 字段。"不能直接调用"是读源码得出的，没有实际运行验证
- handler 必须是 async。文档原话 "the async function that runs when Claude calls the tool"
- 返回格式 {"content": [{"type": "text", "text": ...}]}；出错时加 "is_error": True。handler 里没接住的异常也会变成错误结果交给 AI，程序不会停
- 参数格式由 SDK 的 MCP 服务器在调用 handler 之前检查；测试里直接调 .handler 时不会检查
- 文档没有讲怎么测试自定义工具 → 测试写法见 7.4 tests 一行
- AI 看到的工具名是 mcp__<mcp_servers 里的键名>__<工具名>；allowed_tools 写全名，也可以写 mcp__hotel__* 表示这个服务器的全部工具
- tools 选项只管自带工具，文档原话 "MCP tools are unaffected"
- AgentDefinition 有 mcpServers 字段（驼峰写法），tools 写允许的工具名。两者怎么配合文档没写清楚，靠 smoke test 确认
- tool search 默认开启，自定义工具默认延迟加载：AI 一开始只看到工具名，用到时再加载参数说明
- 有 PostToolUseFailure hook（工具执行失败时触发），可以补 7.2 第 7 条

**smoke test**（1 个简单工具、1 个 subagent，用 DeepSeek 跑一次），确认 6 件事：
1. subagent 能调用自定义工具
2. 两次调用之间，工具存在内存里的数据还在
3. tools=["Agent"] 后，lead 和 subagent 都没有 Bash、Read
4. lead 自己调用自定义工具时，被 hook 拒绝
5. allowed_tools 写了全名后，工具调用不会走到 can_use_tool 被拒
6. subagent 只有 4 个自定义工具时，能正常加载工具的参数说明（因为 tool search 延迟加载）；不行再查怎么关掉 tool search

### 7.6 步骤
1. 查文档 + smoke test（7.5）
2. 通过 → 按 7.3、7.4 改，补测试
3. 重跑 Atahotel Linea Uno，和这次的结果对比
4. 不通过 → 备选方案：保留 Bash + 脚本，但要
   - 新增 add_judgments.py（检查格式后写入）
   - build_report.py 自己写 summary.csv
   - prepare.py、add_keyword.py 直接打印差评原文
   - 中间文件合并成 todo.csv（全部评论 + 判断 4 列）和 log.csv（round, keyword, reasoning）
   - inference 用 heredoc 直接传给 build_report.py
   - 最后再定白名单