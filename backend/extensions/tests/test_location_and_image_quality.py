from conditions import extract_explicit_activity_location
from naver_image_service import _select_image


def test_activity_location_accepts_recommendation_wording():
    assert extract_explicit_activity_location("성수역에서 갈만한 팝업 추천해줘") == "성수역"


def test_image_filter_rejects_real_estate_result():
    items = [{
        "title": "성수역 원룸 월세 매물",
        "thumbnail": "https://example.com/wrong.jpg",
        "sizewidth": "1200",
        "sizeheight": "900",
    }]
    assert _select_image("성수역 산책길", items, "walk") is None


def test_image_filter_accepts_matching_walk_result():
    items = [{
        "title": "서울숲 산책 공원 풍경",
        "thumbnail": "https://example.com/park.jpg",
        "sizewidth": "1200",
        "sizeheight": "900",
    }]
    result = _select_image("서울숲", items, "walk")
    assert result["title"] == "서울숲 산책 공원 풍경"
