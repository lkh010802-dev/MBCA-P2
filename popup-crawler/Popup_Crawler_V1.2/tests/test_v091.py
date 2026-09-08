from __future__ import annotations

import unittest

from crawlers.dayforyou import BASE_URLS, SITE_URL
from crawlers.dayforyou_detail import _detail_url_candidates


class V091Tests(unittest.TestCase):
    def test_dayforyou_apex_host_is_primary(self):
        self.assertEqual("https://dayforyou.com", SITE_URL)
        self.assertEqual("https://dayforyou.com/getScheduleList", BASE_URLS[0])
        self.assertIn("https://www.dayforyou.com/getScheduleList", BASE_URLS)

    def test_detail_url_has_www_fallback(self):
        urls = _detail_url_candidates("https://dayforyou.com/getDetail?scheduleSeq=123", "123")
        self.assertEqual("https://dayforyou.com/getDetail?scheduleSeq=123", urls[0])
        self.assertIn("https://www.dayforyou.com/getDetail?scheduleSeq=123", urls)


if __name__ == "__main__":
    unittest.main()
