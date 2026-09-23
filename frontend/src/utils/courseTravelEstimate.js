function hasCoordinates(location) {
  return (
    location != null &&
    Number.isFinite(Number(location.latitude)) &&
    Number.isFinite(Number(location.longitude))
  );
}

export function buildCourseSegments(startLocation, places, endLocation) {
  const stops = [startLocation, ...(places ?? [])];
  if (endLocation) stops.push(endLocation);

  const segments = [];
  for (let index = 0; index < stops.length - 1; index += 1) {
    const from = stops[index];
    const to = stops[index + 1];
    if (!hasCoordinates(from) || !hasCoordinates(to)) return null;
    segments.push({ from, to });
  }
  return segments;
}

export function routeDurationMinutes(route) {
  const value = Number(route?.duration_min ?? route?.duration_minutes);
  return Number.isFinite(value) && value >= 0 ? Math.round(value) : null;
}

export function courseSegmentCacheKey(segment, transportMode) {
  const coordinate = (value) => Number(value).toFixed(5);
  return [
    transportMode,
    coordinate(segment.from.latitude),
    coordinate(segment.from.longitude),
    coordinate(segment.to.latitude),
    coordinate(segment.to.longitude),
  ].join(":");
}

function distanceKilometers(from, to) {
  if (!hasCoordinates(from) || !hasCoordinates(to)) return null;
  const radians = (value) => (Number(value) * Math.PI) / 180;
  const latitudeDelta = radians(to.latitude) - radians(from.latitude);
  const longitudeDelta = radians(to.longitude) - radians(from.longitude);
  const fromLatitude = radians(from.latitude);
  const toLatitude = radians(to.latitude);
  const haversine =
    Math.sin(latitudeDelta / 2) ** 2 +
    Math.cos(fromLatitude) *
      Math.cos(toLatitude) *
      Math.sin(longitudeDelta / 2) ** 2;
  return 6371 * 2 * Math.atan2(Math.sqrt(haversine), Math.sqrt(1 - haversine));
}

// 외부 경로 조회가 실패한 후보 화면에서만 사용하는 보수적 예상값이다.
// 실제 경로와 구분할 수 있도록 status/source를 반드시 함께 반환한다.
export function estimateFallbackRoute(segment, transportMode) {
  const distanceKm = distanceKilometers(segment?.from, segment?.to);
  if (distanceKm == null) return null;
  if (distanceKm <= 0.01) {
    return {
      durationMinutes: 0,
      route: { mode: "walk", duration_min: 0, calculation_status: "estimated" },
      status: "estimated",
      source: "same_point_fallback",
    };
  }

  let durationMinutes;
  let mode = transportMode;
  if (transportMode === "walk" || distanceKm <= 3) {
    // 짧은 대중교통 경로가 없으면 도보 가능성을 기준으로 넉넉하게 잡는다.
    mode = "walk";
    durationMinutes = Math.ceil((distanceKm * 1.3 * 60) / 4) + 3;
  } else if (transportMode === "car") {
    durationMinutes = Math.ceil((distanceKm * 1.25 * 60) / 25) + 5;
  } else {
    // 장거리 대중교통은 후보 미리보기만 유지하기 위한 낮은 신뢰도 추정이다.
    mode = "transit";
    durationMinutes = Math.ceil((distanceKm * 1.35 * 60) / 18) + 8;
  }

  return {
    durationMinutes: Math.max(1, durationMinutes),
    route: {
      mode,
      distance_km: Number(distanceKm.toFixed(2)),
      duration_min: Math.max(1, durationMinutes),
      calculation_status: "estimated",
    },
    status: "estimated",
    source: "distance_fallback",
  };
}
