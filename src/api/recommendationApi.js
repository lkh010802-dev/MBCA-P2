const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://127.0.0.1:8000'

export async function requestRecommendation({ message, location }) {
  const response = await fetch(`${API_BASE_URL}/recommend`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      user_message: message,
      gps_latitude: location?.latitude ?? null,
      gps_longitude: location?.longitude ?? null,
    }),
  })

  const data = await response.json().catch(() => ({}))
  if (!response.ok || data.error) throw new Error(data.message ?? '추천 정보를 불러오지 못했어요.')
  return data
}
