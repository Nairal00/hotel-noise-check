---
name: "hotel-check-10"
description: "Judge whether a hotel suits noise-sensitive guests from a review CSV: keyword-search complaints, read every hit, add up to 7 keywords, apply the occurrence/unavoidable rule, write one Excel workbook. Runs as a subagent: one hotel per call, inside a per-hotel working directory given by the caller."
---

# 酒店噪音判断（怕吵的人能不能订）

- **所有文件内容和最终结论都用英文。**
- 全程区分 [Fact]（原文直接写的、程序算出的）和 [Inference]（agent 的判断）。
- 不看好评栏，好评不影响分类、指标和结论。
- 本 skill 由 subagent 使用：主 agent（调用方）每次只派一家酒店，并指定这家酒店的**专属工作目录**；所有文件只写在这个目录里，不同酒店互不覆盖。
- 下面的脚本都在本 skill 的 `scripts/` 目录里，只写"当前目录"。所以**每条命令都要先 `cd` 到工作目录，并用脚本的绝对路径和调用方给的 Python**，格式：`cd "工作目录" && "<Python 完整路径>" "<本 skill 目录>/scripts/xxx.py" ...`（下文简写为 `$PYTHON`、`$SKILL_DIR`）。不要用系统的 `python`，它没有装 pandas、openpyxl。

## 输入
调用方会给出五样：
- 原数据 CSV 的路径，必须包含这些列：`Hotel_Name`、`Negative_Review`（差评栏）
- 酒店名（和 `Hotel_Name` 完全一致）
- 这家酒店的工作目录（不存在就先 `mkdir -p` 建好），必须按下面的文件夹结构
- 本 skill 目录的完整路径（`$SKILL_DIR`）
- Python 的完整路径（`$PYTHON`）

开始前先检查：
- 缺少以上任何一样，或 CSV 缺少以上任何一列 → 停下来告诉调用方，不要猜。
- 原数据 CSV 是只读的，所有中间文件写到工作目录。

**文件夹结构**（`runs/` 在项目根目录下）：
```
runs/
  <城市>/                     例：Amsterdam
    summary.csv               这个城市的总表，每家酒店一行（见"输出"第 3 条）
    <评分>/                   例：8.0（保留一位小数）
      <酒店名>/               工作目录；空格和特殊字符换成 _，连续的只留一个，例：Hotel_Mozart
        todo.csv  total.txt  new_hits.csv  judgments.csv  log.csv  inference.txt
        hotel_noise_analysis_log.xlsx
```
调用方给的工作目录不符合这个结构 → 停下来告诉调用方。

**行号**：所有文件和工作表里的 `row` 都是原数据 CSV 的行号（第 1 行是表头，第一条评论在第 2 行）。只分析其中一家酒店时，也用原文件的行号。

## 中间文件（只在工作目录里，跑完保留，不用回传内容）
| 文件 | 内容 |
|---|---|
| `todo.csv` | 这家酒店所有写了差评内容的评论：row, query_hit, text |
| `total.txt` | 这家酒店的评论总数（含没写差评的） |
| `new_hits.csv` | 本轮要读的差评（每轮覆盖） |
| `judgments.csv` | agent 对每条已读差评的判断 |
| `log.csv` | 每轮一行的记录 |
| `inference.txt` | 第 5 步写的 [Inference]，`build_report.py` 读它写进 Excel |

## 第 1 步：准备待读清单（第 0 轮）
```bash
cd "工作目录" && "$PYTHON" "$SKILL_DIR/scripts/prepare.py" --csv 原数据CSV路径 --hotel "酒店名"
```
用三个初始核心词（`nois|thin wall|siren`）筛出第 0 轮要读的差评，写出 `todo.csv`、`new_hits.csv`、空的 `judgments.csv`、`total.txt`，并清掉上一次的 `log.csv`。会打印评论总数、写了差评的条数、命中核心词的条数。

## 第 2 步：精读本轮命中的差评
agent 逐条读 `new_hits.csv` 里的**每一条**（每批 50 条），读完一批就把判断追加到 `judgments.csv`，再读下一批。
- **每一条都要写一行**，不是噪音的也写，这样可以核对有没有漏读。
- 追加时用 `$PYTHON` 运行 Python 的 `csv.writer`，不要手写逗号（原文里的逗号和引号它会自动处理）。
- `judgments.csv` 的列（全部用英文填写）：
  - `row`：原数据行号。
  - `round`：第几轮读的（第 0 轮 = 初始核心词）。
  - `is_noise`：`yes` / `no`。这条差评是否在抱怨噪音或隔音差（包括没用 noise 这类词的说法，如"could hear the neighbours"）。
  - `category`：只有 is_noise = yes 时填，**只能填一个**，见第 3 步；is_noise = no 时留空。
  - `quote`：原文中和噪音相关的句子，原样摘录；涉及多种噪音时可以摘录多句。
  - `reason`：判断理由（属于 [Inference]），英文。

## 第 3 步：给噪音差评分类
| category | 含义 | 例子 |
|---|---|---|
| `unavoidable` | 换房避不开：问题出在整栋楼都有的情况 | 墙薄、隔音差、原文写了换房后仍然吵 |
| `avoidable` | 换房能避开：问题只出在某类房间 | 靠电梯、临街、朝广场、一楼、靠洗衣房或通风机、窗户坏了 |
| `unclear` | 无法判断：没写噪音来源 | "Noise" |

一条差评提到多种噪音时，只填一个，优先级：**unavoidable > avoidable > unclear**。

## 每轮读完后：记录本轮
```bash
cd "工作目录" && "$PYTHON" "$SKILL_DIR/scripts/log_round.py" --round 0 --keyword "nois|thin wall|siren" --reasoning "initial core keywords"
```
每轮换成本轮的轮次、关键词、英文加词理由。脚本会先核对本轮 `new_hits.csv` 的每一行在 `judgments.csv` 里都有判断；有漏读就报出行号并停下，不写记录，这时先补读再重新运行。

`log.csv` 各列定义：
| 列名 | 定义 |
|---|---|
| `round` | 第几轮。0 = 初始 3 个核心词；1～7 = 之后每加一个新词算一轮 |
| `keyword` | 本轮的关键词 |
| `reasoning` | 为什么加这个词 [Inference] |
| `new_hits_current_round` | 本轮新搜到、之前没读过的差评条数 |
| `new_positive_noise_reviews` | 本轮新命中的差评里，被判为真噪音抱怨的条数 |
| `occurrence_rate` | 到本轮为止，碰上噪音的概率 = 噪音差评条数 ÷ 评论总数 |
| `unavoidable_rate` | 到本轮为止，碰上了换房也避不开的比例 = unavoidable 条数 ÷ 噪音差评条数（三类都算） |
| `hit_rows` | 本轮读过的差评的原数据行号 |
| `noise_rows` | 本轮被判为真噪音抱怨的原数据行号 |

## 第 4 步：加新词，再搜再读
每轮记录完后，agent 根据读到的噪音差评，决定要不要加 1 个新词：
- 每轮只加 1 个，最多 7 轮（第 1～7 轮）；觉得没有新词值得加，就提前停。
- 每加一个词，运行下面的命令，然后回到第 2、3 步读 `new_hits.csv`，再运行记录脚本（换成本轮的 `--round`、`--keyword`、`--reasoning`）。

```bash
cd "工作目录" && "$PYTHON" "$SKILL_DIR/scripts/add_keyword.py" --word "new keyword"
```
新词按普通文字匹配（不分大小写），只挑出含新词、而且还没读过的差评，覆盖 `new_hits.csv`。

没被任何关键词命中的差评，agent 没读过，算指标时一律当作"不是噪音"。

## 第 5 步：下结论，生成 Excel
判定规则（用户定的）：
- `occurrence_rate` < 20%，**而且** `unavoidable_rate` < 30% → `OK to book`
- 其他所有情况 → `Not suitable for noise-sensitive guests`

先把 [Inference] 写进工作目录的 `inference.txt`（英文），例如噪音的主要来源、2～3 条代表性差评原文（附原数据行号）。用下面的写法，不要把文字放进命令参数（原文里的引号会把命令弄乱）：
```bash
cd "工作目录" && cat > inference.txt <<'EOF'
<你的 [Inference]，可以多行>
EOF
```

再用脚本生成 Excel，不要手算：
```bash
cd "工作目录" && "$PYTHON" "$SKILL_DIR/scripts/build_report.py" --hotel "酒店名"
```
用最后一轮的指标套判定规则，把 `inference.txt` 的内容一起写进 Excel，在工作目录生成 `hotel_noise_analysis_log.xlsx`，并打印结论和两个指标。没有 `inference.txt` 时脚本会报错停下，这时先写好它再重新运行。

## 输出
1. `hotel_noise_analysis_log.xlsx` 留在工作目录里。四个工作表：`summary`、`log`、`judgments`、`all negative reviews`。
2. `hotel_noise_analysis_log.xlsx` 的 `summary` 表用**英文**给出结论（由 `build_report.py` 写入）：
   - **Verdict**：OK to book / Not suitable for noise-sensitive guests
   - **[Fact]**：两个指标、用过的关键词
   - **[Inference]**：`inference.txt` 的内容（第 5 步写的）
3. 往城市总表 `runs/<城市>/summary.csv`（= 工作目录往上两层）追加这家酒店的一行；文件不存在就先写表头。同一家酒店已有一行时，删掉旧行再写新行。`report` 列是相对 `runs/<城市>/` 的路径（例：`8.0/Hotel_Mozart/hotel_noise_analysis_log.xlsx`），不带电脑用户名。几个 subagent 可能同时写这个文件，所以必须加锁，按下面的写法（把 `<...>` 换成实际值）：
   ```bash
   cd "工作目录" && "$PYTHON" - <<'PY'
   import csv, fcntl, os
   path = os.path.abspath('../../summary.csv')
   header = ['city', 'score', 'hotel', 'verdict', 'occurrence_rate',
             'unavoidable_rate', 'rounds', 'report']
   new = ['<城市>', '<评分>', '<酒店名>', '<verdict>', '<occurrence_rate>',
          '<unavoidable_rate>', '<rounds>',
          os.path.relpath('hotel_noise_analysis_log.xlsx', '../..')]
   with open(path, 'a+', newline='', encoding='utf-8') as f:
       fcntl.flock(f, fcntl.LOCK_EX)
       f.seek(0)
       rows = [r for r in csv.reader(f) if r and r != header and r[2] != new[2]]
       f.seek(0)
       f.truncate()
       w = csv.writer(f)
       w.writerow(header)
       w.writerows(rows + [new])
   PY
   ```
4. 最后回复调用方的内容**只有下面几行**（英文），不要附差评原文或中间过程，避免撑大调用方的上下文：
   ```
   hotel: <酒店名>
   verdict: OK to book / Not suitable for noise-sensitive guests
   occurrence_rate: <build_report.py 打印的值>
   unavoidable_rate: <build_report.py 打印的值>
   rounds: <用过的轮数>
   report: <xlsx 的绝对路径>
   ```
   中途停下（缺列、找不到酒店等）时，回复 `hotel`、`error: <原因>` 两行。
