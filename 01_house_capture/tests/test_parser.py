"""crawler 解析器离线测试：用真实抓取的 hz.zu.ke.com 列表页样本验证。

运行：cd 01_house_capture && python3 -m tests.test_parser
或：python3 tests/test_parser.py
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "local-service"))

import crawler  # noqa: E402

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "zufang_list_sample.html"


class ParseListPageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = FIXTURE.read_text(encoding="utf-8")
        cls.result = crawler.parse_list_page(cls.html)

    def test_page_meta(self):
        self.assertEqual(self.result["total"], 58012)
        self.assertEqual(self.result["cur_page"], 1)
        self.assertEqual(self.result["total_page"], 100)

    def test_all_items_parsed(self):
        self.assertEqual(len(self.result["houses"]), 30)
        for house in self.result["houses"]:
            self.assertTrue(house["url"].startswith("https://hz.zu.ke.com/"))
            self.assertTrue(house["title"])

    def test_first_house_fields(self):
        house = self.result["houses"][0]
        self.assertEqual(house["url"], "https://hz.zu.ke.com/zufang/HZ2177359430218153984.html")
        self.assertEqual(house["house_code"], "HZ2177359430218153984")
        self.assertEqual(house["title"], "整租·理想康城国际 3室2厅 南")
        self.assertEqual(house["rent_type"], "整租")
        self.assertEqual(house["community"], "理想康城国际")
        self.assertEqual(house["district"], "临平区")
        self.assertEqual(house["bizcircle"], "临平新城")
        self.assertEqual(house["area_sqm"], 126.07)
        self.assertEqual(house["orientation"], "南")
        self.assertEqual(house["layout"], "3室2厅2卫")
        self.assertEqual(house["rent_monthly"], 2800)
        self.assertEqual(house["deposit"], "押一付一")
        self.assertIn("精装", house["tags"])
        self.assertTrue(house["image"].startswith("https://"))

    def test_apartment_items_supported(self):
        apartments = [h for h in self.result["houses"] if "/apartment/" in h["url"]]
        self.assertGreater(len(apartments), 0)
        for apt in apartments:
            self.assertIsNotNone(apt["rent_monthly"])
            self.assertTrue(apt["community"])

    def test_login_page_detection(self):
        self.assertTrue(crawler.is_login_page('<meta name="ke-passport" content="LOGIN"/><title>登录</title>'))
        self.assertFalse(crawler.is_login_page(self.html))


class BuildUrlTest(unittest.TestCase):
    def test_plain_list(self):
        self.assertEqual(crawler.build_list_url(), "https://hz.zu.ke.com/zufang/")

    def test_full_filters(self):
        url = crawler.build_list_url(
            district="xihuqu4", page=2, price_tier=3, rooms=1,
            rent_type="whole", keyword="地铁", sort="rco11",
        )
        self.assertEqual(
            url,
            "https://hz.zu.ke.com/zufang/xihuqu4/pg2rt200600000001rp3l1rco11rs%E5%9C%B0%E9%93%81/",
        )

    def test_page_one_no_token(self):
        url = crawler.build_list_url(district="binjiangqu", page=1, rent_type="shared")
        self.assertEqual(url, "https://hz.zu.ke.com/zufang/binjiangqu/rt200600000002/")

    def test_district_slugs(self):
        names = {d["name"] for d in crawler.DISTRICTS}
        for expected in ("西湖区", "滨江区", "余杭区", "萧山区", "上城区"):
            self.assertIn(expected, names)
        xihu = next(d for d in crawler.DISTRICTS if d["name"] == "西湖区")
        self.assertEqual(xihu["slug"], "xihuqu4")


if __name__ == "__main__":
    unittest.main(verbosity=2)
