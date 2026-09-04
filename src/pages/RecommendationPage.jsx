import { useEffect, useRef, useState } from 'react'
import { normalizeRecommendation } from '../utils/normalizeRecommendation'
import KakaoCourseMap from '../components/recommendation/KakaoCourseMap'
import { requestCourse, requestMorePlaces, requestPlaces, requestRoutePreview, validatePlaceSelection } from '../api/placesApi'

const categoryLabels = { food: '식당', cafe: '카페', walk: '산책', culture: '문화', entertainment: '즐길거리', shopping: '쇼핑', drink: '술집' }
const stayMinutesByCategory = { food: 60, cafe: 45, walk: 40, culture: 75, entertainment: 60, shopping: 45, drink: 60 }
const categoryIcons = { food: '🍽', cafe: '☕', walk: '🌿', culture: '🖼', entertainment: '🎟', shopping: '🛍', drink: '🍷' }

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

function AreaCard({ area, selected, onSelect, onPreview }) {
  return (
    <button className={`area-card${selected ? ' is-selected' : ''}`} type="button" onMouseEnter={onPreview} onFocus={onPreview} onTouchStart={onPreview} onClick={onSelect}>
      <div className="area-card-top"><span>{area.rank}위</span><strong>{area.name}</strong>{area.score && <em>{area.score}점</em>}</div>
      <div className="area-route">
        {area.fromStartMinutes > 0 && <span>여기까지 <b>{area.fromStartMinutes}분{area.fromStartTransport && ` · ${area.fromStartTransport}`}</b></span>}
        {area.toNextMinutes > 0 && <span>다음 일정 <b>{area.toNextMinutes}분{area.toNextTransport && ` · ${area.toNextTransport}`}</b></span>}
        {area.stayMinutes !== null && <span>머무르기 <b>{area.stayMinutes}분</b></span>}
      </div>
      <div className="area-metrics"><span>예상 혼잡도 <b>{area.congestion}</b></span>{area.arrivalTime && <span>도착 <b>{area.arrivalTime}</b></span>}</div>
    </button>
  )
}

function findSelectedPlace(optimizedPlace, selectedPlaces) {
  return selectedPlaces.find((place) => (
    Math.abs(Number(place.latitude) - Number(optimizedPlace.latitude)) < 0.000001
    && Math.abs(Number(place.longitude) - Number(optimizedPlace.longitude)) < 0.000001
  ))
}

function formatDistance(distanceMeters) {
  if (!distanceMeters) return '거리 정보 없음'
  return distanceMeters >= 1000 ? `${(distanceMeters / 1000).toFixed(1)}km` : `${distanceMeters}m`
}

function formatLegTransport(travel) {
  if (!travel) return '이동 경로 확인 중'
  if (travel.same_building) return '같은 건물 안'
  if (travel.mode === 'walk') return `도보 ${travel.duration_min ?? 0}분`
  const type = travel.route_type === 'SUBWAY' ? '지하철' : travel.route_type === 'BUS' ? '버스' : travel.route_type === 'BUS_AND_SUBWAY' ? '버스·지하철' : '대중교통'
  const transfer = travel.transfers > 0 ? ` · 환승 ${travel.transfers}회` : ''
  return `${type} ${travel.duration_min ?? 0}분${transfer}`
}

function RecommendationPage({ response, onBack }) {
  const result = normalizeRecommendation(response)
  const rankingAreas = [...(result.targetArea ? [result.targetArea] : []), ...result.otherAreas, ...result.extendedAreas]
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
  const [courseHistory, setCourseHistory] = useState([])
  const [focusedStopIndex, setFocusedStopIndex] = useState(null)
  const [sheetExpanded, setSheetExpanded] = useState(false)
  const [routeCache, setRouteCache] = useState({})
  const [routeLoading, setRouteLoading] = useState({})
  const dragStartY = useRef(null)
  const didDrag = useRef(false)
  const requestingRouteKeys = useRef(new Set())
  const selectedArea = rankingAreas[selectedIndex] ?? result.currentArea
  const startLocation = result.mapContext?.start ?? { latitude: selectedArea?.latitude ?? 37.5563, longitude: selectedArea?.longitude ?? 126.9236 }
  const routeCacheKey = selectedArea?.latitude != null && selectedArea?.longitude != null
    ? `${Number(selectedArea.latitude).toFixed(5)},${Number(selectedArea.longitude).toFixed(5)}`
    : null
  const selectedAreaRoute = (routeCacheKey && routeCache[routeCacheKey]) ?? selectedArea?.startRoute ?? null
  const isWalkingRouteLoading = Boolean(routeCacheKey && routeLoading[routeCacheKey] && !routeCache[routeCacheKey])
  const savedCoursesForArea = courseHistory.filter((item) => item.areaName === selectedArea?.name)

  const prepareAreaRoute = (area) => {
    if (!area || area.hasPreparedMapRoute || area.latitude == null || area.longitude == null) return
    const areaKey = `${Number(area.latitude).toFixed(5)},${Number(area.longitude).toFixed(5)}`
    if (routeCache[areaKey] || requestingRouteKeys.current.has(areaKey)) return
    requestingRouteKeys.current.add(areaKey)
    setRouteLoading((current) => ({ ...current, [areaKey]: true }))
    requestRoutePreview({ startLatitude: startLocation.latitude, startLongitude: startLocation.longitude, endLatitude: area.latitude, endLongitude: area.longitude })
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
  }, [routeCache, routeCacheKey, selectedArea?.hasPreparedMapRoute, selectedArea?.latitude, selectedArea?.longitude, startLocation.latitude, startLocation.longitude])

  useEffect(() => {
    // 전체 후보를 동시에 호출하지 않고, 사용자가 다음으로 볼 가능성이 높은 후보 하나만 준비한다.
    const nextArea = rankingAreas.find((area, index) => index !== selectedIndex && !area.hasPreparedMapRoute)
    if (!nextArea) return undefined
    const timer = window.setTimeout(() => prepareAreaRoute(nextArea), 900)
    return () => window.clearTimeout(timer)
  }, [selectedIndex, rankingAreas, routeCache])

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
    setCalculated(false)
    setCalculationError('')
    setCalculationStatus('idle')
    setCourseResult(null)
    setSelectedPlaces((current) => current.some((item) => item.id === place.id) ? current.filter((item) => item.id !== place.id) : [...current, place])
  }
  const estimatedStay = selectedPlaces.reduce((sum, place) => sum + place.stayMinutes, 0)
  const estimatedTravel = selectedPlaces.reduce((sum, place, index) => sum + straightDistanceMinutes(index === 0 ? selectedArea : selectedPlaces[index - 1], place), 0)
  const availableTimeMinutes = Math.max(1, selectedArea?.stayMinutes ?? 120)

  const handleCalculate = async () => {
    if (!selectedPlaces.length) return
    setCalculationStatus('loading')
    setCalculationError('')
    try {
      const validation = await validatePlaceSelection({ startLatitude: startLocation.latitude, startLongitude: startLocation.longitude, selectedPlaces, availableTimeMinutes })
      setCourseResult({ validation, course: null })
      if (validation.travel_time_precheck?.warning) {
        setCalculationStatus('warning')
        return
      }
      const course = await requestCourse({ startLocation, selectedPlaces, availableTimeMinutes, endLocation: result.mapContext?.end, transportMode: 'auto' })
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
      setFocusedStopIndex(null)
      setCalculationStatus('ready')
    } catch (error) {
      setCalculationStatus('error')
      setCalculationError(error.message)
    }
  }

  const orderedPlaces = (courseResult?.course?.optimized_places ?? [])
    .map((place) => findSelectedPlace(place, selectedPlaces))
    .filter(Boolean)
  const visiblePlaces = calculated && orderedPlaces.length ? orderedPlaces : selectedPlaces

  return (
    <main className="results-page">
      <KakaoCourseMap mapContext={result.mapContext} selectedArea={selectedArea} areaRoute={selectedAreaRoute} walkingRouteLoading={isWalkingRouteLoading} selectedPlaces={visiblePlaces} focusedStopIndex={focusedStopIndex} course={calculated ? courseResult?.course : null} />
      <aside className="results-sidebar">
        <header className="map-topbar"><button className="results-back" type="button" aria-label="처음으로 돌아가기" onClick={onBack}>‹</button><span>KOALA 추천 경로</span></header>
        <section className="map-route-label"><b>{selectedArea?.name ?? '추천 지역'}</b><span>{selectedArea?.fromStartMinutes ? `약 ${selectedArea.fromStartMinutes}분` : '현재 위치 근처'}</span></section>
        {rankingAreas.length > 0 && <section className={`map-ranking-sheet${sheetExpanded ? ' is-expanded' : ''}`}>
          <button className="sheet-handle" type="button" aria-label="추천 지역 목록 펼치기" aria-expanded={sheetExpanded} onPointerDown={handleSheetPointerDown} onPointerMove={handleSheetPointerMove} onPointerUp={handleSheetPointerUp} onClick={() => { if (didDrag.current) { didDrag.current = false; return } setSheetExpanded(!sheetExpanded) }}><i /></button>
          {placeMode ? <>
            <div className="place-picker-head"><button className="place-back-button" type="button" onClick={() => { setPlaceMode(false); setCalculated(false); setCourseResult(null) }}><span aria-hidden="true">‹</span> 지역 목록</button><div><h2>{calculated ? '코스가 완성됐어요' : `${selectedArea?.name ?? '추천 지역'}에서 어디를 가볼까요?`}</h2><p>{calculated ? '지도에서 전체 동선을 확인해 보세요' : ''}</p></div><span>{selectedPlaces.length}곳</span></div>
            {calculated ? <div className="place-result">
              <div className="course-total"><b>{courseResult?.course?.status === 'FEASIBLE' ? '시간 안에 방문 가능해요' : '예정 시간보다 여유가 부족해요'}</b><span>이동 {courseResult?.course?.total_travel_time_minutes ?? 0}분 · 체류 {courseResult?.course?.total_stay_time_minutes ?? 0}분</span></div>
              <div className="course-timeline">
                <b>지도에 표시된 실제 이동 동선</b>
                {visiblePlaces.map((place, index) => <div className="course-timeline-stop" key={place.id}>
                  <div className="course-timeline-leg"><span>{index === 0 ? '현재 위치' : visiblePlaces[index - 1].name} → {place.name}</span><small>{formatLegTransport(courseResult?.course?.legs?.[index]?.travel)}</small></div>
                  <button className={`place-result-route${focusedStopIndex === index ? ' is-focused' : ''}`} type="button" onClick={() => setFocusedStopIndex(index)}><span>{index + 1}</span><strong>{place.name}</strong><small>{place.categoryLabel} · {place.stayMinutes}분 머무르기</small></button>
                </div>)}
                {result.mapContext?.end && courseResult?.course?.legs?.[visiblePlaces.length] && <div className="course-timeline-leg is-final"><span>{visiblePlaces.at(-1)?.name} → 다음 일정</span><small>{formatLegTransport(courseResult.course.legs[visiblePlaces.length].travel)}</small></div>}
              </div>
              <div className={`place-warning${courseResult?.course?.status === 'INFEASIBLE' || calculationError ? ' is-warning' : ''}`}>{calculationError || `총 ${courseResult?.course?.total_required_minutes ?? courseResult?.validation?.travel_time_precheck?.estimated_total_required_minutes ?? estimatedTravel + estimatedStay}분 · ${Math.abs(courseResult?.course?.remaining_time_minutes ?? 0)}분 ${courseResult?.course?.remaining_time_minutes >= 0 ? '여유' : '초과'}`}</div>
              <button className="place-calc-button is-active" type="button" onClick={() => { setCalculated(false); setCourseResult(null); setSelectedPlaces([]); setCalculationStatus('idle'); setCalculationError('') }}>장소 다시 선택하기</button>
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
