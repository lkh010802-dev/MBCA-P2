import { useCallback, useEffect, useRef, useState } from 'react'
import { API_BASE_URL } from '../api/apiConfig'

export function useCurrentLocation() {
  const [location, setLocation] = useState(null)
  const [address, setAddress] = useState(null)
  const [addressStatus, setAddressStatus] = useState('idle')
  const [status, setStatus] = useState('idle')
  const watchIdRef = useRef(null)

  const stopWatching = useCallback(() => {
    if (watchIdRef.current !== null && navigator.geolocation) {
      navigator.geolocation.clearWatch(watchIdRef.current)
      watchIdRef.current = null
    }
  }, [])

  useEffect(() => stopWatching, [stopWatching])

  const clearLocation = useCallback(() => {
    stopWatching()
    setLocation(null)
    setAddress(null)
    setAddressStatus('idle')
    setStatus('idle')
  }, [stopWatching])

  const requestLocation = useCallback((onSuccess, onFailure) => {
    if (!navigator.geolocation) {
      setStatus('unsupported')
      if (typeof onFailure === 'function') onFailure()
      return
    }

    stopWatching()
    setStatus('loading')
    let settled = false
    watchIdRef.current = navigator.geolocation.watchPosition(
      ({ coords }) => {
        if (settled) return
        settled = true
        const nextLocation = {
          latitude: coords.latitude,
          longitude: coords.longitude,
          accuracy: coords.accuracy,
          updatedAt: Date.now(),
        }
        setLocation(nextLocation)
        setAddress(null)
        setAddressStatus('loading')
        setStatus('success')
        stopWatching()
        if (typeof onSuccess === 'function') onSuccess(nextLocation)

        // Address lookup is optional. The aligned mvp-v2 backend does not expose
        // /reverse-geocode, so never block or error the location flow on it.
        // It can be enabled explicitly when a backend providing the endpoint is used.
        const addressController = new AbortController()
        const addressTimeout = window.setTimeout(() => addressController.abort(), 8000)
        fetch(`${API_BASE_URL}/reverse-geocode?latitude=${encodeURIComponent(coords.latitude)}&longitude=${encodeURIComponent(coords.longitude)}`, { signal: addressController.signal })
          .then((response) => {
            if (!response.ok) throw new Error('주소 조회 실패')
            return response.json()
          })
          .then((result) => {
            setAddress(result)
            setAddressStatus(result?.road_address || result?.jibun_address || result?.display_name ? 'success' : 'unavailable')
          })
          .catch(() => setAddressStatus('unavailable'))
          .finally(() => window.clearTimeout(addressTimeout))
      },
      (error) => {
        if (settled) return
        settled = true
        setStatus(error.code === error.PERMISSION_DENIED ? 'denied' : 'unavailable')
        stopWatching()
        if (typeof onFailure === 'function') onFailure(error)
      },
      { enableHighAccuracy: true, timeout: 20000, maximumAge: 15000 },
    )
  }, [stopWatching])

  return { location, address, addressStatus, status, requestLocation, clearLocation }
}
