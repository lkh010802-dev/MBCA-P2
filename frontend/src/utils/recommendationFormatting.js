/** Presentation-only formatting shared by recommendation components. */
export function formatDistance(distanceMeters) {
  if (!distanceMeters) return "거리 정보 없음";
  return distanceMeters >= 1000
    ? `${(distanceMeters / 1000).toFixed(1)}km`
    : `${distanceMeters}m`;
}

export function formatMinutes(minutes) {
  if (minutes == null || Number.isNaN(Number(minutes))) return "시간 확인 중";
  const value = Math.max(0, Math.round(Number(minutes)));
  if (value < 60) return `${value}분`;
  const hours = Math.floor(value / 60);
  const rest = value % 60;
  return rest ? `${hours}시간 ${rest}분` : `${hours}시간`;
}

export function formatCalculatedMinutes(minutes) {
  return Number.isFinite(Number(minutes)) ? `${Number(minutes)}분` : "계산 불가";
}

export function formatClock(value) {
  if (!value) return null;
  return new Intl.DateTimeFormat("ko-KR", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(new Date(value));
}

export function availabilityLabel(availability) {
  if (!availability) return null;
  const arrival = availability.arrival_at
    ? formatClock(availability.arrival_at)
    : null;
  const labels = {
    open: `영업 중${arrival ? ` · ${arrival} 도착` : ""}`,
    closed: "도착 시 영업 종료",
    not_yet_open: "도착 시 영업 전",
    event_not_started: "행사 시작 전",
    event_ended: "행사 종료",
    unknown: arrival ? `${arrival} 도착 예정` : "운영시간 확인 필요",
  };
  return labels[availability.status] ?? null;
}
