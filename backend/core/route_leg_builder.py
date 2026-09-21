def build_travel_legs(
    start_location: dict,
    selected_places: list[dict],
    end_location: dict | None = None,
) -> list[dict]:
    # 방문 순서가 정해진 뒤에만 출발지→장소들→선택적 종료지의 directed leg를 만든다.
    locations = [start_location, *selected_places]
    if end_location is not None:
        locations.append(end_location)

    # A→B와 B→A는 이동시간이 다를 수 있어 방향을 보존한다.
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
