const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://127.0.0.1:8000'

async function postJson(path, payload) {
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

export function requestCourse({ startLocation, selectedPlaces, availableTimeMinutes, endLocation, transportMode = 'auto' }) {
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
  })
}

export async function requestRoutePreview({ startLatitude, startLongitude, endLatitude, endLongitude }) {
  const parameters = new URLSearchParams({
    start_latitude: startLatitude,
    start_longitude: startLongitude,
    end_latitude: endLatitude,
    end_longitude: endLongitude,
    transport_mode: 'auto',
  })
  const response = await fetch(`${API_BASE_URL}/route-preview?${parameters}`)
  const data = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(data.detail ?? '도보 경로를 불러오지 못했어요.')
  return data
}
