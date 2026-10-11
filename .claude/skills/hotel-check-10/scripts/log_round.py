"""每轮读完后：记录本轮到 log.csv。

用法: python scripts/log_round.py --round 0 \
          --keyword "nois|thin wall|siren" --reasoning "initial core keywords"
"""
import argparse
import csv
import os
import sys

LOG_HEADER = ['round', 'keyword', 'reasoning', 'new_hits_current_round',
              'new_positive_noise_reviews', 'occurrence_rate',
              'unavoidable_rate', 'hit_rows', 'noise_rows']


def read(path):
    """把一个 CSV 读成一行行的字典。"""
    with open(path, encoding='utf-8') as f:
        return list(csv.DictReader(f))


def main():
    """核对本轮有没有漏读，然后追加一行记录。"""
    parser = argparse.ArgumentParser()
    parser.add_argument('--round', type=int, required=True)
    parser.add_argument('--keyword', required=True)
    parser.add_argument('--reasoning', required=True,
                        help='why this keyword was added, in English')
    args = parser.parse_args()
    # 第 1 步生成的文件，缺了就提示先跑 prepare.py
    for path in ('total.txt', 'new_hits.csv', 'judgments.csv'):
        if not os.path.exists(path):
            sys.exit(f'{path} not found: run scripts/prepare.py first')

    # 第 1 步存下的评论总数
    with open('total.txt', encoding='utf-8') as f:
        total = int(f.read())
    # 本轮读的原数据行号
    hits = sorted({r['row'] for r in read('new_hits.csv')}, key=int)
    # 到目前为止的全部判断
    judg = read('judgments.csv')
    # 本轮命中、但还没有判断的行号；有漏读就停下，不写记录
    missing = set(hits) - {j['row'] for j in judg}
    if missing:
        sys.exit(f'missing rows {sorted(missing, key=int)}: read them first')
    # 累计的噪音差评
    noise = [j for j in judg if j['is_noise'] == 'yes']
    # 本轮新增的真噪音抱怨的行号
    noise_rows = [j['row'] for j in noise if j['row'] in hits]
    # 累计 unavoidable 的条数
    unavoid = sum(1 for j in noise if j['category'] == 'unavoidable')
    # occurrence_rate：碰上噪音的概率
    occ = len(noise) / total
    # unavoidable_rate；还没有噪音差评时记 0
    unav = unavoid / len(noise) if noise else 0
    # 第一次写时要先写表头
    first = not os.path.exists('log.csv')
    # 'a' = 追加，不覆盖之前的轮次
    with open('log.csv', 'a', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        if first:
            w.writerow(LOG_HEADER)
        # 比例存成小数，Excel 里再显示成百分比；行号用逗号隔开放在一格里
        w.writerow([args.round, args.keyword, args.reasoning, len(hits),
                    len(noise_rows), round(occ, 4), round(unav, 4),
                    ', '.join(hits), ', '.join(noise_rows)])
    # 显示目前的完整记录
    with open('log.csv', encoding='utf-8') as f:
        print(f.read())


if __name__ == '__main__':
    main()
