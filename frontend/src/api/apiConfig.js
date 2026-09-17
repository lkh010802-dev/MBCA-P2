// Use the same-origin /api proxy when no explicit backend URL is configured.
// This keeps production browsers from accidentally calling their own localhost.
const configuredBaseUrl = import.meta.env?.VITE_API_BASE_URL?.trim()

export const API_BASE_URL = (configuredBaseUrl || '/api').replace(/\/$/, '')

export function apiAssetUrl(path) {
  if (!path || /^https?:\/\//i.test(path) || path.startsWith('data:')) return path
  return `${API_BASE_URL}${path.startsWith('/') ? path : `/${path}`}`
}
