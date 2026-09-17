const placeTemplates = [
  ['블루보틀 라운지', '카페', 45, '4.6'],
  ['오늘의 식탁', '식당', 60, '4.5'],
  ['빛의 전시관', '전시·문화', 75, '4.7'],
  ['골목 산책길', '산책', 40, '4.4'],
  ['오후의 서점', '문화', 45, '4.5'],
  ['마켓 키친', '식당', 60, '4.3'],
]

export function getMockPlaces(area) {
  const latitude = area?.latitude ?? 37.5563
  const longitude = area?.longitude ?? 126.9236
  return placeTemplates.map(([name, category, stayMinutes, rating], index) => ({
    id: `${area?.name ?? 'area'}-${index}`,
    name,
    category,
    stayMinutes,
    rating,
    latitude: latitude + (index - 2.5) * 0.0011,
    longitude: longitude + ((index % 3) - 1) * 0.0014,
  }))
}
