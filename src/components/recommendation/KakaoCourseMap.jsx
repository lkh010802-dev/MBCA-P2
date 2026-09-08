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
// 현재 위치의 파란색과 겹치지 않도록 장소별 코스는 주황·초록·분홍으로 구분한다.
const placeColors = ['#ec7b22', '#159b63', '#dc3f78', '#9b59b6']

function segmentStyle(segment, index, isCourseMode) {
  // 안내·검토·지역 미리보기 모두 도보는 동일한 파란 점선으로 표시한다.
  if (segment.type === 'WALKING') return { color: '#2879ed', style: 'shortdot', weight: 7 }
  if (segment.type === 'SUBWAY') {
    const line = Object.keys(subwayColors).find((name) => segment.vehicle?.includes(name))
    return { color: subwayColors[line] ?? '#4685e8', style: 'solid', weight: 6 }
  }
  if (segment.type === 'DRIVING') return { color: '#52677f', style: 'solid', weight: 7 }
  const seed = [...(segment.vehicle ?? `${index}`)].reduce((sum, character) => sum + character.charCodeAt(0), 0)
  return { color: busColors[seed % busColors.length], style: 'solid', weight: 6 }
}

function directionArrows(path) {
  if (path.length < 2) return []
  let distance = 0
  for (let index = 1; index < path.length; index += 1) {
    distance += Math.hypot((path[index].getLat() - path[index - 1].getLat()) * 111, (path[index].getLng() - path[index - 1].getLng()) * 88)
  }
  const count = distance > 2.5 ? 3 : distance > 0.8 ? 2 : 1
  return Array.from({ length: count }, (_, arrowIndex) => {
    const pointIndex = Math.max(1, Math.min(path.length - 1, Math.round((path.length - 1) * ((arrowIndex + 1) / (count + 1)))))
    const from = path[pointIndex - 1]
    const to = path[pointIndex]
    const angle = Math.atan2(-(to.getLat() - from.getLat()), (to.getLng() - from.getLng()) * Math.cos(to.getLat() * Math.PI / 180)) * 180 / Math.PI
    return { position: to, angle }
  })
}

function courseZoomLevel(points) {
  if (points.length < 2) return 3
  const latitudes = points.map((point) => point.latitude)
  const longitudes = points.map((point) => point.longitude)
  const centerLatitude = (Math.max(...latitudes) + Math.min(...latitudes)) / 2
  const latitudeKm = (Math.max(...latitudes) - Math.min(...latitudes)) * 111
  const longitudeKm = (Math.max(...longitudes) - Math.min(...longitudes)) * 111 * Math.cos(centerLatitude * Math.PI / 180)
  const spanKm = Math.sqrt(latitudeKm ** 2 + longitudeKm ** 2)

  if (spanKm <= 0.7) return 3
  if (spanKm <= 1.6) return 4
  if (spanKm <= 3.5) return 5
  if (spanKm <= 7) return 6
  return 7
}

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>'"]/g, (character) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[character]))
}

function KakaoCourseMap({ mapContext, selectedArea, areaRoute, walkingRouteLoading = false, selectedPlaces = [], focusedStopIndex = null, course, courseConfirmed = false, liveLocation = null, guideRoute = null, guidanceActive = false, guidanceStartLocation = null, guidanceStartLabel = '현재 위치' }) {
  const containerRef = useRef(null)
  const mapRef = useRef(null)
  const mapsRef = useRef(null)
  const layersRef = useRef([])
  const [status, setStatus] = useState('loading')
  const [mapReady, setMapReady] = useState(false)
  const key = import.meta.env.VITE_KAKAO_MAP_KEY
  const isCourseReview = Boolean(course?.legs?.length && !courseConfirmed)
  // 확정 전에는 사용자가 고른 장소까지만 검토한다. 마지막 "다음 일정" 구간은
  // 확정 후 전체 동선을 볼 때에만 지도에 포함한다. 출발 위치에서 첫 장소까지의
  // 구간도 검토 화면에서는 빼서, 선택한 장소 사이 코스 자체에 집중하게 한다.
  const displayedCourseLegs = isCourseReview
    ? course.legs.slice(1, selectedPlaces.length)
    : (course?.legs ?? [])
  const missingCoursePath = displayedCourseLegs.some((leg) => !leg.travel?.nearby
    && !(leg.travel?.paths ?? []).some((segment) => toCoordinates(segment.points).length >= 2))

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
    const coursePoints = []
    const extendBounds = (point) => {
      bounds.extend(point)
      coursePoints.push({ latitude: point.getLat(), longitude: point.getLng() })
    }
    const activeStart = guidanceActive && guidanceStartLocation ? guidanceStartLocation : mapContext.start
    const start = new maps.LatLng(activeStart.latitude, activeStart.longitude)
    if (!isCourseReview) {
      extendBounds(start)
      const startLabel = escapeHtml(guidanceActive ? guidanceStartLabel : '현재 위치')
      addLayer(new maps.CustomOverlay({ map, position: start, content: `<div class="map-current-marker">${startLabel}</div><div class="map-current-pin" aria-label="${startLabel}"><i /></div>`, yAnchor: 1, xAnchor: 0.5 }))
    }
    if ((!course || courseConfirmed) && (!guidanceActive || focusedStopIndex == null) && mapContext.end?.latitude != null && mapContext.end?.longitude != null) {
      const end = new maps.LatLng(mapContext.end.latitude, mapContext.end.longitude)
      extendBounds(end)
      addLayer(new maps.CustomOverlay({ map, position: end, content: '<div class="map-end-marker">다음 일정</div><div class="map-end-pin" aria-label="다음 일정"><i /></div>', yAnchor: 1, xAnchor: 0.5 }))
    }

    if (selectedArea?.latitude != null && selectedArea?.longitude != null) {
      const isCourseMode = Boolean(course?.legs?.length) || guidanceActive
      // 코스 확정 후에는 지역 중심좌표를 포함하지 않는다.
      // 실제 장소와 이동 경로만으로 지도를 맞춰 코스가 선명하게 보이게 한다.
      if (!isCourseMode) {
        const destination = new maps.LatLng(selectedArea.latitude, selectedArea.longitude)
        extendBounds(destination)
        addLayer(new maps.Marker({ map, position: destination, title: selectedArea.name }))
      }

      // 최종 코스가 있으면 코스 구간을, 그 전에는 선택한 지역의 경로를 쓴다.
      // 좌표가 없을 때는 직선 대체선을 만들지 않는다.
      const courseSegments = displayedCourseLegs.flatMap((leg, legIndex) => {
        const isFirstLeg = !isCourseReview && legIndex === 0
        const isFinalLeg = !isCourseReview && Boolean(mapContext.end) && legIndex === (course?.legs?.length ?? 0) - 1
        const paths = leg.travel?.paths ?? []
        return paths.map((segment, segmentIndex) => ({
        ...segment,
        routeColorIndex: legIndex,
        // 출발지에서 탑승 지점까지, 마지막 하차 지점에서 다음 일정까지의 도보만
        // 공통 회색으로 두고, 하차 후 선택 장소로 들어가는 길은 코스 색을 유지한다.
        isEdgeWalking: (isFirstLeg && segmentIndex === 0) || (isFinalLeg && segmentIndex === paths.length - 1),
      }))
      })
      // 현재 위치 기준 경로가 갱신되는 동안에는 처음 계산한 해당 구간을 유지해
      // 지도에서 길이 잠깐 사라지는 현상을 막는다.
      // 실시간 위치를 받은 뒤에는 과거 출발점 기준 코스를 대체선으로 쓰지 않는다.
      // 새 경로가 준비될 때까지 잠깐 비워 두어 잘못된 두 경로가 겹치지 않게 한다.
      const guideFallbackSegments = liveLocation ? [] : (course?.legs?.[focusedStopIndex]?.travel?.paths ?? [])
      const segments = guidanceActive ? ((guideRoute?.paths?.length ? guideRoute.paths : guideFallbackSegments)) : (isCourseMode ? courseSegments : (areaRoute?.paths ?? []))
      let previousTransit = null

      segments.forEach((segment, index) => {
        const path = toCoordinates(segment.points).map(([longitude, latitude]) => new maps.LatLng(latitude, longitude))
        if (path.length < 2) return
        path.forEach(extendBounds)
        const visual = segmentStyle(segment, index, isCourseMode)
        if (segment.type === 'WALKING') {
          const walkingHalo = addLayer(new maps.Polyline({ path, strokeWeight: course?.legs?.length ? (segment.isEdgeWalking ? 14 : 18) : 13, strokeColor: '#ffffff', strokeOpacity: 0.98, zIndex: 10 + index }))
          walkingHalo.setMap(map)
        }
        const polyline = addLayer(new maps.Polyline({ path, strokeWeight: visual.weight + (course?.legs?.length ? 2 : 0), strokeColor: visual.color, strokeOpacity: 1, strokeStyle: visual.style, zIndex: 20 + index }))
        polyline.setMap(map)
        if (segment.type !== 'WALKING') {
          directionArrows(path).forEach(({ position, angle }) => {
            addLayer(new maps.CustomOverlay({ map, position, content: `<i class="map-route-direction is-transit" style="--route-angle:${angle}deg" aria-label="진행 방향" />`, xAnchor: 0.5, yAnchor: 0.5, zIndex: 30 + index }))
          })
        }

        const isTransit = segment.type === 'BUS' || segment.type === 'SUBWAY'
        if (isTransit && previousTransit && (previousTransit.type !== segment.type || previousTransit.vehicle !== segment.vehicle)) {
          addLayer(new maps.CustomOverlay({ map, position: path[0], content: '<div class="map-transfer-marker">환승</div>', yAnchor: 1.15 }))
        }
        if (isTransit) previousTransit = segment
      })
    }

    const visibleMapPlaces = guidanceActive
      ? selectedPlaces.map((place, index) => ({ place, index })).filter(({ index }) => index === focusedStopIndex)
      : selectedPlaces.map((place, index) => ({ place, index }))
    visibleMapPlaces.forEach(({ place, index }) => {
      if (place.latitude == null || place.longitude == null) return
      const position = new maps.LatLng(place.latitude, place.longitude)
      extendBounds(position)
      // 기본 지도에는 이름 라벨이 없고 선택한 한 곳만 노출되므로, 핀 바로 위에
      // 붙여 이름과 실제 좌표가 같은 장소임을 즉시 알 수 있게 한다.
      const [offsetX, offsetY] = [0, -26]
      const placeColor = placeColors[index % placeColors.length]
      addLayer(new maps.CustomOverlay({
        map,
        position,
        content: `<div class="map-place-pin${focusedStopIndex === index ? ' is-focused' : ''}" style="--place-color:${placeColor}"><b>${index + 1}</b></div>`,
        yAnchor: 1,
        xAnchor: 0.5,
      }))
      if (focusedStopIndex === index) {
        addLayer(new maps.CustomOverlay({
          map,
          position,
          content: `<div class="map-place-marker-slot" style="--marker-offset-x:${offsetX}px;--marker-offset-y:${offsetY}px;--place-color:${placeColor}"><div class="map-place-marker is-focused"><b>${index + 1}</b><span>${escapeHtml(place.name)}</span></div></div>`,
          yAnchor: 1.15,
        }))
      }
    })
    // 완성 코스는 하단 확인 패널에 가려지지 않도록 여유를 두고 전체 동선을 맞춘다.
    map.relayout?.()
    if (guidanceActive || !course || courseConfirmed || focusedStopIndex == null) {
      const mobile = window.matchMedia('(max-width: 899px)').matches
      const compactCourse = Boolean(course && !courseConfirmed && !guidanceActive)
      map.setBounds(bounds, compactCourse ? 10 : 42, 20, mobile ? (course?.legs?.length ? (compactCourse ? 120 : 230) : 110) : (compactCourse ? 16 : 42), 20)
      // 코스가 짧을수록 더 확대한다. 모든 실제 경로 좌표를 기준으로 계산하므로
      // 1·2번 장소와 그 사이 이동선이 화면 안에 함께 남는다.
      if (compactCourse) {
        const targetLevel = courseZoomLevel(coursePoints)
        if (map.getLevel() > targetLevel) map.setLevel(targetLevel, { animate: true })
      }
    }
  }, [mapReady, mapContext, selectedArea, areaRoute, selectedPlaces, course, courseConfirmed, focusedStopIndex, displayedCourseLegs, isCourseReview, liveLocation, guideRoute, guidanceActive, guidanceStartLocation, guidanceStartLabel])

  useEffect(() => {
    const maps = mapsRef.current
    const map = mapRef.current
    const focusedPlace = selectedPlaces[focusedStopIndex]
    if (guidanceActive || !mapReady || !maps || !map || !focusedPlace || focusedPlace.latitude == null || focusedPlace.longitude == null) return
    const position = new maps.LatLng(focusedPlace.latitude, focusedPlace.longitude)
    map.setLevel(3, { animate: true })
    map.panTo(position)
  }, [mapReady, focusedStopIndex, selectedPlaces, course, guidanceActive])

  return (
    <div className="kakao-course-map">
      <div ref={containerRef} className="kakao-course-map__canvas" />
      {status === 'loading' && <p className="map-status">지도를 불러오는 중이에요</p>}
      {status === 'missing-key' && <p className="map-status">VITE_KAKAO_MAP_KEY를 설정하면 실제 지도가 표시돼요.</p>}
      {status === 'error' && <p className="map-status">카카오 지도 설정을 확인해 주세요.</p>}
      {status === 'ready' && walkingRouteLoading && <p className="map-route-loading"><i />실제 도보 동선을 확인하는 중</p>}
      {status === 'ready' && missingCoursePath && <p className="map-route-loading" role="status">일부 구간의 상세 경로를 불러오지 못했어요</p>}
    </div>
  )
}

export default KakaoCourseMap
