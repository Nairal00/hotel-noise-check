"""筛出要查的酒店：某城市、评分正好等于某值、评论数达到门槛。

同时给出每家选中酒店写了差评的评论，CSV 只读一次。
"""

import re  # 正则表达式，用来把特殊字符换成 _
from pathlib import Path  # 用来拼接文件路径

import pandas as pd  # 用 pandas 读 CSV

# 只读需要的列，速度更快、更省内存
COLUMNS = ["Hotel_Name", "Hotel_Address", "Average_Score", "Negative_Review"]
# 视为"没写差评"的内容（比较前已转小写），和 prepare.py 一样
EMPTY = {"", "no negative", "nothing", "none", "n a", "no complaints"}
# 报告都放在 hotel_noise_check_python/runs/ 下；本文件在 hotel_checker_agent/ 里，项目根目录是上一级
RUNS_DIR = Path(__file__).resolve().parent.parent / "runs"


def folder_name(hotel):
    """把酒店名变成文件夹名：空格和特殊字符换成 _，连续的只留一个。

    例子："Hotel Mozart" -> "Hotel_Mozart"
    """
    # [^A-Za-z0-9]+ 表示"一个或多个不是字母、数字的字符"，整段换成一个 _
    name = re.sub(r"[^A-Za-z0-9]+", "_", hotel)
    # 去掉开头和结尾的 _（酒店名首尾是特殊字符时会出现）
    return name.strip("_")


def complaints(rows):
    """一家酒店写了差评的评论：[{"row": 行号, "text": 原文}, ...]，按行号排。

    原文的换行和多余空格变成单个空格；EMPTY 里的算没写差评，不放进来。
    """
    result = []
    for row, raw in zip(rows["row"], rows["Negative_Review"]):
        text = " ".join(raw.split())
        if text.lower() not in EMPTY:
            result.append({"row": int(row), "text": text})
    return result


def select_hotels(csv_path, city, score, min_reviews, max_hotels):
    """返回要查的酒店列表，按评论数从少到多，最多 max_hotels 家。

    每家酒店是一个字典：
        hotel      酒店原名（已去掉首尾空格）
        reviews    这家酒店在 CSV 里的行数，即评论总数（含没写差评的）
        work_dir   工作目录完整路径：runs/<城市>/<评分>/<酒店文件夹名>
        complaints 写了差评的评论，见 complaints()
    一家都没有时返回空列表。
    """
    # keep_default_na=False：空格子、"NA"、"None" 等照原样读成文字，
    # 否则 pandas 会把它们变成 NaN（不是文字，后面合并空格会报错）
    df = pd.read_csv(csv_path, usecols=COLUMNS, keep_default_na=False)
    # 行号在筛选之前定下来：pandas 编号从 0 开始，表头占第 1 行，所以 +2
    df = df.assign(row=df.index + 2)
    # 上面的设置下，评分只要有一个空格子，整列都会变成文字，"8" == 8.0 不成立，
    # 一家酒店都筛不出来。这里转回数字；空格子变成 NaN，那一行不算（和以前一样）
    df = df.assign(Average_Score=pd.to_numeric(df["Average_Score"]))

    # 地址里倒数第二个词是城市名，例如 "... 20123 Milan Italy" 中的 "Milan"
    # 英国地址例外："... London SW5 9NB United Kingdom"，邮编和国名各两个词，
    # 城市是倒数第五个词
    words = df["Hotel_Address"].str.split()
    is_uk = words.str[-1] == "Kingdom"
    df = df.assign(city=words.str[-5].where(is_uk, words.str[-2]))
    # 忽略大小写比较城市名，只留这个城市的行
    df = df[df["city"].str.lower() == city.lower()]
    # 评分正好等于 score；CSV 里存的是 8，读进来是数字 8.0，可以直接比较
    df = df[df["Average_Score"] == score]
    if df.empty:
        return []

    # 城市文件夹名用地址里的写法：输入 milan 也进 Milan 文件夹
    city_folder = df["city"].iloc[0]
    # 有些酒店名末尾带空格，先去掉，否则同一家酒店会被分成两组
    df = df.assign(Hotel_Name=df["Hotel_Name"].str.strip())

    # 按酒店分组，数每家有几行；reset_index 把结果变回普通表格
    hotels = df.groupby("Hotel_Name").size().reset_index(name="reviews")
    # 去掉评论数不到门槛的酒店
    hotels = hotels[hotels["reviews"] >= min_reviews]
    # 按评论数从少到多排；一样多时按酒店名排，保证每次顺序一样
    hotels = hotels.sort_values(["reviews", "Hotel_Name"])
    # 只取前 max_hotels 家
    hotels = hotels.head(max_hotels)

    # 评分文件夹名保留一位小数，例如 8 -> "8.0"
    base = RUNS_DIR / city_folder / f"{score:.1f}"
    return [
        {"hotel": row.Hotel_Name,
         "reviews": int(row.reviews),
         "work_dir": str(base / folder_name(row.Hotel_Name)),
         "complaints": complaints(df[df["Hotel_Name"] == row.Hotel_Name])}
        for row in hotels.itertuples(index=False)
    ]
