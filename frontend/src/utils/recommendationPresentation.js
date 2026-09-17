export function placeSourceKind(source) {
  const value = String(source ?? "").toLowerCase();
  if (value.includes("popup")) return "popup";
  if (
    value.includes("culture") ||
    value.includes("festival") ||
    value.includes("event")
  )
    return "culture";
  return "general";
}

function parseEventDate(value) {
  if (!value) return null;
  const dateOnly = String(value).match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (dateOnly) {
    const [, year, month, day] = dateOnly;
    return new Date(Number(year), Number(month) - 1, Number(day));
  }
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

export function formatEventPeriod(startValue, endValue) {
  const start = parseEventDate(startValue);
  const end = parseEventDate(endValue);
  if (!start && !end) return null;
  const short = (date) => `${date.getMonth() + 1}.${date.getDate()}`;
  if (start && end)
    return start.toDateString() === end.toDateString()
      ? `${short(start)} 당일`
      : `${short(start)}–${short(end)}`;
  return start ? `${short(start)} 시작` : `${short(end)}까지`;
}

export function eventUrgency(endValue) {
  const end = parseEventDate(endValue);
  if (!end) return null;
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  end.setHours(0, 0, 0, 0);
  const days = Math.round((end.getTime() - today.getTime()) / 86400000);
  if (days < 0) return "종료";
  if (days === 0) return "오늘 종료";
  if (days <= 7) return `D-${days}`;
  return null;
}

export function recommendationReason(place) {
  if (place.eventUrgency === "오늘 종료")
    return "오늘이 마지막 날이라 지금 추천해요";
  if (place.eventUrgency?.startsWith("D-"))
    return `${place.eventUrgency} · 끝나기 전에 가볼 만해요`;
  if (place.sourceKind === "popup") return "지금 운영 중인 팝업이에요";
  if (place.sourceKind === "culture") return "현재 관람할 수 있는 문화행사예요";
  if (place.distanceMeters > 0 && place.distanceMeters <= 500)
    return "현재 위치에서 가까워 이동 부담이 적어요";
  return `${place.categoryLabel} 활동 조건과 잘 맞아요`;
}

