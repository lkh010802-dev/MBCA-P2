import { useEffect, useMemo, useRef, useState } from 'react'
import { normalizeRecommendation } from '../utils/normalizeRecommendation'
import { readSession, writeSession } from '../utils/sessionStore'
import KakaoCourseMap from '../components/recommendation/KakaoCourseMap'
import { requestCourse, requestMorePlaces, requestPlaces, requestRoutePreview, validatePlaceSelection } from '../api/placesApi'

const categoryLabels = { food: '식당', cafe: '카페', walk: '산책', culture: '문화', entertainment: '즐길거리', shopping: '쇼핑', drink: '술집' }
const stayMinutesByCategory = { food: 60, cafe: 45, walk: 40, culture: 75, entertainment: 60, shopping: 45, drink: 60 }
const categoryIcons = { food: '🍽', cafe: '☕', walk: '🌿', culture: '🖼', entertainment: '🎟', shopping: '🛍', drink: '🍷' }
const courseStopColors = ['#ec7b22', '#159b63', '#dc3f78', '#9b59b6']
const ARRIVAL_RADIUS_METERS = 30
const ARRIVAL_DWELL_SECONDS = 60
const transportOptions = [
  { id: 'public_transit', label: '대중교통', icon: '🚇' },
  { id: 'car', label: '자동차', icon: '🚗' },
  { id: 'walk', label: '도보', icon: '🚶' },
]

function normalizePlace(place, index) {
  const category = place.category ?? 'culture'
  return {
    ...place,
    id: `${place.source ?? 'place'}-${place.source_id ?? index}-${place.name}`,
    name: place.name ?? '추천 장소',
    category,
    categoryLabel: categoryLabels[category] ?? place.category_detail ?? '장소',
    categoryIcon: categoryIcons[category] ?? '📍',
    stayMinutes: stayMinutesByCategory[category] ?? 45,
    distanceMeters: Number(place.distance_m ?? 0),
  }
}

function straightDistanceMinutes(from, to) {
  if (!from || !to || from.latitude == null || to.latitude == null) return 0
  const latKm = (to.latitude - from.latitude) * 111
  const lonKm = (to.longitude - from.longitude) * 88
  return Math.max(1, Math.round(Math.sqrt(latKm ** 2 + lonKm ** 2) / 4.5 * 60))
}

function distanceMetersBetween(from, to) {
  if (!from || !to || from.latitude == null || to.latitude == null) return Infinity
  const radius = 6371000
  const latitudeDelta = (Number(to.latitude) - Number(from.latitude)) * Math.PI / 180
  const longitudeDelta = (Number(to.longitude) - Number(from.longitude)) * Math.PI / 180
  const a = Math.sin(latitudeDelta / 2) ** 2
    + Math.cos(Number(from.latitude) * Math.PI / 180) * Math.cos(Number(to.latitude) * Math.PI / 180) * Math.sin(longitudeDelta / 2) ** 2
  return 2 * radius * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a))
}

function AreaCard({ area, selected, onSelect, onPreview }) {
  return (
    <button className={`area-card${selected ? ' is-selected' : ''}`} type="button" onMouseEnter={onPreview} onFocus={onPreview} onTouchStart={onPreview} onClick={onSelect}>
      <div className="area-card-top"><span>{area.rank}위</span><strong>{area.name}</strong>{area.score && <em>{area.score}점</em>}</div>
      <div className="area-route">
        {area.fromStartMinutes > 0 && <span>여기까지 <b>{formatMinutes(area.fromStartMinutes)}{area.fromStartTransport && ` · ${area.fromStartTransport}`}</b></span>}
        {area.stayMinutes !== null && <span>머무르기 <b>{formatMinutes(area.stayMinutes)}</b></span>}
        {area.toNextMinutes > 0 && <span>다음 일정까지 <b>{formatMinutes(area.toNextMinutes)}{area.toNextTransport && ` · ${area.toNextTransport}`}</b></span>}
      </div>
      <div className="area-metrics"><span>예상 혼잡도 <b>{area.congestion}</b></span>{area.arrivalTime && <span>도착 <b>{area.arrivalTime}</b></span>}</div>
    </button>
  )
}

function findSelectedPlace(optimizedPlace, selectedPlaces) {
  return selectedPlaces.find((place) => (
    place.category === optimizedPlace.category
    &&
    Math.abs(Number(place.latitude) - Number(optimizedPlace.latitude)) < 0.000001
    && Math.abs(Number(place.longitude) - Number(optimizedPlace.longitude)) < 0.000001
  ))
}

function formatDistance(distanceMeters) {
  if (!distanceMeters) return '거리 정보 없음'
  return distanceMeters >= 1000 ? `${(distanceMeters / 1000).toFixed(1)}km` : `${distanceMeters}m`
}

function formatMinutes(minutes) {
  if (minutes == null || Number.isNaN(Number(minutes))) return '시간 확인 중'
  const value = Math.max(0, Math.round(Number(minutes)))
  if (value < 60) return `${value}분`
  const hours = Math.floor(value / 60)
  const rest = value % 60
  return rest ? `${hours}시간 ${rest}분` : `${hours}시간`
}

function formatLegTransport(travel) {
  if (!travel) return '이동 경로 확인 중'
  if (travel.nearby) return '아주 가까운 거리 · 약 1분'
  if (travel.mode === 'walk') return `도보 ${travel.duration_min ?? 0}분`
  const type = travel.route_type === 'SUBWAY' ? '지하철' : travel.route_type === 'BUS' ? '버스' : travel.route_type === 'BUS_AND_SUBWAY' ? '버스·지하철' : '대중교통'
  const vehicles = [...new Set((travel.paths ?? [])
    .filter((path) => (path.type === 'BUS' || path.type === 'SUBWAY') && path.vehicle)
    .map((path) => path.vehicle))]
  const routeName = vehicles.length ? vehicles.join(' · ') : type
  const transfer = travel.transfers > 0 ? ` · 환승 ${travel.transfers}회` : ''
  return `${routeName} · ${travel.duration_min ?? 0}분${transfer}`
}

function RecommendationPage({ response, onBack }) {
  const result = useMemo(() => normalizeRecommendation(response), [response])
  const rankingAreas = useMemo(() => [...(result.targetArea ? [result.targetArea] : []), ...result.otherAreas, ...result.extendedAreas], [result])
  const [selectedIndex, setSelectedIndex] = useState(0)
  const [placeMode, setPlaceMode] = useState(false)
  const [selectedPlaces, setSelectedPlaces] = useState([])
  const [calculated, setCalculated] = useState(false)
  const [places, setPlaces] = useState([])
  const [placeCursor, setPlaceCursor] = useState(null)
  const [nextOffset, setNextOffset] = useState(null)
  const [hasMorePlaces, setHasMorePlaces] = useState(false)
  const [placeStatus, setPlaceStatus] = useState('idle')
  const [placeError, setPlaceError] = useState('')
  const [calculationStatus, setCalculationStatus] = useState('idle')
  const [calculationError, setCalculationError] = useState('')
  const [courseResult, setCourseResult] = useState(null)
  const [courseConfirmed, setCourseConfirmed] = useState(false)
  const [guidanceStarted, setGuidanceStarted] = useState(false)
  const [guideStep, setGuideStep] = useState(0)
  const [liveLocation, setLiveLocation] = useState(null)
  const [liveLocationStatus, setLiveLocationStatus] = useState('idle')
  const [guideRoute, setGuideRoute] = useState(null)
  const [arrivalSeconds, setArrivalSeconds] = useState(0)
  const [transportMode, setTransportMode] = useState('public_transit')
  const historyKey = `koala-history-${JSON.stringify(response.map_context)}`
  const [courseHistory, setCourseHistory] = useState(() => readSession(historyKey, []))
  useEffect(() => { writeSession(historyKey, courseHistory) }, [historyKey, courseHistory])
  const [focusedStopIndex, setFocusedStopIndex] = useState(null)
  const [sheetExpanded, setSheetExpanded] = useState(false)
  const [routeCache, setRouteCache] = useState({})
  const [routeLoading, setRouteLoading] = useState({})
  const dragStartY = useRef(null)
  const didDrag = useRef(false)
  const requestingRouteKeys = useRef(new Set())
  const calculationRequest = useRef(0)
  const lastLiveLocation = useRef(null)
  const lastGuideRouteRequest = useRef(null)
  const arrivalRef = useRef({ targetId: null, enteredAt: null, lastLocationAt: null })
  useEffect(() => () => { calculationRequest.current += 1 }, [])
  const selectedArea = rankingAreas[selectedIndex] ?? result.currentArea
  const startLocation = result.mapContext?.start ?? { latitude: selectedArea?.latitude ?? 37.5563, longitude: selectedArea?.longitude ?? 126.9236 }
  const routeCacheKey = selectedArea?.latitude != null && selectedArea?.longitude != null
    ? `${transportMode}:${Number(selectedArea.latitude).toFixed(5)},${Number(selectedArea.longitude).toFixed(5)}`
    : null
  const selectedAreaRoute = (routeCacheKey && routeCache[routeCacheKey]) ?? selectedArea?.startRoute ?? null
  const isWalkingRouteLoading = Boolean(routeCacheKey && routeLoading[routeCacheKey] && !routeCache[routeCacheKey])
  const savedCoursesForArea = courseHistory.filter((item) => item.areaName === selectedArea?.name)

  const prepareAreaRoute = (area) => {
    if (!area || area.latitude == null || area.longitude == null) return
    const areaKey = `${transportMode}:${Number(area.latitude).toFixed(5)},${Number(area.longitude).toFixed(5)}`
    if (routeCache[areaKey] || requestingRouteKeys.current.has(areaKey)) return
    requestingRouteKeys.current.add(areaKey)
    setRouteLoading((current) => ({ ...current, [areaKey]: true }))
    requestRoutePreview({ startLatitude: startLocation.latitude, startLongitude: startLocation.longitude, endLatitude: area.latitude, endLongitude: area.longitude, transportMode })
      .then((route) => setRouteCache((current) => ({ ...current, [areaKey]: route })))
      .catch(() => { /* 기존 카카오 대중교통 경로는 그대로 보여 준다. */ })
      .finally(() => {
        requestingRouteKeys.current.delete(areaKey)
        setRouteLoading((current) => ({ ...current, [areaKey]: false }))
      })
  }

  useEffect(() => { if (placeMode) setSheetExpanded(true) }, [placeMode])
  useEffect(() => {
    // 1순위는 서버가 미리 준비해 준 Tmap 보행 경로를 즉시 사용한다.
    // 다른 지역은 기존 지도 경로를 먼저 그리고, 보행 보강본만 뒤에서 받아 캐시한다.
    if (!routeCacheKey) return
    prepareAreaRoute(selectedArea)
  }, [routeCache, routeCacheKey, selectedArea?.hasPreparedMapRoute, selectedArea?.latitude, selectedArea?.longitude, startLocation.latitude, startLocation.longitude, transportMode])

  useEffect(() => {
    // 전체 후보를 동시에 호출하지 않고, 사용자가 다음으로 볼 가능성이 높은 후보 하나만 준비한다.
    const nextArea = rankingAreas.find((area, index) => index !== selectedIndex && !area.hasPreparedMapRoute)
    if (!nextArea) return undefined
    const timer = window.setTimeout(() => prepareAreaRoute(nextArea), 900)
    return () => window.clearTimeout(timer)
  }, [selectedIndex, rankingAreas, routeCache, transportMode])

  useEffect(() => {
    if (!placeMode || !selectedArea?.name || selectedArea.latitude == null || selectedArea.longitude == null) return undefined
    let cancelled = false
    setPlaceStatus('loading')
    setPlaceError('')
    requestPlaces({ areaName: selectedArea.name, latitude: selectedArea.latitude, longitude: selectedArea.longitude })
      .then((data) => {
        if (cancelled) return
        setPlaces((data.places ?? []).map(normalizePlace))
        setPlaceCursor(data.cursor ?? null)
        setNextOffset(data.next_offset ?? null)
        setHasMorePlaces(Boolean(data.has_more))
        setPlaceStatus('ready')
      })
      .catch((error) => { if (!cancelled) { setPlaces([]); setPlaceStatus('error'); setPlaceError(error.message) } })
    return () => { cancelled = true }
  }, [placeMode, selectedArea?.name, selectedArea?.latitude, selectedArea?.longitude])

  const handleLoadMore = async () => {
    if (!placeCursor || nextOffset == null || placeStatus === 'more-loading') return
    setPlaceStatus('more-loading')
    try {
      const data = await requestMorePlaces({ cursor: placeCursor, offset: nextOffset })
      setPlaces((current) => [...current, ...(data.places ?? []).map((place, index) => normalizePlace(place, current.length + index))])
      setNextOffset(data.next_offset ?? null)
      setHasMorePlaces(Boolean(data.has_more))
      setPlaceStatus('ready')
    } catch (error) {
      setPlaceStatus('ready')
      setPlaceError(error.message)
    }
  }

  const handleSheetPointerDown = (event) => { dragStartY.current = event.clientY; didDrag.current = false }
  const handleSheetPointerMove = (event) => { if (dragStartY.current !== null && Math.abs(event.clientY - dragStartY.current) > 10) didDrag.current = true }
  const handleSheetPointerUp = (event) => {
    if (dragStartY.current === null) return
    const distance = event.clientY - dragStartY.current
    if (distance < -24) setSheetExpanded(true)
    if (distance > 24) setSheetExpanded(false)
    dragStartY.current = null
  }
  const togglePlace = (place) => {
    calculationRequest.current += 1
    setFocusedStopIndex(null)
    setCalculated(false)
    setCalculationError('')
    setCalculationStatus('idle')
    setCourseResult(null)
    setCourseConfirmed(false)
    setGuidanceStarted(false)
    setGuideStep(0)
    setSelectedPlaces((current) => {
      const existingIndex = current.findIndex((item) => item.id === place.id)
      if (existingIndex >= 0) {
        setFocusedStopIndex(null)
        return current.filter((item) => item.id !== place.id)
      }
      setFocusedStopIndex(current.length)
      return [...current, place]
    })
  }
  const estimatedStay = selectedPlaces.reduce((sum, place) => sum + place.stayMinutes, 0)
  const estimatedTravel = selectedPlaces.reduce((sum, place, index) => sum + straightDistanceMinutes(index === 0 ? selectedArea : selectedPlaces[index - 1], place), 0)
  const availableTimeMinutes = Math.max(1, result.mapContext?.available_time_minutes
    ?? (selectedArea?.stayMinutes != null
      ? selectedArea.stayMinutes + selectedArea.fromStartMinutes + selectedArea.toNextMinutes : 120))

  const handleCalculate = async () => {
    if (!selectedPlaces.length) return
    const requestId = ++calculationRequest.current
    setCalculationStatus('loading')
    setCalculationError('')
    try {
      const validation = await validatePlaceSelection({ startLatitude: startLocation.latitude, startLongitude: startLocation.longitude, selectedPlaces, availableTimeMinutes })
      if (requestId !== calculationRequest.current) return
      setCourseResult({ validation, course: null })
      // The straight-distance estimate is advisory; actual routing decides feasibility.
      const course = await requestCourse({ startLocation, selectedPlaces, availableTimeMinutes, endLocation: result.mapContext?.end, transportMode })
      if (requestId !== calculationRequest.current) return
      setCourseResult({ validation, course })
      if (course.status !== 'FEASIBLE') {
        setCalculationStatus('warning')
        return
      }
      setCourseHistory((current) => [{
        id: `${Date.now()}-${selectedArea?.name ?? 'course'}`,
        areaName: selectedArea?.name,
        selectedPlaces: [...selectedPlaces],
        validation,
        course,
      }, ...current].slice(0, 3))
      setCalculated(true)
      setCourseConfirmed(false)
      setGuidanceStarted(false)
      setGuideStep(0)
      setFocusedStopIndex(null)
      setCalculationStatus('ready')
    } catch (error) {
      if (requestId !== calculationRequest.current) return
      setCalculationStatus('error')
      setCalculationError(error.message)
    }
  }

  const orderedPlaces = useMemo(() => {
    const remaining = [...selectedPlaces]
    return (courseResult?.course?.optimized_places ?? []).map((place) => {
      const match = findSelectedPlace(place, remaining)
      if (match) remaining.splice(remaining.indexOf(match), 1)
      return match
    }).filter(Boolean)
  }, [courseResult, selectedPlaces])
  const visiblePlaces = calculated && orderedPlaces.length ? orderedPlaces : selectedPlaces
  const guideStopCount = visiblePlaces.length + (result.mapContext?.end ? 1 : 0)
  const guideIsComplete = guidanceStarted && guideStep >= guideStopCount
  const guidePlace = guideStep < visiblePlaces.length ? visiblePlaces[guideStep] : null
  const guideDestination = guidePlace ?? (guideStep === visiblePlaces.length && result.mapContext?.end ? { id: 'next-schedule', name: '다음 일정', ...result.mapContext.end } : null)
  const guidePreviousPlace = guideStep > 0 ? visiblePlaces[guideStep - 1] : null
  const guideOrigin = guidePreviousPlace ?? liveLocation ?? startLocation
  const guideOriginLabel = guidePreviousPlace ? `${guideStep}번 출발` : '현재 위치'
  const guideTravel = courseResult?.course?.legs?.[guideStep]?.travel
  const guideTransportMode = guideTravel?.mode === 'walk'
    ? 'walk'
    : guideTravel?.mode === 'car'
      ? 'car'
      : guideTravel?.mode === 'transit'
        ? 'public_transit'
        : transportMode
  const mapFocusIndex = courseConfirmed && guidanceStarted
    ? (guideStep < visiblePlaces.length ? guideStep : null)
    : focusedStopIndex
  useEffect(() => {
    if (!guidanceStarted) {
      lastLiveLocation.current = null
      setLiveLocation(null)
      setLiveLocationStatus('idle')
      arrivalRef.current = { targetId: null, enteredAt: null, lastLocationAt: null }
      setArrivalSeconds(0)
      return undefined
    }
    if (!navigator.geolocation) {
      setLiveLocationStatus('unavailable')
      return undefined
    }
    setLiveLocationStatus('requesting')
    const watchId = navigator.geolocation.watchPosition((position) => {
      const nextLocation = { latitude: position.coords.latitude, longitude: position.coords.longitude, accuracy: position.coords.accuracy, updatedAt: Date.now() }
      const previous = lastLiveLocation.current
      const elapsed = Date.now() - (previous?.updatedAt ?? 0)
      if (!previous || distanceMetersBetween(previous, nextLocation) >= 10 || elapsed >= 5000) {
        lastLiveLocation.current = { ...nextLocation, updatedAt: Date.now() }
        setLiveLocation(nextLocation)
      }
      setLiveLocationStatus('ready')
    }, () => setLiveLocationStatus('unavailable'), { enableHighAccuracy: true, maximumAge: 5000, timeout: 12000 })
    return () => navigator.geolocation.clearWatch(watchId)
  }, [guidanceStarted])

  useEffect(() => {
    if (!guidanceStarted || !guideDestination || !liveLocation) return
    const distance = distanceMetersBetween(liveLocation, guideDestination)
    const current = arrivalRef.current
    if (distance <= ARRIVAL_RADIUS_METERS) {
      if (current.targetId !== guideDestination.id || !current.enteredAt) {
        arrivalRef.current = { targetId: guideDestination.id, enteredAt: Date.now(), lastLocationAt: liveLocation.updatedAt }
        setArrivalSeconds(0)
      } else {
        arrivalRef.current = { ...current, lastLocationAt: liveLocation.updatedAt }
      }
    } else if (current.targetId === guideDestination.id) {
      arrivalRef.current = { targetId: guideDestination.id, enteredAt: null, lastLocationAt: liveLocation.updatedAt }
      setArrivalSeconds(0)
    }
  }, [guidanceStarted, guideDestination?.id, guideDestination?.latitude, guideDestination?.longitude, liveLocation])

  useEffect(() => {
    if (!guidanceStarted || !guideDestination) return undefined
    const timer = window.setInterval(() => {
      const current = arrivalRef.current
      if (current.targetId !== guideDestination.id || !current.enteredAt) return
      // 오래된 GPS 좌표만 남아 있을 때 자동 도착 처리되는 것을 막는다.
      if (!current.lastLocationAt || Date.now() - current.lastLocationAt > 20000) {
        setArrivalSeconds(0)
        return
      }
      const elapsedSeconds = Math.floor((Date.now() - current.enteredAt) / 1000)
      setArrivalSeconds(Math.min(ARRIVAL_DWELL_SECONDS, elapsedSeconds))
      if (elapsedSeconds >= ARRIVAL_DWELL_SECONDS) {
        arrivalRef.current = { targetId: null, enteredAt: null, lastLocationAt: null }
        setArrivalSeconds(0)
        setGuideStep((currentStep) => Math.min(currentStep + 1, guideStopCount))
      }
    }, 1000)
    return () => window.clearInterval(timer)
  }, [guidanceStarted, guideDestination?.id, guideStopCount])

  useEffect(() => {
    if (!guidanceStarted || !guideDestination || !guideOrigin) {
      if (!guidanceStarted) setGuideRoute(null)
      return undefined
    }
    const previous = lastGuideRouteRequest.current
    const targetChanged = previous?.targetId !== guideDestination.id || previous?.transportMode !== guideTransportMode
    if (!targetChanged && distanceMetersBetween(previous, guideOrigin) < 40) return undefined
    let cancelled = false
    lastGuideRouteRequest.current = { ...guideOrigin, targetId: guideDestination.id, transportMode: guideTransportMode }
    if (targetChanged) setGuideRoute(null)
    requestRoutePreview({ startLatitude: guideOrigin.latitude, startLongitude: guideOrigin.longitude, endLatitude: guideDestination.latitude, endLongitude: guideDestination.longitude, transportMode: guideTransportMode })
      .then((route) => { if (!cancelled) setGuideRoute(route) })
      .catch(() => { /* 직전의 정상 경로를 유지하고 다음 위치 갱신 때 다시 시도한다. */ })
    return () => { cancelled = true }
  }, [guidanceStarted, guideDestination?.id, guideDestination?.latitude, guideDestination?.longitude, guideOrigin?.latitude, guideOrigin?.longitude, guideTransportMode])
  const returnToRegions = () => {
    calculationRequest.current += 1
    setPlaceMode(false)
    setCalculated(false)
    setCourseResult(null)
    setCourseConfirmed(false)
    setGuidanceStarted(false)
    setGuideStep(0)
    setFocusedStopIndex(null)
    setCalculationStatus('idle')
    setCalculationError('')
  }
  const resetCourseSelection = () => {
    calculationRequest.current += 1
    setCalculated(false)
    setCourseResult(null)
    setCourseConfirmed(false)
    setGuidanceStarted(false)
    setGuideStep(0)
    setFocusedStopIndex(null)
    setCalculationStatus('idle')
    setCalculationError('')
  }
  const confirmCourse = async () => {
    if (calculationStatus === 'loading') return
    setCalculationStatus('loading')
    setCalculationError('')
    try {
      // 확정 지도는 이전 화면의 캐시가 아니라 최신 혼합 이동 정책으로 다시
      // 계산한 코스를 사용한다. 백엔드의 구간 캐시는 재사용돼 응답은 빠르다.
      const course = await requestCourse({ startLocation, selectedPlaces, availableTimeMinutes, endLocation: result.mapContext?.end, transportMode, fresh: true })
      if (course.status !== 'FEASIBLE') {
        setCourseResult((current) => ({ ...current, course }))
        setCalculationStatus('warning')
        setCalculationError('최신 경로로 다시 계산하니 예정 시간보다 여유가 부족해요.')
        return
      }
      setCourseResult((current) => ({ ...current, course }))
      setFocusedStopIndex(null)
      setCourseConfirmed(true)
      setGuidanceStarted(false)
      setGuideStep(0)
      setCalculationStatus('ready')
    } catch (error) {
      setCalculationStatus('error')
      setCalculationError(error.message ?? '확정 경로를 다시 계산하지 못했어요.')
    }
  }
  const startGuidance = () => {
    setGuideStep(0)
    setGuidanceStarted(true)
  }

  return (
    <main className="results-page">
      <KakaoCourseMap mapContext={result.mapContext} selectedArea={selectedArea} areaRoute={selectedAreaRoute} walkingRouteLoading={isWalkingRouteLoading} selectedPlaces={visiblePlaces} focusedStopIndex={mapFocusIndex} course={calculated ? courseResult?.course : null} courseConfirmed={courseConfirmed} liveLocation={liveLocation} guideRoute={guideRoute} guidanceActive={guidanceStarted} guidanceStartLocation={guideOrigin} guidanceStartLabel={guideOriginLabel} />
      <aside className={`results-sidebar${placeMode ? ' is-place-mode' : ''}`}>
        {!placeMode && <header className="map-topbar">
          <>
            <button className="results-back results-back-icon" type="button" aria-label="이전 화면으로 돌아가기" onClick={onBack}><span aria-hidden="true">‹</span></button><span>KOALA 추천 경로</span>
          </>
        </header>}
        {!placeMode && <section className="map-transport-selector" aria-label="이동수단 선택">{transportOptions.map((option) => <button key={option.id} type="button" className={transportMode === option.id ? 'is-active' : ''} aria-pressed={transportMode === option.id} onClick={() => setTransportMode(option.id)}><i aria-hidden="true">{option.icon}</i>{option.label}</button>)}</section>}
        {rankingAreas.length > 0 && <section className={`map-ranking-sheet${sheetExpanded ? ' is-expanded' : ''}`}>
          <button className="sheet-handle" type="button" aria-label="추천 지역 목록 펼치기" aria-expanded={sheetExpanded} onPointerDown={handleSheetPointerDown} onPointerMove={handleSheetPointerMove} onPointerUp={handleSheetPointerUp} onClick={() => { if (didDrag.current) { didDrag.current = false; return } setSheetExpanded(!sheetExpanded) }}><i /></button>
          {placeMode ? <>
            <div className="place-picker-head"><button className="place-back-button" type="button" onClick={returnToRegions}><span aria-hidden="true">‹</span> 지역 목록</button><div><h2>{guidanceStarted ? '코스 안내 중이에요' : courseConfirmed ? '코스가 확정됐어요' : calculated ? '코스가 완성됐어요' : `${selectedArea?.name ?? '추천 지역'}에서 어디를 가볼까요?`}</h2><p>{guidanceStarted ? '도착하면 다음 장소를 안내해 드려요' : courseConfirmed ? '전체 동선을 마지막으로 확인해 보세요' : calculated ? '지도에서 전체 동선을 확인해 보세요' : ''}</p></div><span>{guidanceStarted ? `${Math.min(guideStep + 1, guideStopCount)}/${guideStopCount}` : `${selectedPlaces.length}곳`}</span></div>
            {calculated && courseConfirmed && guidanceStarted ? <div className="course-guide">
              {guideIsComplete ? <div className="guide-complete"><span>✓</span><b>오늘 코스를 모두 마쳤어요</b><p>수고했어요. 다음에도 코알라가 함께할게요.</p><button type="button" onClick={() => setGuideStep(0)}>처음부터 다시 보기</button></div> : <>
                <div className="guide-progress"><span>{arrivalSeconds > 0 ? `도착 확인 중 · ${ARRIVAL_DWELL_SECONDS - arrivalSeconds}초` : liveLocationStatus === 'ready' ? '현재 위치로 안내 중' : liveLocationStatus === 'unavailable' ? '기존 경로로 안내 중' : '현재 위치 확인 중'}</span><b>{guideStep + 1} / {guideStopCount}</b></div>
                <section className="guide-current" style={{ '--place-color': guidePlace ? courseStopColors[guideStep % courseStopColors.length] : '#ef6259' }}>
                  <small>{guidePlace ? '다음 장소' : '다음 일정'}</small>
                  <h3>{guidePlace?.name ?? '다음 일정 장소'}</h3>
                  <strong>{formatLegTransport(guideTravel)}</strong>
                  <p>{guidePlace ? `도착 후 약 ${formatMinutes(guidePlace.stayMinutes)} 머무르기` : '약속 장소까지 이동해요'}</p>
                </section>
                <div className="guide-stops">{visiblePlaces.map((place, index) => <button key={place.id} type="button" className={guideStep === index ? 'is-active' : ''} style={{ '--place-color': courseStopColors[index % courseStopColors.length] }} onClick={() => setGuideStep(index)}><i>{index + 1}</i><span>{place.name}</span></button>)}{result.mapContext?.end && <button type="button" className={guideStep === visiblePlaces.length ? 'is-active is-end' : 'is-end'} onClick={() => setGuideStep(visiblePlaces.length)}><i>✓</i><span>다음 일정</span></button>}</div>
                <button className="guide-next-button" type="button" onClick={() => setGuideStep((current) => Math.min(current + 1, guideStopCount))}>도착했어요 <span>→</span></button>
                <button className="guide-reset-button" type="button" onClick={resetCourseSelection}>코스 다시 설정하기</button>
              </>}
            </div> : calculated ? <div className="place-result">
              <div className="course-total"><b>{courseConfirmed ? '이 코스를 저장했어요' : courseResult?.course?.status === 'FEASIBLE' ? '시간 안에 방문 가능해요' : '예정 시간보다 여유가 부족해요'}</b><span>이동 {courseResult?.course?.total_travel_time_minutes ?? 0}분 · 체류 {courseResult?.course?.total_stay_time_minutes ?? 0}분</span></div>
              <button className="place-calc-button is-active course-reset-button" type="button" onClick={resetCourseSelection}>코스 다시 설정하기 <span>↺</span></button>
              <div className="course-timeline">
                <b>지도에 표시된 실제 이동 동선</b>
                {visiblePlaces.map((place, index) => <div className="course-timeline-stop" key={place.id} style={{ '--place-color': courseStopColors[index % courseStopColors.length] }}>
                  <div className="course-timeline-leg"><span>{index === 0 ? '현재 위치' : visiblePlaces[index - 1].name} → {place.name}</span><small>{formatLegTransport(courseResult?.course?.legs?.[index]?.travel)}</small></div>
                  <button className={`place-result-route${focusedStopIndex === index ? ' is-focused' : ''}`} type="button" onClick={() => setFocusedStopIndex(index)}><span>{index + 1}</span><strong>{place.name}</strong><small>{place.categoryLabel} · {place.stayMinutes}분 머무르기</small></button>
                </div>)}
                {result.mapContext?.end && courseResult?.course?.legs?.[visiblePlaces.length] && <div className="course-timeline-leg is-final"><span>{visiblePlaces.at(-1)?.name} → 다음 일정</span><small>{formatLegTransport(courseResult.course.legs[visiblePlaces.length].travel)}</small></div>}
              </div>
              <div className={`place-warning${courseResult?.course?.status === 'INFEASIBLE' || calculationError ? ' is-warning' : ''}`}>{calculationError || `총 ${courseResult?.course?.total_required_minutes ?? courseResult?.validation?.travel_time_precheck?.estimated_total_required_minutes ?? estimatedTravel + estimatedStay}분 · ${Math.abs(courseResult?.course?.remaining_time_minutes ?? 0)}분 ${courseResult?.course?.remaining_time_minutes >= 0 ? '여유' : '초과'}`}</div>
              {courseResult?.course?.status === 'FEASIBLE' && !courseConfirmed && <button className="place-calc-button is-active course-finalize-button" type="button" disabled={calculationStatus === 'loading'} onClick={confirmCourse}>{calculationStatus === 'loading' ? '최적 경로 확인 중…' : '이 코스로 확정하기'} {calculationStatus !== 'loading' && <span>→</span>}</button>}
              {courseConfirmed && <button className="place-calc-button is-active course-finalize-button" type="button" onClick={startGuidance}>안내 시작 <span>→</span></button>}
            </div> : <>
              {placeStatus === 'loading' && <p className="place-status">주변 실제 장소를 찾고 있어요…</p>}{placeStatus === 'error' && <p className="place-status is-error">{placeError || '장소를 불러오지 못했어요.'}</p>}{placeStatus === 'ready' && !places.length && <p className="place-status">추천할 장소가 아직 없어요.</p>}
              <div className={`place-picker-summary${calculationStatus === 'warning' ? ' is-warning' : ''}`}><b>예상 {estimatedTravel + estimatedStay}분</b><span>직선거리 기준 이동 {estimatedTravel}분 · 체류 {estimatedStay}분</span></div>
              {savedCoursesForArea.length > 0 && <button className="saved-course-button" type="button" onClick={() => { const saved = savedCoursesForArea[0]; setSelectedPlaces(saved.selectedPlaces); setCourseResult({ validation: saved.validation, course: saved.course }); setCalculated(true); setCalculationStatus('ready') }}>최근 계산한 코스 다시 보기</button>}
              <div className="ranking-scroll place-scroll">{places.map((place) => <button className={`place-card${selectedPlaces.some((item) => item.id === place.id) ? ' is-selected' : ''}`} type="button" key={place.id} onClick={() => togglePlace(place)}><span className="place-check">{selectedPlaces.some((item) => item.id === place.id) ? '✓' : ''}</span><span className="place-category-icon">{place.categoryIcon}</span><div><strong>{place.name}</strong><small>{place.categoryLabel} · {place.address ?? '주소 확인 중'}</small></div><em>{formatDistance(place.distanceMeters)}</em></button>)}{hasMorePlaces && <button className="place-more-button" type="button" onClick={handleLoadMore} disabled={placeStatus === 'more-loading'}>{placeStatus === 'more-loading' ? '장소를 더 찾는 중…' : '추천 장소 더 보기'}</button>}</div>
              {calculationStatus === 'warning' && <div className="place-warning is-warning">선택한 장소를 모두 방문하면 시간이 부족해요. 장소를 하나 이상 빼고 다시 코스를 짜주세요.</div>}
              {calculationError && <p className="place-status is-error">{calculationError}</p>}
              <button className={`place-calc-button${selectedPlaces.length && calculationStatus !== 'loading' ? ' is-active' : ''}`} type="button" disabled={!selectedPlaces.length || calculationStatus === 'loading'} onClick={handleCalculate}>{calculationStatus === 'loading' ? '코스 계산 중…' : calculationStatus === 'warning' ? '장소를 조정해 주세요' : '선택한 장소로 코스 짜기'} <span>→</span></button>
            </>}
          </> : <><div className="ranking-heading"><div><h2>{result.targetArea ? '요청한 지역 코스' : '지금 가기 좋은 지역'}</h2><p>지역을 누르면 실제 장소를 선택할 수 있어요</p></div><span>{rankingAreas.length}곳</span></div><div className="ranking-scroll">{rankingAreas.map((area, index) => <AreaCard key={`${area.name}-${index}`} area={{ ...area, rank: index + 1 }} selected={selectedIndex === index} onPreview={() => prepareAreaRoute(area)} onSelect={() => { prepareAreaRoute(area); setSelectedIndex(index); setSelectedPlaces([]); setCalculated(false); setCourseResult(null); setPlaceMode(true) }} />)}</div></>}
        </section>}
      </aside>
    </main>
  )
}

export default RecommendationPage
