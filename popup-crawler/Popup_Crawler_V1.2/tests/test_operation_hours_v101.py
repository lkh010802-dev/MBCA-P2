from __future__ import annotations

import unittest
from pathlib import Path

from crawlers.dayforyou_detail import parse_detail_html
from normalization.operation_hours import parse_operation_schedule, resolve_schedule_for_day


class OperationHoursParserTests(unittest.TestCase):
    def test_daily_simple(self):
        schedule, opening, closing = parse_operation_schedule(["매일 12:00 ~ 20:00"])
        self.assertEqual("12:00", opening)
        self.assertEqual("20:00", closing)
        self.assertEqual(7, len(schedule[0]["days"]))

    def test_weekday_weekend_split(self):
        schedule, opening, closing = parse_operation_schedule([
            "평일 10:30~20:00",
            "금~일/공휴일 10:30~20:30",
        ])
        self.assertIsNone(opening)
        self.assertIsNone(closing)
        self.assertEqual(["MON", "TUE", "WED", "THU"], schedule[0]["days"])
        self.assertTrue(any(item.get("closing_time") == "20:30" for item in schedule))
        self.assertTrue(any("PUBLIC_HOLIDAY" in item.get("special_days", []) for item in schedule))

    def test_slash_separates_two_weekday_schedules(self):
        schedule, opening, closing = parse_operation_schedule([
            "월-목 10:30-20:00 / 금-일 10:30-20:30"
        ])
        self.assertEqual(["MON", "TUE", "WED", "THU"], schedule[0]["days"])
        self.assertEqual("20:00", schedule[0]["closing_time"])
        self.assertEqual(["FRI", "SAT", "SUN"], schedule[1]["days"])
        self.assertEqual("20:30", schedule[1]["closing_time"])
        self.assertIsNone(opening)
        self.assertIsNone(closing)

    def test_holiday_slash_is_not_split_from_day_range(self):
        schedule, _, _ = parse_operation_schedule(["금~일/공휴일 10:30~20:30"])
        self.assertEqual(1, len(schedule))
        self.assertEqual(["FRI", "SAT", "SUN"], schedule[0]["days"])
        self.assertEqual(["PUBLIC_HOLIDAY"], schedule[0]["special_days"])

    def test_closed_day(self):
        schedule, opening, closing = parse_operation_schedule([
            "월 : 휴무", "화~토 : 12:00 - 21:00", "일 : 12:00 - 18:00"
        ])
        self.assertTrue(any(item.get("closed") for item in schedule))
        self.assertIsNone(opening)
        self.assertIsNone(closing)


    def test_weekday_weekend_flat_bounds(self):
        schedule, opening, closing = parse_operation_schedule([
            "월~토 : 10:30 - 20:30",
            "일 : 11:00 - 20:30",
        ])
        self.assertIsNone(opening)
        self.assertIsNone(closing)
        self.assertEqual(2, len(schedule))

    def test_adjacent_schedules_without_separator(self):
        schedule, opening, closing = parse_operation_schedule([
            "월-목 10:00 ~ 20:00 금-일 10:00 ~ 20:30"
        ])
        self.assertEqual(["MON", "TUE", "WED", "THU"], schedule[0]["days"])
        self.assertEqual(["FRI", "SAT", "SUN"], schedule[1]["days"])
        self.assertEqual((None, None), (opening, closing))

    def test_english_weekday_schedule(self):
        schedule, opening, closing = parse_operation_schedule([
            "MON-FRI,SUN 12:00 - 21:30 | SAT 12:00 - 19:00"
        ])
        self.assertEqual(["MON", "TUE", "WED", "THU", "FRI", "SUN"], schedule[0]["days"])
        self.assertEqual(["SAT"], schedule[1]["days"])
        self.assertEqual((None, None), (opening, closing))

    def test_single_overnight_window_is_flattened(self):
        schedule, opening, closing = parse_operation_schedule(["월~일 : 11:00 - 02:00"])
        self.assertEqual(("11:00", "02:00"), (opening, closing))
        self.assertEqual(7, len(schedule[0]["days"]))

    def test_multiple_daily_windows_do_not_flatten(self):
        schedule, opening, closing = parse_operation_schedule([
            "매주 금/토/일 (주간) 11:00~18:00, (야간)16:00~22:00"
        ])
        self.assertEqual(2, len(schedule))
        self.assertIsNone(opening)
        self.assertIsNone(closing)


    def test_resolves_exact_weekday_window_without_widening(self):
        schedule, _, _ = parse_operation_schedule([
            "월-목 12:00-19:00 / 금-일 09:00-22:00"
        ])
        friday = resolve_schedule_for_day(schedule, "FRI")
        monday = resolve_schedule_for_day(schedule, "MON")
        self.assertEqual("09:00", friday["today_opening_time"])
        self.assertEqual("22:00", friday["today_closing_time"])
        self.assertFalse(friday["today_closed"])
        self.assertEqual("12:00", monday["today_opening_time"])
        self.assertEqual("19:00", monday["today_closing_time"])

    def test_split_session_day_keeps_scalar_today_times_null(self):
        schedule, _, _ = parse_operation_schedule([
            "매주 금/토/일 (주간) 11:00~18:00, (야간)16:00~22:00"
        ])
        friday = resolve_schedule_for_day(schedule, "FRI")
        self.assertEqual(2, len(friday["today_schedule"]))
        self.assertIsNone(friday["today_opening_time"])
        self.assertIsNone(friday["today_closing_time"])
        self.assertFalse(friday["today_closed"])

    def test_explicit_closed_day_resolves_closed(self):
        schedule, _, _ = parse_operation_schedule([
            "월 : 휴무", "화~일 : 10:00-20:00"
        ])
        monday = resolve_schedule_for_day(schedule, "MON")
        self.assertTrue(monday["today_closed"])
        self.assertIsNone(monday["today_opening_time"])
        self.assertIsNone(monday["today_closing_time"])

    def test_repairs_obvious_single_digit_minute_typo(self):
        schedule, opening, closing = parse_operation_schedule(["매일 10:0-22:00"])
        self.assertEqual("10:00", opening)
        self.assertEqual("22:00", closing)
        self.assertEqual("10:00", schedule[0]["opening_time"])

    def test_repairs_obvious_trailing_zero_minute_typo(self):
        schedule, opening, closing = parse_operation_schedule(["매일 10:30-22:000"])
        self.assertEqual("10:30", opening)
        self.assertEqual("22:00", closing)
        self.assertEqual("22:00", schedule[0]["closing_time"])

    def test_allows_24_00_as_day_end(self):
        schedule, opening, closing = parse_operation_schedule(["매일 00:00 ~ 24:00"])
        self.assertEqual("00:00", opening)
        self.assertEqual("24:00", closing)
        self.assertEqual("24:00", schedule[0]["closing_time"])

    def test_future_notice(self):
        self.assertEqual(([], None, None), parse_operation_schedule(["운영시간 추후 공지"]))


class DayForYouOperationExtractionTests(unittest.TestCase):
    def test_extracts_labeled_time(self):
        html = '''
        <html><body>
          <div id="schedule_title">테스트 팝업</div>
          <div class="schedule_date">2026-09-01 ~ 2026-09-30</div>
          <div id="schedule_location">서울 성동구 연무장길 1</div>
          <div class="schedule_detail"><p><strong>운영시간</strong><br>
          📍 장소 : 테스트<br>📅 기간 : 2026-09-01 ~ 2026-09-30<br>
          ⏰ 시간 : 평일 10:30~20:00, 금~일/공휴일 10:30~20:30</p></div>
        </body></html>'''
        row = parse_detail_html(html, "1", "https://example.test/1")
        self.assertEqual([
            "평일 10:30~20:00, 금~일/공휴일 10:30~20:30"
        ], row.operation_hours_raw)

    def test_extracts_oberkampf_simple_time(self):
        html = """
        <html><body>
          <div id="schedule_title">[오베르캄프] 사워도우 에그타르트</div>
          <div class="schedule_date">2026-02-13 ~ 2026-12-31</div>
          <div id="schedule_location">서울 송파구 올림픽로 300 롯데월드몰</div>
          <div class="schedule_detail"><p><strong>운영시간</strong><br>
          📍 장소 : 롯데월드몰 5F 오베르캄프<br>
          📅 기간 : 2026-02-13 ~ 2026-12-31<br>
          ⏰ 시간 : 10:30~22:00<br><br><strong>콘텐츠</strong><br>테스트</p></div>
        </body></html>
        """
        row = parse_detail_html(html, "30071", "https://dayforyou.com/getDetail?scheduleSeq=30071")
        self.assertEqual(["10:30~22:00"], row.operation_hours_raw)
        schedule, opening, closing = parse_operation_schedule(row.operation_hours_raw)
        self.assertEqual("10:30", opening)
        self.assertEqual("22:00", closing)
        self.assertEqual(7, len(schedule[0]["days"]))


    def test_inline_strong_time_label_stays_on_one_logical_line(self):
        html = """
        <html><body>
          <div id="schedule_title">로이드</div>
          <div class="schedule_date">2026-07-01 ~ 2026-09-30</div>
          <div id="schedule_location">서울 마포구 양화로 188 AK플라자 홍대</div>
          <div class="schedule_detail"><p><strong>운영시간</strong><br>
          📍 장소 : AK플라자 홍대<br>📅 기간 : 2026-07-01 ~ 2026-09-30<br>
          ⏰ <strong>시간 :</strong> 10:30~20:00</p><p><strong>콘텐츠</strong><br>본문</p></div>
        </body></html>
        """
        row = parse_detail_html(html, "33312", "https://dayforyou.com/getDetail?scheduleSeq=33312")
        self.assertEqual(["10:30~20:00"], row.operation_hours_raw)

    def test_extracts_source_typo_but_preserves_raw(self):
        html = """
        <html><body>
          <div id="schedule_title">바이오힐 보 쇼룸 팝업 IN 성수</div>
          <div class="schedule_date">2026-01-05 ~ 2026-12-31</div>
          <div id="schedule_location">서울 성동구 연무장7길 13</div>
          <div class="schedule_detail"><p><strong>운영시간</strong><br>
          📍 장소 : 서울 성동구 연무장7길 13<br>⏰ 매일 10:0-22:00<br><strong>콘텐츠</strong></p></div>
        </body></html>
        """
        row = parse_detail_html(html, "24073", "https://dayforyou.com/getDetail?scheduleSeq=24073")
        self.assertEqual(["매일 10:0-22:00"], row.operation_hours_raw)
        schedule, opening, closing = parse_operation_schedule(row.operation_hours_raw)
        self.assertEqual(("10:00", "22:00"), (opening, closing))

    def test_extracts_24_hour_day_end(self):
        html = """
        <html><body>
          <div id="schedule_title">아그넬 팝업</div>
          <div class="schedule_date">2026-05-01 ~ 2026-10-11</div>
          <div id="schedule_location">서울 중구 장충단로 60</div>
          <div class="schedule_detail"><p><strong>운영시간</strong><br>
          📍 장소 : 반얀트리 서울<br>⏰ 매일 00:00 ~ 24:00<br><strong>콘텐츠</strong></p></div>
        </body></html>
        """
        row = parse_detail_html(html, "25737", "https://dayforyou.com/getDetail?scheduleSeq=25737")
        self.assertEqual(["매일 00:00 ~ 24:00"], row.operation_hours_raw)
        schedule, opening, closing = parse_operation_schedule(row.operation_hours_raw)
        self.assertEqual(("00:00", "24:00"), (opening, closing))

    def test_extracts_clock_without_time_label(self):
        html = '''
        <html><body>
          <div id="schedule_title">테스트 팝업</div>
          <div class="schedule_date">2026-09-01 ~ 2026-09-30</div>
          <div id="schedule_location">서울 중구 세종대로 1</div>
          <div class="schedule_detail"><p><strong>운영시간</strong><br>
          ⏰ 매주 금/토/일 (주간) 11:00~18:00, (야간)16:00~22:00</p></div>
        </body></html>'''
        row = parse_detail_html(html, "2", "https://example.test/2")
        self.assertEqual([
            "매주 금/토/일 (주간) 11:00~18:00, (야간)16:00~22:00"
        ], row.operation_hours_raw)

    def test_content_body_class_times_do_not_leak(self):
        html = """
        <html><body>
          <div id="schedule_title">글렌도만 영재교실</div>
          <div class="schedule_date">2026-09-03 ~ 2026-11-30</div>
          <div id="schedule_location">서울 서대문구 신촌로 83 현대백화점 신촌점</div>
          <div class="schedule_detail">기간 : 2026-09-03 ~ 2026-11-30<br>
          장소 : 9층 문화센터<br>콘텐츠 :<br>
          월요 글렌도만 영재교실 행사 정보 일시 매주 월 14:10 ~ 14:50 15:00 ~ 15:40
          </div>
        </body></html>
        """
        row = parse_detail_html(html, "class1", "https://example.test/class1")
        self.assertEqual([], row.operation_hours_raw)

    def test_content_fallback_selects_matching_venue(self):
        html = """
        <html><body>
          <div id="schedule_title">케로로 팝업</div>
          <div class="schedule_date">2026-08-28 ~ 2026-09-14</div>
          <div id="schedule_location">서울 서대문구 신촌로 83 현대백화점 신촌점</div>
          <div class="schedule_detail">기간 : 2026-08-28 ~ 2026-09-14<br>
          장소 : 신촌점<br>콘텐츠 :<br>
          📍 서울 서대문구 연세로 13 현대백화점 신촌점 U-PLEX 지하2층 🕒 10:30 ~ 22:00<br>
          📍 서울 용산구 한강대로23길 55 용산 아이파크몰 🕒 일-목 10:30 ~ 20:30 금·토 10:30 ~ 21:00
          </div>
        </body></html>
        """
        row = parse_detail_html(html, "36690", "https://dayforyou.com/getDetail?scheduleSeq=36690")
        self.assertEqual(["10:30 ~ 22:00"], row.operation_hours_raw)

    def test_content_fallback_handles_labeled_multi_venue_block(self):
        html = """
        <html><body>
          <div id="schedule_title">이누야샤 팝업</div>
          <div class="schedule_date">2026-09-01 ~ 2026-09-22</div>
          <div id="schedule_location">서울 마포구 양화로 188</div>
          <div class="schedule_detail">기간 : 2026-09-01 ~ 2026-09-22<br>콘텐츠 :<br>
          장소: AK PLAZA 홍대 4F LIMITION 주소: 서울 마포구 양화로 188 시간: 홍대 평일 11:00 - 22:00, 주말 10:30 - 22:00
          장소: AK PLAZA 수원 5F 주소: 경기 수원시 팔달구 덕영대로 924 시간: 매일 10:30 - 22:00
          </div>
        </body></html>
        """
        row = parse_detail_html(html, "37241", "https://dayforyou.com/getDetail?scheduleSeq=37241")
        self.assertEqual(["평일 11:00 - 22:00", "주말 10:30 - 22:00"], row.operation_hours_raw)


class OperationHoursMissingHotfixTests(unittest.TestCase):
    def test_space_separated_pair_is_safe_when_exactly_two_clocks(self):
        schedule, opening, closing = parse_operation_schedule(["10:30 22:00"])
        self.assertEqual(("10:30", "22:00"), (opening, closing))
        self.assertEqual(7, len(schedule[0]["days"]))

    def test_three_clock_session_list_is_not_interpreted_as_range(self):
        schedule, opening, closing = parse_operation_schedule(["월~금 15:00 17:00 19:30"])
        self.assertEqual([], schedule)
        self.assertIsNone(opening)
        self.assertIsNone(closing)

    def test_english_closed_suffix_keeps_active_and_closed_days(self):
        schedule, opening, closing = parse_operation_schedule(["11:00-18:00 (Sun, Mon close)"])
        active = next(item for item in schedule if not item["closed"])
        closed = next(item for item in schedule if item["closed"])
        self.assertEqual(["TUE", "WED", "THU", "FRI", "SAT"], active["days"])
        self.assertEqual(["SUN", "MON"], closed["days"])
        self.assertEqual((None, None), (opening, closing))

    def test_korean_closed_typo_is_preserved_as_exception(self):
        schedule, _, _ = parse_operation_schedule(["10:30-19:30", "매주 일요일 휴뮤"])
        active = next(item for item in schedule if not item["closed"])
        closed = next(item for item in schedule if item["closed"])
        self.assertEqual(["MON", "TUE", "WED", "THU", "FRI", "SAT"], active["days"])
        self.assertEqual(["SUN"], closed["days"])

    def test_extracts_midline_space_pair_time_label(self):
        html = """
        <html><body>
          <div id="schedule_title">테라리움 팝업</div>
          <div id="schedule_location">서울 서대문구 신촌로 83 현대백화점 신촌점</div>
          <div class="schedule_detail">기간 : 2026-09-04 ~ 2026-09-10 장소 : 현대백화점 신촌점 지하 2층 시간 : 10:30 22:00 콘텐츠 : 본문</div>
        </body></html>
        """
        row = parse_detail_html(html, "37292", "https://example.test/37292")
        self.assertEqual(["10:30 22:00"], row.operation_hours_raw)
        schedule, opening, closing = parse_operation_schedule(row.operation_hours_raw)
        self.assertEqual(("10:30", "22:00"), (opening, closing))
        self.assertEqual(7, len(schedule[0]["days"]))

    def test_popup_operation_marker_beats_experience_hours(self):
        html = """
        <html><body>
          <div id="schedule_title">신촌 팝업</div>
          <div id="schedule_location">서울 서대문구 신촌로 83 현대백화점 신촌점</div>
          <div class="schedule_detail">기간 : 2026-09-04 ~ 2026-09-10 콘텐츠 : 팝업 운영 10:30 — 22:00 체험 운영 11:00 — 21:00</div>
        </body></html>
        """
        row = parse_detail_html(html, "37234", "https://example.test/37234")
        self.assertEqual(["10:30 — 22:00"], row.operation_hours_raw)

    def test_multi_venue_without_markers_uses_address_local_range(self):
        html = """
        <html><body>
          <div id="schedule_title">케로로 팝업</div>
          <div id="schedule_location">서울 서대문구 신촌로 83 현대백화점 신촌점</div>
          <div class="schedule_detail">기간 : 2026-08-28 ~ 2026-09-14 콘텐츠 : 신촌점 현대백화점 신촌점 U-PLEX B2 서브스트릿 스페이스 10:30 ~ 22:00 용산점 용산 아이파크몰 리빙파크 6F 서브스트릿 스페이스 월·수·목·일 10:30 ~ 20:30 금·토 10:30 ~ 21:00</div>
        </body></html>
        """
        row = parse_detail_html(html, "36690", "https://example.test/36690")
        self.assertEqual(["10:30 ~ 22:00"], row.operation_hours_raw)

    def test_content_only_gallery_hours_with_close_suffix(self):
        html = """
        <html><body>
          <div id="schedule_title">스스로 그러한 Self-So</div>
          <div id="schedule_location">서울시 강남구 압구정로71길 14, 2층</div>
          <div class="schedule_detail">갤러리 플래닛 그룹전 2026.8.19-9.18 11:00-18:00(Sun, Mon close) 갤러리 플래닛 | 서울시 강남구 압구정로71길 14, 2층 Press Open 15:00</div>
        </body></html>
        """
        row = parse_detail_html(html, "36015", "https://example.test/36015")
        self.assertEqual(["11:00-18:00", "Sun, Mon close"], row.operation_hours_raw)
        schedule, _, _ = parse_operation_schedule(row.operation_hours_raw)
        self.assertEqual(["SUN", "MON"], next(item for item in schedule if item["closed"])["days"])

    def test_performance_session_times_stay_empty(self):
        html = """
        <html><body>
          <div id="schedule_title">연극 행오버</div>
          <div id="schedule_location">서울 대학로 정극장</div>
          <div class="schedule_detail">운영시간 장소 : 정극장 콘텐츠 : 공연 월~금 15:00 17:00 19:30 / 토요일 12:00 14:00 16:00 18:00 20:00 / 일요일 13:00 15:00 17:00 19:00</div>
        </body></html>
        """
        row = parse_detail_html(html, "6183", "https://example.test/6183")
        self.assertEqual([], row.operation_hours_raw)


if __name__ == "__main__":
    unittest.main()
