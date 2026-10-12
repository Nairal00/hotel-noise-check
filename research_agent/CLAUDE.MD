# hotel-noise-check

用 Claude Agent SDK 判断酒店是否适合怕吵的人。计划和进度见 docs/plan.md（当前：Sprint 2）。

## 运行环境
- 一律用 .venv/bin/python，系统 python 没装 pandas、openpyxl
- 测试用 tests/data/ 里的小 CSV

## 不要做
- 不要运行 research_agent/agent.py：它会调用 DeepSeek 花钱，要试跑先问我
- 不要整个读 Hotel_Reviews.csv（238MB），只读几行看格式
- 不要读 .env（里面是 API key）
- 不要改外层的 hotel-check-10/（原版 skill，有意不同步）

## 容易弄错的规则
- row = Hotel_Reviews.csv 里的真实行号，表头是第 1 行，第一条评论在第 2 行
- 代码里写的 sonnet / haiku，实际由 .env 映射成 DeepSeek 的模型
- runs/、logs/ 是输出，不进 git