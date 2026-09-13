"""crawler 解析器离线测试：用真实抓取的列表页样本（样例城市 fixture）验证。

运行：cd 01_house_capture && python3 -m tests.test_parser
或：python3 tests/test_parser.py
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "local-service"))

import crawler  # noqa: E402
import site_config  # noqa: E402

BASE = site_config.base_url()  # 站点根来自配置层，测试不硬编码

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
            self.assertTrue(house["url"].startswith(BASE + "/"))
            self.assertTrue(house["title"])

    def test_first_house_fields(self):
        house = self.result["houses"][0]
        self.assertEqual(house["url"], BASE + "/zufang/HZ2177359430218153984.html")
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
        self.assertEqual(crawler.build_list_url(), BASE + "/zufang/")

    def test_full_filters(self):
        url = crawler.build_list_url(
            district="xihuqu4", page=2, price_tier=3, rooms=1,
            rent_type="whole", keyword="地铁", sort="rco11",
        )
        self.assertEqual(
            url,
            BASE + "/zufang/xihuqu4/pg2rt200600000001rp3l1rco11rs%E5%9C%B0%E9%93%81/",
        )

    def test_page_one_no_token(self):
        url = crawler.build_list_url(district="binjiangqu", page=1, rent_type="shared")
        self.assertEqual(url, BASE + "/zufang/binjiangqu/rt200600000002/")

    def test_district_dynamic_discovery(self):
        """区域表零硬编码：从列表页动态发现（样例 fixture 应能发现西湖区等）。"""
        fixture = FIXTURE.read_text(encoding="utf-8")
        discovered = crawler.parse_districts(fixture)
        names = {d["name"] for d in discovered}
        for expected in ("西湖区", "滨江区", "余杭区", "萧山区", "上城区"):
            self.assertIn(expected, names)
        xihu = next(d for d in discovered if d["name"] == "西湖区")
        self.assertEqual(xihu["slug"], "xihuqu4")
        self.assertEqual(crawler.DISTRICTS, [])  # 无 site.json 时静态表为空，全靠动态发现


class PolitenessAndAntiDetectionTest(unittest.TestCase):
    """反检测/礼貌抓取行为测试。"""

    def test_verify_page_detection(self):
        self.assertTrue(crawler.is_verify_page("<html><head><title>人机验证</title></head></html>"))
        self.assertTrue(crawler.is_verify_page('<meta name="ke-passport" content="CAPTCHA"/><title>验证</title>'))
        # 登录页走 LoginRequired 分支，不与人机验证混淆
        self.assertFalse(crawler.is_verify_page('<meta name="ke-passport" content="LOGIN"/><title>登录</title>'))
        fixture = FIXTURE.read_text(encoding="utf-8")
        self.assertFalse(crawler.is_verify_page(fixture))

    def test_backoff_monotonic_with_jitter(self):
        for _ in range(20):
            delays = [crawler.backoff_delay(a) for a in range(4)]
            self.assertEqual(delays, sorted(delays))
            self.assertGreater(delays[0], 2.0)
            self.assertLess(delays[0], 3.5)

    def test_headers_browser_like(self):
        headers = crawler.build_headers()
        self.assertEqual(headers["Sec-Fetch-Mode"], "navigate")
        self.assertEqual(headers["Sec-Fetch-Site"], "none")
        self.assertNotIn("Referer", headers)
        with_ref = crawler.build_headers(referer=BASE + "/zufang/")
        self.assertEqual(with_ref["Sec-Fetch-Site"], "same-origin")
        self.assertEqual(with_ref["Referer"], BASE + "/zufang/")
        with_cookie = crawler.build_headers(cookie="lianjia_uuid=abc")
        self.assertEqual(with_cookie["Cookie"], "lianjia_uuid=abc")

    def test_risk_control_errors_exist(self):
        for cls in (crawler.LoginRequiredError, crawler.CaptchaError, crawler.RiskControlError):
            self.assertTrue(issubclass(cls, RuntimeError))


if __name__ == "__main__":
    unittest.main(verbosity=2)
