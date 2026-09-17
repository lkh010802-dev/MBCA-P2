from fastapi import APIRouter, HTTPException

from adventure_service import (
    create_blind_two_place_gacha,
    create_blind_single_place_gacha,
    NoAdventureCandidateError,
    recommend_random_quest,
    recommend_seoul_gacha,
    recommend_single_place_gacha,
    recommend_two_place_gacha,
    reveal_blind_two_place_gacha,
    reveal_blind_single_place_gacha,
)
from blind_adventure_cache import BlindAdventureTokenError
from models import (
    AdventureCourseResponse,
    AdventureRequest,
    AdventureResponse,
    BlindAdventureResponse,
    BlindAdventureCourseResponse,
    BlindAdventureRevealRequest,
    RandomQuestRequest,
    RandomQuestResponse,
    SeoulGachaRequest,
    SeoulGachaResponse,
)


router = APIRouter()


@router.post(
    "/recommend/adventure/quest",
    response_model=RandomQuestResponse,
)
def recommend_adventure_quest(request: RandomQuestRequest):
    return recommend_random_quest(request.activity)


@router.post(
    "/recommend/adventure/seoul",
    response_model=SeoulGachaResponse,
)
def recommend_seoul_adventure(request: SeoulGachaRequest):
    try:
        return recommend_seoul_gacha(request)
    except NoAdventureCandidateError as error:
        raise HTTPException(
            status_code=404,
            detail="현재 조건에서 선택 가능한 서울 추천 지역이 없습니다.",
        ) from error


@router.post("/recommend/adventure", response_model=AdventureResponse)
def recommend_adventure(request: AdventureRequest):
    try:
        return recommend_single_place_gacha(request)
    except NoAdventureCandidateError as error:
        raise HTTPException(
            status_code=404,
            detail="현재 조건에서 방문 가능한 가챠 후보가 없습니다.",
        ) from error


@router.post(
    "/recommend/adventure/course",
    response_model=AdventureCourseResponse,
)
def recommend_adventure_course(request: AdventureRequest):
    try:
        return recommend_two_place_gacha(request)
    except NoAdventureCandidateError as error:
        raise HTTPException(
            status_code=404,
            detail="현재 조건에서 방문 가능한 2장소 가챠 코스가 없습니다.",
        ) from error


@router.post(
    "/recommend/adventure/blind",
    response_model=BlindAdventureResponse,
)
def recommend_blind_adventure(request: AdventureRequest):
    try:
        return create_blind_single_place_gacha(request)
    except NoAdventureCandidateError as error:
        raise HTTPException(
            status_code=404,
            detail="현재 조건에서 방문 가능한 가챠 후보가 없습니다.",
        ) from error


@router.post(
    "/recommend/adventure/blind/reveal",
    response_model=AdventureResponse,
)
def reveal_blind_adventure(request: BlindAdventureRevealRequest):
    try:
        return reveal_blind_single_place_gacha(request.token)
    except BlindAdventureTokenError as error:
        raise HTTPException(
            status_code=404,
            detail="유효하지 않거나 만료된 가챠 토큰입니다.",
        ) from error


@router.post(
    "/recommend/adventure/blind/course",
    response_model=BlindAdventureCourseResponse,
)
def recommend_blind_adventure_course(request: AdventureRequest):
    try:
        return create_blind_two_place_gacha(request)
    except NoAdventureCandidateError as error:
        raise HTTPException(
            status_code=404,
            detail="현재 조건에서 방문 가능한 2장소 가챠 코스가 없습니다.",
        ) from error


@router.post(
    "/recommend/adventure/blind/course/reveal",
    response_model=AdventureCourseResponse,
)
def reveal_blind_adventure_course(request: BlindAdventureRevealRequest):
    try:
        return reveal_blind_two_place_gacha(request.token)
    except BlindAdventureTokenError as error:
        raise HTTPException(
            status_code=404,
            detail="유효하지 않거나 만료된 가챠 토큰입니다.",
        ) from error
