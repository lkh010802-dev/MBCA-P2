export function readSession(key, fallback) {
  try {
    const entry = JSON.parse(sessionStorage.getItem(key))
    return entry?.expires > Date.now() ? entry.value : fallback
  } catch { return fallback }
}

export function writeSession(key, value) {
  try {
    sessionStorage.setItem(key, JSON.stringify({ value, expires: Date.now() + 15 * 60 * 1000 }))
  } catch { /* Storage may be disabled or full; in-memory UI still works. */ }
}
