"""筛出要查的酒店：某城市、评分正好等于某值、评论数达到门槛。

由 agent.py 在启动 Claude 之前调用，不花钱。
从 donor code hotel-check-10/scripts/list_hotels.py 改过来。
"""

import re  # 正则表达式，用来把特殊字符换成 _
from pathlib import Path  # 用来拼接文件路径

import pandas as pd  # 用 pandas 读 CSV

# 只读需要的列，速度更快、更省内存
COLUMNS = ["Hotel_Name", "Hotel_Address", "Average_Score"]
# 报告都放在 research-agent/runs/ 下；本文件在 research_agent/ 里，项目根目录是上一级
RUNS_DIR = Path(__file__).resolve().parent.parent / "runs"


def folder_name(hotel):
    """把酒店名变成文件夹名：空格和特殊字符换成 _，连续的只留一个。

    例子："Hotel Mozart" -> "Hotel_Mozart"
    """
    # [^A-Za-z0-9]+ 表示"一个或多个不是字母、数字的字符"，整段换成一个 _
    name = re.sub(r"[^A-Za-z0-9]+", "_", hotel)
    # 去掉开头和结尾的 _（酒店名首尾是特殊字符时会出现）
    return name.strip("_")


def select_hotels(csv_path, city, score, min_reviews, max_hotels):
    """返回要查的酒店列表，按评论数从少到多，最多 max_hotels 家。

    每家酒店是一个字典：
        hotel    酒店原名（已去掉首尾空格）
        reviews  这家酒店在 CSV 里的行数
        work_dir 工作目录完整路径：runs/<城市>/<评分>/<酒店文件夹名>
    一家都没有时返回空列表。
    """
    df = pd.read_csv(csv_path, usecols=COLUMNS)

    # 地址里倒数第二个词是城市名，例如 "... 20123 Milan Italy" 中的 "Milan"
    # 注意：英国地址以 "United Kingdom" 结尾，这样会取到 "United"，本项目不处理英国
    df = df.assign(city=df["Hotel_Address"].str.split().str[-2])
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
         "work_dir": str(base / folder_name(row.Hotel_Name))}
        for row in hotels.itertuples(index=False)
    ]
