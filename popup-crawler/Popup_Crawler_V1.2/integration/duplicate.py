from __future__ import annotations

import re
import unicodedata
from datetime import date
from collections import Counter
from difflib import SequenceMatcher
from itertools import combinations
from typing import Any


GENERIC_NAME_PARTS = (
    "팝업스토어",
    "팝업",
    "popupstore",
    "popup",
)


def compact_text(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).lower()
    text = text.replace("×", "x")
    return re.sub(r"[^0-9a-z가-힣]+", "", text)


def core_name(value: object) -> str:
    text = compact_text(value)
    for part in GENERIC_NAME_PARTS:
        text = text.replace(part, "")
    return text


def compact_address(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    text = re.sub(r"\([^)]*\)", "", text)
    text = re.sub(r"^서울(?:특별시|시)", "서울", text)
    return re.sub(r"[^0-9a-z가-힣]+", "", text.lower())




GENERIC_DISTINCTIVE_TAGS = {
    "서울", "성수", "강남", "홍대", "잠실", "여의도", "팝업", "이벤트", "행사",
    "패션", "뷰티", "굿즈", "캐릭터", "카페", "전시", "서울팝업",
    "콜라보", "콜라보카페", "협업카페", "collab", "collabcafe",
    "성수팝업", "강남팝업", "홍대팝업", "잠실팝업",
    "open", "comingsoon", "stage", "popupstage", "popupopen",
}


def _distinctive_tags(row: dict[str, Any]) -> set[str]:
    result: set[str] = set()
    context = compact_text(" ".join([
        str(row.get("venue_name") or ""),
        str(row.get("address") or ""),
        str(row.get("district") or ""),
        str(row.get("category") or ""),
        " ".join(str(x) for x in (row.get("categories") or [])),
    ]))
    for raw in row.get("tags") or []:
        value = core_name(raw)
        if not value or len(value) < 2 or value in GENERIC_DISTINCTIVE_TAGS:
            continue
        if value.endswith("카페") and len(value) <= 4:
            continue
        # Venue/location/category tags are weak identity evidence and create
        # false matches when many events share a mall.
        if len(value) >= 2 and value in context:
            continue
        result.add(value)
    return result




DESCRIPTION_TOKEN_STOPWORDS = {
    "팝업", "팝업스토어", "팝업을", "팝업에서", "팝업으로", "행사", "이벤트",
    "서울", "성수", "홍대", "강남", "현대백화점", "롯데백화점", "신세계백화점",
    "직접", "특별한", "함께", "브랜드", "컬렉션", "컬렉션을", "오픈", "open",
    "pop", "up", "the", "and", "with", "에서", "있는", "진행합니다", "선보입니다",
}


def _description_tokens(row: dict[str, Any]) -> set[str]:
    text = unicodedata.normalize("NFKC", str(row.get("description") or "")).lower()
    text = text.replace("×", " x ")
    tokens = re.findall(r"[a-z0-9]{2,}|[가-힣]{2,}", text)
    return {
        token for token in tokens
        if token not in DESCRIPTION_TOKEN_STOPWORDS and len(token) >= 2
    }


def _description_similarity(left: dict[str, Any], right: dict[str, Any]) -> tuple[float, int]:
    left_tokens = _description_tokens(left)
    right_tokens = _description_tokens(right)
    if not left_tokens or not right_tokens:
        return 0.0, 0
    shared = left_tokens & right_tokens
    union = left_tokens | right_tokens
    return (len(shared) / len(union) if union else 0.0), len(shared)


def _shared_identity_tags(left: dict[str, Any], right: dict[str, Any]) -> list[str]:
    """Return strong shared tag identity, including containment aliases.

    Source tags often encode the same brand differently, for example
    ``키움히어로즈`` vs ``키움히어로즈x디에포``.  Venue/location/category
    tags have already been removed by ``_distinctive_tags`` so a containment
    match here is reasonably strong identity evidence.
    """
    left_tags = _distinctive_tags(left)
    right_tags = _distinctive_tags(right)
    matches = set(left_tags & right_tags)
    for ltag in left_tags:
        for rtag in right_tags:
            if ltag == rtag:
                continue
            shorter, longer = sorted((ltag, rtag), key=len)
            if len(shorter) >= 4 and shorter in longer:
                matches.add(shorter)
    return sorted(matches)


def _normalized_official_url(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    # Ignore fragments and common tracking parameters, but keep page identity.
    text = text.split("#", 1)[0]
    text = re.sub(r"([?&])utm_[^=&]+=[^&]*&?", r"\1", text, flags=re.I)
    text = text.rstrip("?&/")
    return text.lower()

def _bigrams(value: str) -> set[str]:
    if not value:
        return set()
    if len(value) == 1:
        return {value}
    return {value[index:index + 2] for index in range(len(value) - 1)}


def _prepared_name(value: object) -> tuple[str, str, set[str], Counter[str], Counter[str]]:
    full = compact_text(value)
    core = core_name(value)
    return full, core, _bigrams(core), Counter(full), Counter(core)


def _sequence_ratio_upper_bound(
    left: str, right: str, left_counts: Counter[str], right_counts: Counter[str]
) -> float:
    if not left or not right:
        return 0.0
    # SequenceMatcher's total matched characters cannot exceed the character
    # multiset intersection. This is a safe upper bound, used only to skip
    # pairs that mathematically cannot reach the candidate threshold.
    max_matches = sum(
        min(count, right_counts.get(char, 0))
        for char, count in left_counts.items()
    )
    return (2.0 * max_matches) / (len(left) + len(right))


def _name_similarity_upper_bound(
    left: tuple[str, str, set[str], Counter[str], Counter[str]],
    right: tuple[str, str, set[str], Counter[str], Counter[str]],
) -> float:
    left_full, left_core, left_grams, left_full_counts, left_core_counts = left
    right_full, right_core, right_grams, right_full_counts, right_core_counts = right
    upper = _sequence_ratio_upper_bound(
        left_full, right_full, left_full_counts, right_full_counts
    )
    if left_core and right_core:
        upper = max(
            upper,
            _sequence_ratio_upper_bound(
                left_core, right_core, left_core_counts, right_core_counts
            ),
        )
    if left_grams and right_grams:
        # Jaccard cannot exceed min(size)/max(size), even with perfect overlap.
        upper = max(upper, min(len(left_grams), len(right_grams)) / max(len(left_grams), len(right_grams)))
    return upper


def _date_overlap_possible(left: dict[str, Any], right: dict[str, Any]) -> bool:
    """Cheap exact prefilter equivalent to date_overlap_coverage(...) > 0."""
    left_start = str(left["start_date"])
    right_start = str(right["start_date"])
    left_end = str(left["end_date"]) if left.get("end_date") else None
    right_end = str(right["end_date"]) if right.get("end_date") else None

    if left_end is None or right_end is None:
        if left_start == right_start:
            return True
        if left_end is None and right_end is None:
            return False
        if left_end is None:
            assert right_end is not None
            return right_start <= left_start <= right_end
        return left_start <= right_start <= left_end
    return max(left_start, right_start) <= min(left_end, right_end)


def _candidate_name_threshold(
    left: dict[str, Any],
    right: dict[str, Any],
    *,
    address_exact: bool,
    same_district: bool,
) -> float:
    if address_exact:
        return 0.25
    exact_dates = (
        left.get("start_date") == right.get("start_date")
        and left.get("end_date") == right.get("end_date")
    )
    if exact_dates and same_district:
        return 0.30
    if same_district:
        return 0.65
    return 0.90


def name_similarity(left: object, right: object) -> float:
    left_full = compact_text(left)
    right_full = compact_text(right)
    left_core = core_name(left)
    right_core = core_name(right)
    values = [SequenceMatcher(None, left_full, right_full).ratio()]
    if left_core and right_core:
        values.append(SequenceMatcher(None, left_core, right_core).ratio())
        left_grams = _bigrams(left_core)
        right_grams = _bigrams(right_core)
        union = left_grams | right_grams
        if union:
            values.append(len(left_grams & right_grams) / len(union))
    return max(values)


def date_overlap_coverage(left: dict[str, Any], right: dict[str, Any]) -> float:
    left_start = date.fromisoformat(str(left["start_date"]))
    right_start = date.fromisoformat(str(right["start_date"]))
    left_end = (
        date.fromisoformat(str(left["end_date"]))
        if left.get("end_date") else None
    )
    right_end = (
        date.fromisoformat(str(right["end_date"]))
        if right.get("end_date") else None
    )

    if left_end is None or right_end is None:
        if left_start == right_start:
            return 1.0
        known_end = left_end or right_end
        known_start = left_start if left_end else right_start
        open_start = right_start if left_end else left_start
        if known_end and known_start <= open_start <= known_end:
            return 0.5
        return 0.0

    overlap_start = max(left_start, right_start)
    overlap_end = min(left_end, right_end)
    if overlap_end < overlap_start:
        return 0.0
    overlap_days = (overlap_end - overlap_start).days + 1
    shorter_days = min(
        (left_end - left_start).days + 1,
        (right_end - right_start).days + 1,
    )
    return overlap_days / shorter_days


def duplicate_features(
    left: dict[str, Any],
    right: dict[str, Any],
) -> dict[str, Any]:
    name_score = name_similarity(left.get("name"), right.get("name"))
    left_address = compact_address(left.get("address_base") or left.get("address"))
    right_address = compact_address(right.get("address_base") or right.get("address"))
    address_exact = bool(left_address and left_address == right_address)
    address_conflict = bool(left_address and right_address and not address_exact)
    same_district = bool(
        left.get("district")
        and left.get("district") == right.get("district")
    )
    overlap = date_overlap_coverage(left, right)
    exact_dates = (
        left.get("start_date") == right.get("start_date")
        and left.get("end_date") == right.get("end_date")
    )
    same_end_date = bool(
        left.get("end_date")
        and left.get("end_date") == right.get("end_date")
    )
    exact_core_name = bool(
        core_name(left.get("name"))
        and core_name(left.get("name")) == core_name(right.get("name"))
    )
    left_core = core_name(left.get("name"))
    right_core = core_name(right.get("name"))
    shorter_core, longer_core = sorted((left_core, right_core), key=len)
    core_containment = bool(
        len(shorter_core) >= 2 and shorter_core in longer_core
    )
    shared_distinctive_tags = _shared_identity_tags(left, right)
    description_token_jaccard, shared_description_token_count = _description_similarity(left, right)
    left_official = _normalized_official_url(left.get("official_url"))
    right_official = _normalized_official_url(right.get("official_url"))
    official_url_exact = bool(left_official and left_official == right_official)

    score = 45.0 * name_score
    score += 30.0 if address_exact else 0.0
    score += 5.0 if same_district else 0.0
    score += 20.0 if exact_dates else 15.0 * overlap
    score = round(min(100.0, score), 2)

    return {
        "name_similarity": round(name_score, 4),
        "address_exact": address_exact,
        "address_conflict": address_conflict,
        "same_district": same_district,
        "date_overlap_coverage": round(overlap, 4),
        "exact_dates": exact_dates,
        "same_end_date": same_end_date,
        "exact_core_name": exact_core_name,
        "core_containment": core_containment,
        "shared_distinctive_tags": shared_distinctive_tags,
        "shared_distinctive_tag_count": len(shared_distinctive_tags),
        "description_token_jaccard": round(description_token_jaccard, 4),
        "shared_description_token_count": shared_description_token_count,
        "official_url_exact": official_url_exact,
        "duplicate_score": score,
    }


def _is_candidate(features: dict[str, Any]) -> bool:
    name_score = features["name_similarity"]
    overlap = features["date_overlap_coverage"]
    shared_tags = int(features.get("shared_distinctive_tag_count") or 0)
    description_jaccard = float(features.get("description_token_jaccard") or 0.0)
    shared_description_tokens = int(features.get("shared_description_token_count") or 0)
    if overlap <= 0:
        return False
    if (
        features.get("official_url_exact")
        and features["address_exact"]
        and features["exact_dates"]
    ):
        return True
    if (
        features["address_exact"]
        and features["exact_dates"]
        and shared_tags >= 1
        and description_jaccard >= 0.18
        and shared_description_tokens >= 4
    ):
        return True
    if (
        features["address_exact"]
        and features["exact_dates"]
        and description_jaccard >= 0.35
        and shared_description_tokens >= 4
        and name_score >= 0.10
    ):
        return True
    if features["address_exact"] and name_score >= 0.25:
        return True
    if features["exact_dates"] and features["same_district"] and name_score >= 0.3:
        return True
    if name_score >= 0.65 and features["same_district"]:
        return True
    if name_score >= 0.9:
        return True
    return False


def _auto_duplicate(features: dict[str, Any]) -> bool:
    # Canonical rows are location-specific. If both sources provide concrete
    # but different street addresses, never merge them automatically merely
    # because the title/date/district match (multi-location campaigns are common).
    if features.get("address_conflict"):
        return False
    name_score = features["name_similarity"]
    overlap = features["date_overlap_coverage"]
    shared_tags = int(features.get("shared_distinctive_tag_count") or 0)
    description_jaccard = float(features.get("description_token_jaccard") or 0.0)
    shared_description_tokens = int(features.get("shared_description_token_count") or 0)
    if (
        features.get("official_url_exact")
        and features["address_exact"]
        and features["exact_dates"]
    ):
        return True
    if (
        features["address_exact"]
        and features["exact_dates"]
        and shared_tags >= 1
        and description_jaccard >= 0.18
        and shared_description_tokens >= 4
    ):
        return True
    if (
        features["address_exact"]
        and features["exact_dates"]
        and description_jaccard >= 0.35
        and shared_description_tokens >= 4
        and name_score >= 0.10
    ):
        return True
    if (
        features["address_exact"]
        and features["exact_dates"]
        and name_score >= 0.55
        and (
            features.get("exact_core_name")
            or features.get("core_containment")
            or shared_tags >= 1
        )
    ):
        return True
    if (
        features["address_exact"]
        and features["exact_dates"]
        and features["core_containment"]
        and name_score >= 0.3
    ):
        return True
    if (
        features["address_exact"]
        and overlap >= 0.8
        and features.get("same_end_date")
        and shared_tags >= 1
        and name_score >= 0.5
    ):
        return True
    if (
        features["address_exact"]
        and features["exact_dates"]
        and shared_tags >= 1
        and name_score >= 0.3
    ):
        return True
    if features["address_exact"] and name_score >= 0.72 and overlap >= 0.8:
        return True
    if (
        features["exact_core_name"]
        and overlap >= 0.8
        and (features["same_district"] or features["address_exact"])
    ):
        return True
    if (
        features["exact_dates"]
        and features["same_district"]
        and name_score >= 0.78
    ):
        return True
    return False


def _needs_duplicate_review(features: dict[str, Any]) -> bool:
    """Return only genuinely ambiguous identity pairs.

    Concrete but different street addresses are treated as different location
    instances. This prevents a multi-location campaign from creating a manual
    review queue every day.
    """
    if features.get("address_conflict"):
        return False
    name_score = features["name_similarity"]
    overlap = features["date_overlap_coverage"]
    if (
        features["address_exact"]
        and features["exact_dates"]
        and (
            name_score >= 0.55
            or features.get("core_containment")
            or int(features.get("shared_distinctive_tag_count") or 0) >= 1
        )
    ):
        return True
    if (
        features["address_exact"]
        and features["core_containment"]
        and name_score >= 0.43
        and overlap >= 0.8
    ):
        return True
    if features["exact_core_name"] and overlap >= 0.5:
        return True
    if name_score >= 0.75 and overlap >= 0.6 and features["same_district"]:
        return True
    return False


def generate_duplicate_candidates(
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []

    supported = [
        row for row in rows
        if row.get("source") in {"dayforyou", "popga", "popply"}
    ]
    prepared_names = {
        row["record_id"]: _prepared_name(row.get("name")) for row in supported
    }
    prepared_addresses = {
        row["record_id"]: compact_address(row.get("address_base") or row.get("address"))
        for row in supported
    }

    for left, right in combinations(supported, 2):
        same_source = left.get("source") == right.get("source")
        if not _date_overlap_possible(left, right):
            continue

        # Normally duplicate matching is cross-source. DayForYou can however
        # publish the exact same upstream event under two scheduleSeq values.
        # Allow only an extremely strict same-source merge so separate events
        # from the same mall can never collapse accidentally.
        if same_source:
            left_official = str(left.get("official_url") or "").strip()
            right_official = str(right.get("official_url") or "").strip()
            features = duplicate_features(left, right)
            strict_same_source = bool(
                (
                    features.get("official_url_exact")
                    and features["address_exact"]
                    and features["exact_dates"]
                )
                or (
                    # DayForYou sometimes republishes one event with an
                    # editorial prefix or a completely different post title.
                    # Exact place + exact dates + multiple distinctive brand
                    # tags is enough to merge this narrow same-source case.
                    features["address_exact"]
                    and features["exact_dates"]
                    and (
                        (
                            features["core_containment"]
                            and features["name_similarity"] >= 0.72
                        )
                        or (
                            int(features.get("shared_distinctive_tag_count") or 0) >= 2
                            and (
                                features["name_similarity"] >= 0.20
                                or (
                                    float(features.get("description_token_jaccard") or 0.0) >= 0.15
                                    and int(features.get("shared_description_token_count") or 0) >= 2
                                )
                            )
                        )
                        or (
                            float(features.get("description_token_jaccard") or 0.0) >= 0.35
                            and int(features.get("shared_description_token_count") or 0) >= 4
                            and features["name_similarity"] >= 0.10
                        )
                    )
                )
            )
            if not strict_same_source:
                continue
            candidates.append({
                "left_record_id": left["record_id"],
                "right_record_id": right["record_id"],
                "left_source": left["source"],
                "left_source_id": left["source_id"],
                "left_name": left.get("name"),
                "left_classification": left.get("classification"),
                "right_source": right["source"],
                "right_source_id": right["source_id"],
                "right_name": right.get("name"),
                "right_classification": right.get("classification"),
                "left_address": left.get("address_base") or left.get("address"),
                "right_address": right.get("address_base") or right.get("address"),
                "left_dates": [left.get("start_date"), left.get("end_date")],
                "right_dates": [right.get("start_date"), right.get("end_date")],
                **features,
                "decision": "AUTO_DUPLICATE",
                "same_source_exact_identity": True,
            })
            continue

        left_address = prepared_addresses[left["record_id"]]
        right_address = prepared_addresses[right["record_id"]]
        address_exact = bool(left_address and left_address == right_address)
        same_district = bool(
            left.get("district") and left.get("district") == right.get("district")
        )
        threshold = _candidate_name_threshold(
            left, right, address_exact=address_exact, same_district=same_district
        )
        exact_dates = (
            left.get("start_date") == right.get("start_date")
            and left.get("end_date") == right.get("end_date")
        )
        # Exact place + exact date pairs can be aliases with almost no title
        # similarity (REW vs 리더블유). Inspect their stronger URL/tag/body
        # identity before applying the cheap name-only upper-bound shortcut.
        if not (address_exact and exact_dates):
            if _name_similarity_upper_bound(
                prepared_names[left["record_id"]], prepared_names[right["record_id"]]
            ) < threshold:
                continue

        features = duplicate_features(left, right)
        if not _is_candidate(features):
            continue

        both_popup = (
            left.get("classification") == "POPUP"
            and right.get("classification") == "POPUP"
        )
        has_classification_conflict = (
            left.get("classification") != right.get("classification")
        )
        needs_review = _needs_duplicate_review(features)
        both_non_popup = (
            left.get("classification") == "NON_POPUP"
            and right.get("classification") == "NON_POPUP"
        )
        if both_popup and _auto_duplicate(features):
            decision = "AUTO_DUPLICATE"
        elif both_non_popup and needs_review:
            decision = "NON_POPUP_MATCH"
        elif has_classification_conflict and needs_review:
            decision = "REVIEW_CLASSIFICATION_CONFLICT"
        elif needs_review:
            decision = "REVIEW_DUPLICATE"
        else:
            decision = "REJECT_NOT_DUPLICATE"

        candidates.append({
            "left_record_id": left["record_id"],
            "right_record_id": right["record_id"],
            "left_source": left["source"],
            "left_source_id": left["source_id"],
            "left_name": left.get("name"),
            "left_classification": left.get("classification"),
            "right_source": right["source"],
            "right_source_id": right["source_id"],
            "right_name": right.get("name"),
            "right_classification": right.get("classification"),
            "left_address": left.get("address_base") or left.get("address"),
            "right_address": right.get("address_base") or right.get("address"),
            "left_dates": [left.get("start_date"), left.get("end_date")],
            "right_dates": [right.get("start_date"), right.get("end_date")],
            **features,
            "decision": decision,
        })

    candidates.sort(
        key=lambda item: (
            -float(item["duplicate_score"]),
            item["left_record_id"],
            item["right_record_id"],
        )
    )
    resolved = _resolve_multiple_auto_matches(candidates)
    conflict_checked = _reject_reviews_conflicting_with_auto_match(resolved)
    return reject_redundant_review_edges(conflict_checked)


def reject_redundant_review_edges(
    candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """이미 다른 AUTO edge 경로로 같은 cluster인 REVIEW edge는 검토에서 뺀다."""
    record_ids = {
        record_id
        for item in candidates
        for record_id in (item["left_record_id"], item["right_record_id"])
    }
    parent = {record_id: record_id for record_id in record_ids}

    def find(value: str) -> str:
        while parent[value] != value:
            parent[value] = parent[parent[value]]
            value = parent[value]
        return value

    def union(left: str, right: str) -> None:
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    for item in candidates:
        if item["decision"] == "AUTO_DUPLICATE":
            union(item["left_record_id"], item["right_record_id"])

    for item in candidates:
        if not item["decision"].startswith("REVIEW_"):
            continue
        if find(item["left_record_id"]) == find(item["right_record_id"]):
            item["decision"] = "REJECT_REDUNDANT_AUTO_CLUSTER"
    return candidates


def _resolve_multiple_auto_matches(
    candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """한 레코드가 서로 다른 여러 행사에 자동병합되는 것을 막는다."""
    by_record: dict[str, list[tuple[dict[str, Any], tuple[Any, ...], str]]] = {}
    auto_pairs = {
        frozenset((item["left_record_id"], item["right_record_id"]))
        for item in candidates if item["decision"] == "AUTO_DUPLICATE"
    }
    for item in candidates:
        if item["decision"] != "AUTO_DUPLICATE":
            continue
        left_other_signature = (
            core_name(item["right_name"]),
            compact_address(item["right_address"]),
            tuple(item["right_dates"]),
        )
        right_other_signature = (
            core_name(item["left_name"]),
            compact_address(item["left_address"]),
            tuple(item["left_dates"]),
        )
        by_record.setdefault(item["left_record_id"], []).append(
            (item, left_other_signature, item["right_record_id"])
        )
        by_record.setdefault(item["right_record_id"], []).append(
            (item, right_other_signature, item["left_record_id"])
        )

    demote: set[tuple[str, str]] = set()
    for edge_entries in by_record.values():
        if len(edge_entries) <= 1:
            continue
        other_signatures = {signature for _, signature, _ in edge_entries}
        cores = {signature[0] for signature in other_signatures}
        dates = {signature[2] for signature in other_signatures}
        known_addresses = {signature[1] for signature in other_signatures if signature[1]}
        # 상세 미수집 source의 주소만 비어 있어도 이름/날짜가 완전히 같으면
        # 같은 행사 signature로 본다. 주소가 서로 다른 경우에는 허용하지 않는다.
        if len(cores) == 1 and len(dates) == 1 and len(known_addresses) <= 1:
            continue
        # Strict same-source aliases are already proven to be one upstream
        # identity. Do not let an editorial re-post create a false "multiple
        # matches" conflict for otherwise coherent cross-source partners.
        non_alias_entries = [
            entry for entry in edge_entries
            if not entry[0].get("same_source_exact_identity")
        ]
        identity_alias_present = len(non_alias_entries) != len(edge_entries)
        ambiguity_entries = non_alias_entries if identity_alias_present else edge_entries
        other_ids = [other_id for _, _, other_id in ambiguity_entries]
        if identity_alias_present and len(other_ids) <= 1:
            continue

        # 여러 출처가 같은 행사를 서로 다른 제목으로 올리면 한 레코드를
        # 중심으로 별 모양 AUTO_DUPLICATE 묶음이 생길 수 있다.
        # 모든 연결이 정확히 같은 장소/기간을 가리키고, 각 연결마다
        # 추가적인 행사 정체성 근거가 있을 때만 하나의 묶음으로 인정한다.
        ambiguity_signatures = {
            signature for _, signature, _ in ambiguity_entries
        }
        ambiguity_dates = {
            signature[2] for signature in ambiguity_signatures
        }
        ambiguity_addresses = {
            signature[1]
            for signature in ambiguity_signatures
            if signature[1]
        }

        coherent_exact_place_dates = bool(
            len(ambiguity_entries) >= 2
            and len(ambiguity_dates) == 1
            and len(ambiguity_addresses) == 1
            and all(
                edge.get("address_exact")
                and edge.get("exact_dates")
                and (
                    edge.get("official_url_exact")
                    or edge.get("exact_core_name")
                    or edge.get("core_containment")
                    or int(
                        edge.get("shared_distinctive_tag_count") or 0
                    ) >= 1
                    or float(
                        edge.get("name_similarity") or 0.0
                    ) >= 0.72
                    or (
                        float(
                            edge.get("description_token_jaccard") or 0.0
                        ) >= 0.35
                        and int(
                            edge.get("shared_description_token_count") or 0
                        ) >= 4
                    )
                )
                for edge, _, _ in ambiguity_entries
            )
        )
        if coherent_exact_place_dates:
            continue

        # Editorial aliases can create a 4+ record cluster where every partner
        # is not a complete triangle (for example one DayForYou re-post plus
        # Popga/Popply). If the remaining partners are still connected through
        # strong AUTO edges, they are one coherent identity component and must
        # not be demoted to REVIEW_MULTIPLE_MATCHES.
        partner_set = set(other_ids)
        adjacency = {record_id: set() for record_id in partner_set}
        for pair in auto_pairs:
            pair_ids = list(pair)
            if len(pair_ids) != 2:
                continue
            a, b = pair_ids
            if a in partner_set and b in partner_set:
                adjacency[a].add(b)
                adjacency[b].add(a)
        if partner_set:
            start = next(iter(partner_set))
            seen = {start}
            stack = [start]
            while stack:
                current = stack.pop()
                for nxt in adjacency.get(current, set()):
                    if nxt not in seen:
                        seen.add(nxt)
                        stack.append(nxt)
            partners_are_connected = seen == partner_set
        else:
            partners_are_connected = False
        if partners_are_connected:
            continue
        if len(other_signatures) == 1:
            continue
        ranked = sorted(
            (edge for edge, _, _ in edge_entries),
            key=lambda item: item["duplicate_score"],
            reverse=True,
        )
        if ranked[0]["duplicate_score"] - ranked[1]["duplicate_score"] >= 8:
            for edge in ranked[1:]:
                demote.add((edge["left_record_id"], edge["right_record_id"]))
        else:
            for edge in ranked:
                demote.add((edge["left_record_id"], edge["right_record_id"]))

    for item in candidates:
        key = (item["left_record_id"], item["right_record_id"])
        if key in demote and item["decision"] == "AUTO_DUPLICATE":
            item["decision"] = "REVIEW_MULTIPLE_MATCHES"
    return candidates


def _record_signature(
    name: object,
    address: object,
    dates: list[object] | tuple[object, ...],
) -> tuple[Any, ...]:
    return (
        core_name(name),
        compact_address(address),
        tuple(dates),
    )


def _reject_reviews_conflicting_with_auto_match(
    candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """이미 강하게 매칭된 레코드의 서로 다른 지점/기간 후보를 제거한다."""
    auto_partner_signatures: dict[str, set[tuple[Any, ...]]] = {}
    for item in candidates:
        if item["decision"] != "AUTO_DUPLICATE":
            continue
        auto_partner_signatures.setdefault(item["left_record_id"], set()).add(
            _record_signature(
                item["right_name"], item["right_address"], item["right_dates"]
            )
        )
        auto_partner_signatures.setdefault(item["right_record_id"], set()).add(
            _record_signature(
                item["left_name"], item["left_address"], item["left_dates"]
            )
        )

    for item in candidates:
        if not item["decision"].startswith("REVIEW_"):
            continue
        right_signature = _record_signature(
            item["right_name"], item["right_address"], item["right_dates"]
        )
        left_signature = _record_signature(
            item["left_name"], item["left_address"], item["left_dates"]
        )
        left_partners = auto_partner_signatures.get(item["left_record_id"])
        right_partners = auto_partner_signatures.get(item["right_record_id"])
        if (
            (left_partners and right_signature not in left_partners)
            or (right_partners and left_signature not in right_partners)
        ):
            item["decision"] = "REJECT_CONFLICTS_WITH_AUTO_MATCH"
    return candidates
