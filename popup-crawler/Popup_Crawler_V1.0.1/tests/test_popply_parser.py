from __future__ import annotations

import unittest

from crawlers.popply import parse_list_html
from crawlers.popply_detail import extract_explicit_offline_period, parse_detail_html
from run_popply import enrich_with_details
from datetime import date


LIST_HTML = """
<div class="calendar-popup-list popuplist-board"><ul>
<li><div>
  <a class="popup-img-wrap" data-image="https://cdn.example/5866" href="/popup/5866"></a>
  <div class="popup-info-wrap">
    <a data-track-component="PopupListCardInfo" href="/popup/5866">
      <ul class="popup-info-wrap-lower">
        <li class="popup-category"><p class="calendar-store-category">뷰티/헬스</p></li>
        <li class="popup-name"><p>올리브영 시티 로그 팝업</p></li>
        <li><p class="popup-date">26.08.29 - 26.09.13</p></li>
        <li class="popup-location">서울 성동구</li>
      </ul>
    </a>
  </div>
</div></li>
<li><div><div class="popup-info-wrap">
  <a data-track-component="PopupListCardInfo" href="/popup/9999">
    <p class="calendar-store-category">패션</p><p class="popup-name">부산 행사</p>
    <p class="popup-date">26.08.29 - 26.09.13</p><p class="popup-location">부산 해운대구</p>
  </a>
</div></div></li>
</ul></div>
"""


DETAIL_HTML = """
<html><head><meta property="og:image" content="https://cdn.example/main.jpg"></head><body>
<div class="popupdetail-title-info">
  <p class="calendar-store-category">뷰티/헬스</p>
  <h1 class="tit">올리브영 시티 로그 팝업</h1>
  <p class="date">26.08.29 - 26.09.13</p>
  <p class="location">서울 성동구 연무장7길 13 올리브영N 성수<button>지도보기</button></p>
  <div class="search-box-inner"><ul><li data-track-value="산리오">산리오</li></ul></div>
</div>
<div class="popupdetail-link"><a href="https://example.com/reserve"><span>사전예약</span></a></div>
<div class="popupdetail-icon-area"><ul>
  <li class="false"><p>주차가능</p></li><li><p>주차불가</p></li><li><p>사전예약</p></li>
</ul></div>
<div class="popupdetail-time"><li class="working-hours__item"><span>월~일 :</span><span>10:00 - 22:00</span></li></div>
<div class="popupdetail-caution"><div class="session-content"><p>선착순 종료</p></div></div>
<div class="popupdetail-info"><div class="popupdetail-info-inner"><p>콜라보 상품과 체험 공간</p></div>
<p class="popupdetail-warning-text">무단 배포 금지</p></div>
</body></html>
"""


class PopplyParserTests(unittest.TestCase):
    def test_explicit_offline_period_is_separated_from_online_header(self) -> None:
        description = """[ONLINE] Period: 2026.08.27 14:00 ~ 2026.09.17 23:59
[OFFLINE POP-UP] Location: Olive Young Doota Branch
Period: 2026.09.08(Tue) 10:30 ~ 2026.09.17(Thu) 23:59 (KST)"""
        self.assertEqual(
            ("2026-09-08", "2026-09-17"),
            extract_explicit_offline_period(description),
        )

    def test_enrichment_prefers_explicit_offline_period_but_preserves_header(self) -> None:
        list_row = {
            "source": "popply", "source_id": "5864", "name": "베리베리 팝업",
            "start_date": "2026-08-27", "end_date": "2026-09-17",
            "detail_url": "https://popply.co.kr/popup/5864",
        }
        detail = {
            "source_id": "5864", "fetch_ok": True, "parse_source": "rendered_public_dom",
            "title_detail": "베리베리 팝업", "category_detail": "연예/크리에이터",
            "start_date_detail": "2026-08-27", "end_date_detail": "2026-09-17",
            "physical_start_date": "2026-09-08", "physical_end_date": "2026-09-17",
            "physical_period_source": "description_explicit_offline_popup",
            "parse_warnings": ["source_header_offline_period_conflict"],
        }
        row = enrich_with_details([list_row], [detail], today=date(2026, 8, 31))[0]
        self.assertEqual("2026-09-08", row["start_date"])
        self.assertEqual("2026-08-27", row["source_header_start_date"])
        self.assertEqual("UPCOMING", row["status"])

    def test_list_parser_keeps_only_explicit_seoul_cards(self) -> None:
        rows = parse_list_html(LIST_HTML, source_status="진행 중", crawled_at="2026-08-31T12:00:00+09:00")
        self.assertEqual(1, len(rows))
        self.assertEqual("5866", rows[0].source_id)
        self.assertEqual("2026-08-29", rows[0].start_date)
        self.assertEqual("https://cdn.example/5866", rows[0].image_url)

    def test_detail_parser_extracts_public_dom_fields(self) -> None:
        row = parse_detail_html(
            DETAIL_HTML,
            source_id="5866",
            detail_url="https://popply.co.kr/popup/5866",
        )
        self.assertEqual("서울 성동구 연무장7길 13", row["address"])
        self.assertEqual("올리브영N 성수", row["venue_name"])
        self.assertEqual("성동구", row["district"])
        self.assertEqual(["산리오"], row["tags_raw"])
        self.assertTrue(row["reservation_info_present"])
        self.assertEqual("https://example.com/reserve", row["reservation_url"])
        self.assertTrue(row["copyright_warning_present"])


if __name__ == "__main__":
    unittest.main()
