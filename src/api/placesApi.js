const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://127.0.0.1:8000'

const responses = new Map()
const pending = new Map()

function postJson(path, payload, { fresh = false } = {}) {
  const key = JSON.stringify([path, payload])
  const cached = fresh ? null : responses.get(key)
  if (cached?.expires > Date.now()) return Promise.resolve(cached.data)
  if (pending.has(key)) return pending.get(key)
  const request = sendJson(path, payload).then((data) => {
    if (responses.size >= 50) responses.delete(responses.keys().next().value)
    responses.set(key, { data, expires: Date.now() + 60000 })
    return data
  }).finally(() => pending.delete(key))
  pending.set(key, request)
  return request
}

async function sendJson(path, payload) {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  const data = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(data.detail ?? data.message ?? '장소 정보를 불러오지 못했어요.')
  return data
}

export function requestPlaces({ areaName, latitude, longitude, activities = [] }) {
  return postJson('/recommend/places', {
    area_name: areaName,
    latitude,
    longitude,
    activities,
    companions: [],
    budget_max: null,
    budget_preference: null,
    space_preference: null,
  })
}

export function requestMorePlaces({ cursor, offset }) {
  return postJson('/recommend/places/more', { cursor, offset })
}

export function validatePlaceSelection({ startLatitude, startLongitude, selectedPlaces, availableTimeMinutes }) {
  return postJson('/recommend/places/validate-selection', {
    start_latitude: startLatitude,
    start_longitude: startLongitude,
    selected_places: selectedPlaces.map((place) => ({
      category: place.category,
      latitude: place.latitude,
      longitude: place.longitude,
      specified_duration_minutes: place.specifiedDurationMinutes ?? null,
    })),
    available_time_minutes: availableTimeMinutes,
  })
}

export function requestCourse({ startLocation, selectedPlaces, availableTimeMinutes, endLocation, transportMode = 'auto', fresh = false }) {
  return postJson('/recommend/course', {
    start_location: startLocation,
    selected_places: selectedPlaces.map((place) => ({
      category: place.category,
      latitude: place.latitude,
      longitude: place.longitude,
      specified_duration_minutes: place.specifiedDurationMinutes ?? null,
    })),
    available_time_minutes: availableTimeMinutes,
    end_location: endLocation ?? null,
    transport_mode: transportMode,
  }, { fresh })
}

export async function requestRoutePreview({ startLatitude, startLongitude, endLatitude, endLongitude, transportMode = 'auto' }) {
  const parameters = new URLSearchParams({
    start_latitude: startLatitude,
    start_longitude: startLongitude,
    end_latitude: endLatitude,
    end_longitude: endLongitude,
    transport_mode: transportMode,
  })
  const response = await fetch(`${API_BASE_URL}/route-preview?${parameters}`)
  const data = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(data.detail ?? '도보 경로를 불러오지 못했어요.')
  return data
}
