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
