const congestionLabels = { '여유': '여유', '보통': '보통', '약간 붐빔': '약간 붐빔', '붐빔': '붐빔' }

function formatTime(value) {
  if (!value) return null
  return new Intl.DateTimeFormat('ko-KR', { hour: 'numeric', minute: '2-digit', hour12: false }).format(new Date(value))
}

function formatTransport(transport) {
  if (!transport || transport.mode === 'stay') return null
  if (transport.mode === 'walk') return '도보'
  const typeLabels = { BUS: '버스', SUBWAY: '지하철', BUS_AND_SUBWAY: '버스·지하철' }
  const label = typeLabels[transport.route_type] ?? '대중교통'
  return transport.transfers > 0 ? `${label} · 환승 ${transport.transfers}회` : label
}

export function normalizeCandidate(candidate, rank) {
  if (!candidate) return null
  const travelMinutes = (candidate.start_to_candidate_travel_minutes ?? 0) + (candidate.candidate_to_end_travel_minutes ?? 0)
  return {
    rank,
    name: candidate.AREA_NM ?? '추천 지역',
    score: typeof candidate.final_score === 'number' ? candidate.final_score.toFixed(1) : null,
    activityScore: candidate.activity_match_score ?? null,
    congestion: congestionLabels[candidate.forecast_congestion?.FCST_CONGEST_LVL] ?? '알 수 없음',
    travelMinutes,
    fromStartMinutes: candidate.start_to_candidate_travel_minutes ?? 0,
    toNextMinutes: candidate.candidate_to_end_travel_minutes ?? 0,
    fromStartTransport: formatTransport(candidate.start_to_candidate_transport),
    toNextTransport: formatTransport(candidate.candidate_to_end_transport),
    stayMinutes: candidate.available_stay_minutes ?? null,
    arrivalTime: formatTime(candidate.arrival_datetime),
    latitude: candidate.latitude ?? null,
    longitude: candidate.longitude ?? null,
    startRoute: candidate.map_preview_route ?? candidate.start_to_candidate_route ?? null,
    hasPreparedMapRoute: Boolean(candidate.map_preview_route),
  }
}

export function normalizeRecommendation(response) {
  return {
    message: (response.recommendation_message ?? '지금 가기 좋은 곳을 찾았어요.')
      .split('\n\n')[0]
      .replaceAll('**', ''),
    mapContext: response.map_context ?? null,
    targetArea: normalizeCandidate(response.target_area, 1),
    currentArea: normalizeCandidate(response.current_area, null),
    otherAreas: (response.other_areas ?? []).map((item, index) => normalizeCandidate(item, index + 1)),
    extendedAreas: (response.extended_areas ?? []).map((item, index) => normalizeCandidate(item, index + 1)),
  }
}
