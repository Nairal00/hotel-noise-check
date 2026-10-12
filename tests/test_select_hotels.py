"""select_hotels.py 的测试。"""

import csv
import tempfile
import unittest
from pathlib import Path

from research_agent.select_hotels import (
    EMPTY,
    RUNS_DIR,
    folder_name,
    select_hotels,
)

# 测试用的小 CSV：Milan、评分 8.0、评论数 >= 100 的 4 家酒店
CSV = Path(__file__).parent / "data" / "milan_score_8_over_100_reviews.csv"
# 小 CSV 的地址都用这一个，倒数第二个词是城市 Milan
ADDRESS = "Via Roma 1 20123 Milan Italy"


def csv_lines(path):
    """不经过 pandas，用 csv 模块读：文件里的实际行号 -> 这一行的记录。

    utf-8-sig 去掉测试 CSV 开头的 BOM 标记。每条评论只占一行，
    所以 line_num（读到第几行）就是这条评论所在的行号。
    """
    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        return {reader.line_num: record for record in reader}


def clean(text):
    """换行和多余空格变成单个空格，和 select_hotels.py 的规则一样。"""
    return " ".join(text.split())


class TestFolderName(unittest.TestCase):
    """folder_name：酒店名 -> 文件夹名。"""

    def test_space_becomes_underscore(self):
        """空格换成 _。"""
        self.assertEqual(folder_name("Hotel Mozart"), "Hotel_Mozart")

    def test_repeated_special_chars_become_one(self):
        """连续的空格和特殊字符只留一个 _。"""
        self.assertEqual(folder_name("A  &  B's Inn"), "A_B_s_Inn")

    def test_edges_are_trimmed(self):
        """首尾的特殊字符不留 _。"""
        self.assertEqual(folder_name(" (Hotel) "), "Hotel")


class TestSelectHotels(unittest.TestCase):
    """select_hotels：用测试 CSV 筛酒店。"""

    def select(self, city="Milan", max_hotels=10):
        """调用 select_hotels，固定评分 8.0、门槛 100。"""
        return select_hotels(CSV, city, 8.0, 100, max_hotels)

    def test_four_hotels_sorted_by_reviews(self):
        """4 家都选中，按评论数从少到多。"""
        result = self.select()
        self.assertEqual(
            [(h["hotel"], h["reviews"]) for h in result],
            [("Atahotel Linea Uno", 119),
             ("Hotel Carrobbio", 131),
             ("Novotel Milano Linate Aeroporto", 189),
             ("Hotel Mozart", 512)])

    def test_max_hotels_one(self):
        """max_hotels=1 时只剩评论最少的那家。"""
        result = self.select(max_hotels=1)
        self.assertEqual([h["hotel"] for h in result], ["Atahotel Linea Uno"])

    def test_work_dir(self):
        """工作目录是 runs/<城市>/<评分>/<酒店文件夹名> 的完整路径。"""
        result = self.select(max_hotels=1)
        expected = RUNS_DIR / "Milan" / "8.0" / "Atahotel_Linea_Uno"
        self.assertEqual(result[0]["work_dir"], str(expected))

    def test_runs_dir_in_project(self):
        """runs/ 在项目根目录下（和 tests/ 同一级）。"""
        self.assertEqual(RUNS_DIR, Path(__file__).resolve().parent.parent / "runs")

    def test_city_ignores_case(self):
        """输入小写 milan，结果一样，文件夹仍用地址里的 Milan。"""
        self.assertEqual(self.select(city="milan"), self.select())

    def test_no_match_returns_empty(self):
        """CSV 里没有的城市，返回空列表。"""
        self.assertEqual(self.select(city="Paris"), [])


class TestComplaints(unittest.TestCase):
    """complaints：用测试 CSV 核对行号和差评清洗。"""

    @classmethod
    def setUpClass(cls):
        """4 家酒店只筛一次；另用 csv 模块读出每一行，作为对照。"""
        cls.hotels = select_hotels(CSV, "Milan", 8.0, 100, 10)
        cls.lines = csv_lines(CSV)

    def lines_of(self, hotel):
        """对照：这家酒店在测试 CSV 里的 {行号: 记录}。"""
        return {n: r for n, r in self.lines.items()
                if r["Hotel_Name"].strip() == hotel}

    def test_rows_match_csv_lines(self):
        """每条差评的行号，就是它在测试 CSV 里实际所在的行。"""
        for h in self.hotels:
            for c in h["complaints"]:
                record = self.lines[c["row"]]
                self.assertEqual(record["Hotel_Name"].strip(), h["hotel"])
                self.assertEqual(clean(record["Negative_Review"]), c["text"])

    def test_reviews_count_all_rows(self):
        """reviews 算这家的全部评论，包括没写差评的。"""
        for h in self.hotels:
            self.assertEqual(h["reviews"], len(self.lines_of(h["hotel"])))
            self.assertLess(len(h["complaints"]), h["reviews"])

    def test_written_reviews_all_kept(self):
        """写了差评的一条不少，没写的一条不多。"""
        for h in self.hotels:
            expected = [n for n, r in self.lines_of(h["hotel"]).items()
                        if clean(r["Negative_Review"]).lower() not in EMPTY]
            self.assertEqual([c["row"] for c in h["complaints"]], expected)

    def test_empty_like_reviews_left_out(self):
        """空的、None、No Negative 不进清单（测试 CSV 里这几种都有）。"""
        skipped = {n for n, r in self.lines.items()
                   if r["Negative_Review"].strip() in ("", "None", "No Negative")}
        kept = {c["row"] for h in self.hotels for c in h["complaints"]}
        self.assertTrue(skipped)
        self.assertFalse(skipped & kept)

    def test_spaces_collapsed(self):
        """原文里没有换行、首尾空格和连续空格。"""
        for h in self.hotels:
            for c in h["complaints"]:
                self.assertEqual(c["text"], clean(c["text"]))


def select_tiny(rows):
    """临时写一个小 CSV 再筛 Milan、8.0；测完临时文件夹自动删除。

    rows 的每一项是 (评分, 差评)，酒店都是 Tiny Inn。
    """
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "tiny.csv"
        with open(path, "w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["Hotel_Name", "Hotel_Address",
                             "Average_Score", "Negative_Review"])
            for score, review in rows:
                writer.writerow(["Tiny Inn", ADDRESS, score, review])
        return select_hotels(path, "Milan", 8.0, 1, 1)


class TestTinyCsv(unittest.TestCase):
    """用几行的小 CSV，测测试 CSV 里没有的情况。"""

    def test_na_kept_as_text(self):
        """NA 照原样当文字留下（pandas 默认会读成 NaN）；空的、None 不留。"""
        hotel = select_tiny([("8", "NA"), ("8", ""), ("8", " None "),
                             ("8", "  thin   walls\there ")])[0]
        self.assertEqual(hotel["reviews"], 4)
        self.assertEqual(hotel["complaints"],
                         [{"row": 2, "text": "NA"},
                          {"row": 5, "text": "thin walls here"}])

    def test_blank_score_does_not_hide_hotel(self):
        """评分有一个空格子时，其他行照常筛出；空格子那一行不算。"""
        hotel = select_tiny([("8", "noisy"), ("", "loud")])[0]
        self.assertEqual(hotel["reviews"], 1)
        self.assertEqual(hotel["complaints"], [{"row": 2, "text": "noisy"}])


if __name__ == "__main__":
    unittest.main()
