def build_travel_legs(
    start_location: dict,
    selected_places: list[dict],
    end_location: dict | None = None,
) -> list[dict]:
    locations = [start_location, *selected_places]
    if end_location is not None:
        locations.append(end_location)

    return [
        {
            "origin": {
                "latitude": origin["latitude"],
                "longitude": origin["longitude"],
            },
            "destination": {
                "latitude": destination["latitude"],
                "longitude": destination["longitude"],
            },
        }
        for origin, destination in zip(locations, locations[1:])
    ]
