"""第 1 步：准备待读清单（第 0 轮）。

用法: python scripts/prepare.py --csv 上传文件路径 --hotel "酒店名"
"""
import argparse
import csv
import os
import re
import sys

# 三个初始核心词；re.I = 不分大小写
CORE = re.compile(r'nois|thin wall|siren', re.I)
# 视为"没写差评"的内容（比较前已转小写）
EMPTY = {'', 'no negative', 'nothing', 'none', 'n a', 'no complaints'}
# todo.csv 和 new_hits.csv 共用的表头
HEADER = ['row', 'query_hit', 'text']


def main():
    """读原数据，写出 todo.csv、new_hits.csv、judgments.csv、total.txt。"""
    parser = argparse.ArgumentParser()
    parser.add_argument('--csv', required=True, help='uploaded review CSV')
    parser.add_argument('--hotel', required=True, help='exact Hotel_Name')
    args = parser.parse_args()
    # 输入的酒店名也去掉首尾空格，和下面数据里的比较方式一致
    hotel = args.hotel.strip()

    # 整张表读进来，每条评论是一行
    with open(args.csv, encoding='utf-8') as f:
        rows = list(csv.DictReader(f))
    # total = 评论总数；todo = 待读清单
    total, todo = 0, []
    for i, r in enumerate(rows):
        # 只留这家酒店
        if r['Hotel_Name'].strip() != hotel:
            continue
        # 每条评论都计入总数，包括没写差评的
        total += 1
        # 差评原文；换行和多余空格都变成单个空格
        text = ' '.join(r['Negative_Review'].split())
        # 没写差评的不用读
        if text.lower() in EMPTY:
            continue
        # 原数据行号（+2 因为表头占第 1 行）、是否命中核心词、原文
        todo.append([i + 2, 'Y' if CORE.search(text) else '', text])

    # 一条评论都没有，多半是酒店名写错了；停下，不写任何文件
    if total == 0:
        sys.exit(f'hotel not found: {hotel!r}, check the exact Hotel_Name')

    # 存待读清单
    with open('todo.csv', 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(HEADER)
        w.writerows(todo)
    # 第 0 轮要读的 = 命中核心词的
    with open('new_hits.csv', 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(HEADER)
        w.writerows(t for t in todo if t[1] == 'Y')
    # 新建空的判断表，只有表头
    with open('judgments.csv', 'w', newline='', encoding='utf-8') as f:
        csv.writer(f).writerow(
            ['row', 'round', 'is_noise', 'category', 'quote', 'reason'])
    # 存下评论总数，后面算指标用
    with open('total.txt', 'w', encoding='utf-8') as f:
        f.write(str(total))
    # 清掉上一次运行留下的文件，每次从第 0 轮开始
    for old in ('log.csv', 'inference.txt', 'hotel_noise_analysis_log.xlsx'):
        if os.path.exists(old):
            os.remove(old)
    # 报告三个数字
    print('total', total, 'with_complaint', len(todo),
          'core_hits', sum(t[1] == 'Y' for t in todo))


if __name__ == '__main__':
    main()
