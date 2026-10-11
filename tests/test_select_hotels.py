"""select_hotels.py 的测试（happy path）。"""

import unittest
from pathlib import Path

from research_agent.select_hotels import RUNS_DIR, folder_name, select_hotels

# 测试用的小 CSV：Milan、评分 8.0、评论数 >= 100 的 4 家酒店
CSV = Path(__file__).parent / "data" / "milan_score_8_over_100_reviews.csv"


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


if __name__ == "__main__":
    unittest.main()
