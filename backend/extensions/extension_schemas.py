"""Request schemas owned by the local extension layer."""

from typing import Literal

from pydantic import BaseModel, Field


class PlacePhotoItem(BaseModel):
    client_key: str
    name: str
    address: str | None = None
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    category: Literal[
        "food",
        "cafe",
        "walk",
        "culture",
        "entertainment",
        "shopping",
        "drink",
    ]


class PlacePhotoBatchRequest(BaseModel):
    places: list[PlacePhotoItem] = Field(max_length=6)
