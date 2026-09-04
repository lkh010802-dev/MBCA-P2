import { useEffect, useRef, useState } from 'react'

const SCRIPT_ID = 'kakao-map-sdk'

function loadKakaoMap(key) {
  if (window.kakao?.maps) return Promise.resolve(window.kakao.maps)

  return new Promise((resolve, reject) => {
    const existing = document.getElementById(SCRIPT_ID)
    if (existing) {
      existing.addEventListener('load', () => window.kakao.maps.load(() => resolve(window.kakao.maps)), { once: true })
      existing.addEventListener('error', reject, { once: true })
      return
    }

    const script = document.createElement('script')
    script.id = SCRIPT_ID
    script.async = true
    script.src = `https://dapi.kakao.com/v2/maps/sdk.js?appkey=${key}&autoload=false`
    script.onload = () => window.kakao.maps.load(() => resolve(window.kakao.maps))
    script.onerror = () => reject(new Error('카카오맵을 불러오지 못했습니다.'))
    document.head.appendChild(script)
  })
}

function toCoordinates(points) {
  let source = points
  if (typeof source === 'string') {
    try { source = JSON.parse(source) } catch { return [] }
  }
  if (!Array.isArray(source)) source = source?.coordinates ?? source?.points
  if (!Array.isArray(source)) return []
  if (typeof source[0] === 'number') {
    return source.reduce((result, value, index) => (index % 2 === 0 && source[index + 1] !== undefined ? [...result, [value, source[index + 1]]] : result), [])
  }
  return source
    .map((point) => Array.isArray(point) ? point : [point?.x ?? point?.longitude, point?.y ?? point?.latitude])
    .filter(([longitude, latitude]) => Number.isFinite(Number(longitude)) && Number.isFinite(Number(latitude)))
}

const subwayColors = { '1호선': '#2f81f7', '2호선': '#29a655', '3호선': '#ef7b2d', '4호선': '#39a6d8', '5호선': '#8b51b8', '6호선': '#b56a36', '7호선': '#6b8c2d', '8호선': '#e44a89', '9호선': '#bd9d35', '경의중앙선': '#6db5a2', '신분당선': '#d84250' }
const busColors = ['#2879e8', '#4589e8', '#5b86dc', '#6d7ed2', '#7c72c5']

function segmentStyle(segment, index) {
  if (segment.type === 'WALKING') return { color: '#6f8399', style: 'shortdash', weight: 5 }
  if (segment.type === 'SUBWAY') {
    const line = Object.keys(subwayColors).find((name) => segment.vehicle?.includes(name))
    return { color: subwayColors[line] ?? '#4685e8', style: 'solid', weight: 6 }
  }
  const seed = [...(segment.vehicle ?? `${index}`)].reduce((sum, character) => sum + character.charCodeAt(0), 0)
  return { color: busColors[seed % busColors.length], style: 'solid', weight: 6 }
}

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>'"]/g, (character) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[character]))
}

function KakaoCourseMap({ mapContext, selectedArea, areaRoute, walkingRouteLoading = false, selectedPlaces = [], focusedStopIndex = null, course }) {
  const containerRef = useRef(null)
  const mapRef = useRef(null)
  const mapsRef = useRef(null)
  const layersRef = useRef([])
  const [status, setStatus] = useState('loading')
  const [mapReady, setMapReady] = useState(false)
  const key = import.meta.env.VITE_KAKAO_MAP_KEY

  useEffect(() => {
    if (!key) {
      setStatus('missing-key')
      return undefined
    }
    if (!mapContext?.start || !containerRef.current) return undefined

    let cancelled = false
    loadKakaoMap(key)
      .then((maps) => {
        if (cancelled) return
        const start = new maps.LatLng(mapContext.start.latitude, mapContext.start.longitude)
        mapsRef.current = maps
        mapRef.current = new maps.Map(containerRef.current, { center: start, level: 5 })
        setStatus('ready')
        setMapReady(true)
      })
      .catch(() => !cancelled && setStatus('error'))

    return () => { cancelled = true }
  }, [key, mapContext?.start?.latitude, mapContext?.start?.longitude])

  useEffect(() => {
    const maps = mapsRef.current
    const map = mapRef.current
    if (!mapReady || !maps || !map || !mapContext?.start) return

    // 지도 바탕은 유지하고, 선택에 따라 경로·핀 레이어만 교체한다.
    layersRef.current.forEach((layer) => layer.setMap?.(null))
    layersRef.current = []
    const addLayer = (layer) => { layersRef.current.push(layer); return layer }
    const bounds = new maps.LatLngBounds()
    const start = new maps.LatLng(mapContext.start.latitude, mapContext.start.longitude)
    bounds.extend(start)
    addLayer(new maps.Marker({ map, position: start, title: '현재 위치' }))

    if (selectedArea?.latitude != null && selectedArea?.longitude != null) {
      const isCourseMode = Boolean(course?.legs?.length)
      // 코스 확정 후에는 지역 중심좌표를 포함하지 않는다.
      // 실제 장소와 이동 경로만으로 지도를 맞춰 코스가 선명하게 보이게 한다.
      if (!isCourseMode) {
        const destination = new maps.LatLng(selectedArea.latitude, selectedArea.longitude)
        bounds.extend(destination)
        addLayer(new maps.Marker({ map, position: destination, title: selectedArea.name }))
      }

      // 최종 코스가 있으면 코스 구간을, 그 전에는 선택한 지역의 경로를 쓴다.
      // 좌표가 없을 때는 직선 대체선을 만들지 않는다.
      const courseSegments = (course?.legs ?? []).flatMap((leg) => leg.travel?.paths ?? [])
      const segments = courseSegments.length ? courseSegments : (areaRoute?.paths ?? [])
      let previousTransit = null

      segments.forEach((segment, index) => {
        const path = toCoordinates(segment.points).map(([longitude, latitude]) => new maps.LatLng(latitude, longitude))
        if (path.length < 2) return
        path.forEach((point) => bounds.extend(point))
        const visual = segmentStyle(segment, index)
        if (segment.type === 'WALKING') {
          const walkingHalo = addLayer(new maps.Polyline({ path, strokeWeight: course?.legs?.length ? 11 : 9, strokeColor: '#ffffff', strokeOpacity: 0.92, zIndex: 10 + index }))
          walkingHalo.setMap(map)
        }
        const polyline = addLayer(new maps.Polyline({ path, strokeWeight: visual.weight + (course?.legs?.length ? 2 : 0), strokeColor: visual.color, strokeOpacity: 1, strokeStyle: visual.style, zIndex: 20 + index }))
        polyline.setMap(map)

        const isTransit = segment.type === 'BUS' || segment.type === 'SUBWAY'
        if (isTransit && previousTransit && (previousTransit.type !== segment.type || previousTransit.vehicle !== segment.vehicle)) {
          addLayer(new maps.CustomOverlay({ map, position: path[0], content: '<div class="map-transfer-marker">환승</div>', yAnchor: 1.15 }))
        }
        if (isTransit) previousTransit = segment
      })
    }

    selectedPlaces.forEach((place, index) => {
      if (place.latitude == null || place.longitude == null) return
      const position = new maps.LatLng(place.latitude, place.longitude)
      bounds.extend(position)
      addLayer(new maps.CustomOverlay({
        map,
        position,
        content: `<div class="map-place-marker${focusedStopIndex === index ? ' is-focused' : ''}"><b>${index + 1}</b><span>${escapeHtml(place.name)}</span></div>`,
        yAnchor: 1.15,
      }))
    })

    if (course?.legs?.length) {
      const total = course.total_travel_time_minutes ?? 0
      addLayer(new maps.CustomOverlay({
        map,
        position: start,
        content: `<div class="map-course-summary">실제 이동 ${total}분</div>`,
        yAnchor: 1.2,
      }))
    }
    // 완성 코스는 하단 확인 패널에 가려지지 않도록 여유를 두고 전체 동선을 맞춘다.
    map.relayout?.()
    map.setBounds(bounds, 42, 20, course?.legs?.length ? 230 : 110, 20)
  }, [mapReady, mapContext, selectedArea, areaRoute, selectedPlaces, course, focusedStopIndex])

  useEffect(() => {
    const maps = mapsRef.current
    const map = mapRef.current
    const focusedPlace = selectedPlaces[focusedStopIndex]
    if (!mapReady || !maps || !map || !focusedPlace || focusedPlace.latitude == null || focusedPlace.longitude == null) return
    const position = new maps.LatLng(focusedPlace.latitude, focusedPlace.longitude)
    map.setLevel(3, { animate: true })
    map.panTo(position)
  }, [mapReady, focusedStopIndex, selectedPlaces])

  return (
    <div className="kakao-course-map">
      <div ref={containerRef} className="kakao-course-map__canvas" />
      {status === 'loading' && <p className="map-status">지도를 불러오는 중이에요</p>}
      {status === 'missing-key' && <p className="map-status">VITE_KAKAO_MAP_KEY를 설정하면 실제 지도가 표시돼요.</p>}
      {status === 'error' && <p className="map-status">카카오 지도 설정을 확인해 주세요.</p>}
      {status === 'ready' && walkingRouteLoading && <p className="map-route-loading"><i />실제 도보 동선을 확인하는 중</p>}
    </div>
  )
}

export default KakaoCourseMap
