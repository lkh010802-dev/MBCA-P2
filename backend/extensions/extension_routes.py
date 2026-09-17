"""Thin HTTP endpoints supplied by the local extension layer."""

from fastapi import APIRouter, HTTPException, Response

from extension_schemas import PlacePhotoBatchRequest
from map_service import get_visual_travel, reverse_geocode
from naver_image_service import get_cached_image, lookup_place_photos
from user_data_routes import router as user_data_router


router = APIRouter()
router.include_router(user_data_router)


@router.get("/reverse-geocode")
def reverse_geocode_api(latitude: float, longitude: float):
    result = reverse_geocode(latitude, longitude)
    return result or {
        "display_name": None,
        "road_address": None,
        "jibun_address": None,
    }


@router.get("/route-preview")
def route_preview_api(
    start_latitude: float,
    start_longitude: float,
    end_latitude: float,
    end_longitude: float,
    transport_mode: str = "auto",
):
    result = get_visual_travel(
        start_longitude,
        start_latitude,
        end_longitude,
        end_latitude,
        transport_mode=transport_mode,
    )
    if not result:
        raise HTTPException(status_code=502, detail="이동 경로를 계산하지 못했어요.")
    return result


@router.post("/place-media/photos")
def place_photos_api(payload: PlacePhotoBatchRequest):
    return lookup_place_photos(
        [item.model_dump() for item in payload.places],
    )


@router.get("/place-media/image/{cache_key}")
def place_image_api(cache_key: str):
    result = get_cached_image(cache_key)
    if not result:
        raise HTTPException(status_code=404, detail="장소 이미지가 없거나 만료되었어요.")
    content, content_type = result
    return Response(content=content, media_type=content_type, headers={"Cache-Control": "public, max-age=86400"})
