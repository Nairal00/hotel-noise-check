"""第 4 步：加一个新词，找出含新词、还没读过的差评，覆盖 new_hits.csv。

用法: python scripts/add_keyword.py --word "elevator"
"""
import argparse
import csv
import os
import re
import sys


def read(path):
    """把一个 CSV 读成一行行的字典。"""
    with open(path, encoding='utf-8') as f:
        return list(csv.DictReader(f))


def main():
    """按新词搜 todo.csv，跳过已读过的行。"""
    parser = argparse.ArgumentParser()
    parser.add_argument('--word', required=True, help='new keyword')
    args = parser.parse_args()
    # 去掉首尾空格；空词会命中所有评论，直接拒绝
    word = args.word.strip()
    if not word:
        sys.exit('--word is empty')
    # 第 1 步生成的文件，缺了就提示先跑 prepare.py
    for path in ('todo.csv', 'judgments.csv'):
        if not os.path.exists(path):
            sys.exit(f'{path} not found: run scripts/prepare.py first')

    # 全部写了差评的评论
    todo = read('todo.csv')
    # 已经读过的行号
    done = {r['row'] for r in read('judgments.csv')}
    # re.escape：词里的特殊符号按普通文字处理；不分大小写
    pat = re.compile(re.escape(word), re.I)
    # 含新词、而且还没读过
    new = [r for r in todo if pat.search(r['text']) and r['row'] not in done]
    # 覆盖成本轮的待读清单，列和 todo.csv 一样
    with open('new_hits.csv', 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=['row', 'query_hit', 'text'])
        w.writeheader()
        w.writerows(new)
    # 报告本轮新增多少条
    print('keyword', word, 'new hits', len(new))


if __name__ == '__main__':
    main()
