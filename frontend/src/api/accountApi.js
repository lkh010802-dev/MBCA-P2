import { API_BASE_URL } from './apiConfig'
// Real API/DB authentication is the safe default in every environment.
// Opt into localStorage-only demo auth explicitly with VITE_AUTH_MODE=mock.
const MOCK_AUTH = import.meta.env.VITE_AUTH_MODE === 'mock'
const MOCK_TOKEN = 'koala-local-demo-token'
const USER_KEY = 'koala-mock-user'
const PREF_KEY = 'koala-mock-preferences'
const COURSE_KEY = 'koala-mock-courses'
const EXCLUDED_PLACE_KEY = 'koala-mock-excluded-places'
const defaultPreferences = { transport_mode: 'public_transit', space_preference: 'any', activity_preferences: {} }

function read(key, fallback) { try { return JSON.parse(localStorage.getItem(key)) ?? fallback } catch { return fallback } }
function write(key, value) { localStorage.setItem(key, JSON.stringify(value)); return value }
function mockUser(input = {}) { return read(USER_KEY, null) ?? write(USER_KEY, { id: 1, email: input.email ?? 'demo@koala.local', nickname: input.nickname ?? '코알라 여행자', created_at: new Date().toISOString() }) }
function assertMockToken(token) { if (token !== MOCK_TOKEN) throw new Error('로그인이 필요해요.') }

async function api(path, { method = 'GET', token, body } = {}) {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    method,
    headers: {
      ...(body ? { 'Content-Type': 'application/json' } : {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  })
  const data = response.status === 204 ? null : await response.json().catch(() => ({}))
  if (!response.ok) {
    const detail = typeof data?.detail === 'string' ? data.detail : ''
    const message = detail === 'Not Found'
      ? '회원가입 서버 주소를 찾지 못했어요. 잠시 후 다시 시도해 주세요.'
      : (detail || '계정 정보를 처리하지 못했어요.')
    throw new Error(message)
  }
  return data
}

function normalizePreferences(data) {
  const activities = Array.isArray(data?.activity_preferences)
    ? Object.fromEntries(data.activity_preferences.map((item) => [item.activity, item.preference_level]))
    : (data?.activity_preferences ?? {})
  return { transport_mode: data?.transport_mode ?? null, space_preference: data?.space_preference ?? null, activity_preferences: activities }
}

export async function signup(body) {
  if (!MOCK_AUTH) return api('/auth/signup', { method: 'POST', body })
  write(USER_KEY, { id: 1, email: String(body.email).trim().toLowerCase(), nickname: body.nickname, created_at: new Date().toISOString() })
  if (!localStorage.getItem(PREF_KEY)) write(PREF_KEY, defaultPreferences)
  return mockUser(body)
}
export async function login(body) { if (!MOCK_AUTH) return api('/auth/login', { method: 'POST', body }); mockUser(body); return { access_token: MOCK_TOKEN, token_type: 'bearer', mock: true } }
export async function getMe(token) { if (!MOCK_AUTH) return api('/users/me', { token }); assertMockToken(token); return mockUser() }
export async function getPreferences(token) {
  if (MOCK_AUTH) { assertMockToken(token); return read(PREF_KEY, defaultPreferences) }
  try { return normalizePreferences(await api('/ml/users/me/preferences', { token })) }
  catch { return normalizePreferences(await api('/users/me/preferences', { token })) }
}
export async function updatePreferences(token, body) {
  if (MOCK_AUTH) { assertMockToken(token); return write(PREF_KEY, normalizePreferences(body)) }
  const mlBody = { transport_mode: body.transport_mode, space_preference: body.space_preference, activity_preferences: Object.entries(body.activity_preferences ?? {}).map(([activity, preference_level]) => ({ activity, preference_level })) }
  try { return normalizePreferences(await api('/ml/users/me/preferences', { method: 'PUT', token, body: mlBody })) }
  catch { return normalizePreferences(await api('/users/me/preferences', { method: 'PUT', token, body: mlBody })) }
}
export async function saveCourse(token, body) {
  if (!MOCK_AUTH) return api('/users/me/courses', { method: 'POST', token, body })
  assertMockToken(token)
  const saved = { ...body, id: Date.now(), created_at: new Date().toISOString() }
  write(COURSE_KEY, [saved, ...read(COURSE_KEY, [])].slice(0, 30))
  return saved
}
export async function getSavedCourses(token) { if (!MOCK_AUTH) return api('/users/me/courses', { token }); assertMockToken(token); return read(COURSE_KEY, []) }
export async function deleteSavedCourse(token, courseId) {
  if (!MOCK_AUTH) return api(`/users/me/courses/${courseId}`, { method: 'DELETE', token })
  assertMockToken(token); write(COURSE_KEY, read(COURSE_KEY, []).filter((course) => String(course.id) !== String(courseId))); return null
}
export const isMockAuthEnabled = () => MOCK_AUTH

export async function getExcludedPlaces(token) {
  if (!MOCK_AUTH) return api('/users/me/excluded-places', { token })
  assertMockToken(token); return read(EXCLUDED_PLACE_KEY, [])
}

export async function excludePlace(token, body) {
  if (!MOCK_AUTH) return api('/users/me/excluded-places', { method: 'POST', token, body })
  assertMockToken(token)
  const current = read(EXCLUDED_PLACE_KEY, [])
  const existing = current.find((item) => item.place_key === body.place_key)
  if (existing) return existing
  const item = { ...body, id: Date.now(), user_id: 1, created_at: new Date().toISOString() }
  write(EXCLUDED_PLACE_KEY, [item, ...current].slice(0, 200))
  return item
}
