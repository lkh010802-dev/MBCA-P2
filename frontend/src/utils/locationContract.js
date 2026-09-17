export function distanceMetersBetweenLocations(left, right) {
  const leftLatitude = Number(left?.latitude)
  const leftLongitude = Number(left?.longitude)
  const rightLatitude = Number(right?.latitude)
  const rightLongitude = Number(right?.longitude)
  if (![leftLatitude, leftLongitude, rightLatitude, rightLongitude].every(Number.isFinite)) return null
  const toRadians = (value) => value * Math.PI / 180
  const latitudeDelta = toRadians(rightLatitude - leftLatitude)
  const longitudeDelta = toRadians(rightLongitude - leftLongitude)
  const a = Math.sin(latitudeDelta / 2) ** 2
    + Math.cos(toRadians(leftLatitude)) * Math.cos(toRadians(rightLatitude)) * Math.sin(longitudeDelta / 2) ** 2
  return 6371000 * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a))
}

// 자동 추천은 항상 "현재 위치"에서 시작한다. 이 계약이 깨지면 엉뚱한 지역을
// 표시하는 대신 서버 재시작/재시도를 안내한다.
export function hasAutoCourseStartLocationMismatch(requestLocation, responseStartLocation, maximumMeters = 1000) {
  const distance = distanceMetersBetweenLocations(requestLocation, responseStartLocation)
  return distance !== null && distance > maximumMeters
}
