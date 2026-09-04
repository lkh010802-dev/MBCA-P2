import { useCallback, useState } from 'react'

export function useCurrentLocation() {
  const [location, setLocation] = useState(null)
  const [address, setAddress] = useState(null)
  const [status, setStatus] = useState('idle')

  const requestLocation = useCallback(() => {
    if (!navigator.geolocation) {
      setStatus('unsupported')
      return
    }

    setStatus('loading')
    navigator.geolocation.getCurrentPosition(
      ({ coords }) => {
        const nextLocation = { latitude: coords.latitude, longitude: coords.longitude }
        setLocation(nextLocation)
        setAddress(null)
        setStatus('success')

        const apiBaseUrl = import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000'
        fetch(`${apiBaseUrl}/reverse-geocode?latitude=${encodeURIComponent(coords.latitude)}&longitude=${encodeURIComponent(coords.longitude)}`)
          .then((response) => {
            if (!response.ok) throw new Error('주소 조회 실패')
            return response.json()
          })
          .then(setAddress)
          .catch(() => setAddress(null))
      },
      () => setStatus('denied'),
      { enableHighAccuracy: true, timeout: 10000, maximumAge: 60000 },
    )
  }, [])

  return { location, address, status, requestLocation }
}
