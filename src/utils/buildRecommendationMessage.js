const activityLabels = { cafe: '카페', culture: '전시·문화', walk: '산책', food: '맛집', shopping: '쇼핑', drink: '술집' }
const transportLabels = { auto: '이동수단은 상관없고', transit: '대중교통을 이용하고', walk: '도보 이동 위주로' }
const spaceLabels = { indoor: '실내 위주로', outdoor: '야외 위주로' }

export function buildRecommendationMessage(message, conditions) {
  const details = []
  if (conditions.activities.length) details.push(`${conditions.activities.map((item) => activityLabels[item]).join(', ')}을(를) 원해.`)
  if (conditions.transport) details.push(`${transportLabels[conditions.transport]} 추천해줘.`)
  if (conditions.space) details.push(`${spaceLabels[conditions.space]} 부탁해.`)
  return [message.trim(), ...details].filter(Boolean).join(' ')
}
