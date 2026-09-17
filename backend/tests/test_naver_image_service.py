from naver_image_service import _select_image, lookup_place_photos

def test_enrichment_is_optional_without_credentials(monkeypatch):
    monkeypatch.delenv("NAVER_CLIENT_ID", raising=False)
    monkeypatch.delenv("NAVER_CLIENT_SECRET", raising=False)
    assert lookup_place_photos([]) == {"enabled": False, "photos": []}

def test_image_selection_prefers_matching_place_title():
    result = _select_image("신림 테스트 카페", [
        {"title": "일반 커피 사진", "thumbnail": "https://example.com/a.jpg", "link": "https://example.com/a-original.jpg", "sizewidth": "2000", "sizeheight": "1500"},
        {"title": "<b>신림 테스트 카페</b> 내부", "thumbnail": "https://example.com/b.jpg", "link": "https://example.com/b-original.jpg", "sizewidth": "800", "sizeheight": "600"},
    ])
    assert result["image_url"] == "https://example.com/b.jpg"
    assert result["image_source"] == "naver_image_search"

def test_no_valid_https_image_returns_none():
    assert _select_image("장소", [{"title": "장소", "link": "http://unsafe.example/a.jpg"}]) is None
