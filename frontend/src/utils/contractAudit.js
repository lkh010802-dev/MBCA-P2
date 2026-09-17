export function courseWarnings(course, request) {
  const warnings = []
  const fields = ['total_required_minutes', 'total_travel_time_minutes', 'total_stay_time_minutes', 'remaining_time_minutes', 'available_time_minutes']
  if (fields.some((field) => !Number.isFinite(course[field]))) return ['missing_course_time']
  if (course.total_required_minutes !== course.total_travel_time_minutes + course.total_stay_time_minutes) warnings.push('total_mismatch')
  if (course.remaining_time_minutes !== course.available_time_minutes - course.total_required_minutes) warnings.push('remaining_mismatch')
  if (course.available_time_minutes !== request.available_time_minutes) warnings.push('budget_mismatch')
  if (course.status !== (course.remaining_time_minutes >= 0 ? 'FEASIBLE' : 'INFEASIBLE')) warnings.push('status_mismatch')
  const expectedLegCount = (request.selected_places?.length ?? 0) + (request.end_location ? 1 : 0)
  if ((course.legs?.length ?? 0) !== expectedLegCount) warnings.push('leg_count_mismatch')
  const legMinutes = (course.legs ?? []).map((leg) => leg.travel_time_minutes)
  if (legMinutes.some((minutes) => !Number.isFinite(minutes) || minutes < 0)) warnings.push('missing_leg_time')
  else if (legMinutes.reduce((sum, minutes) => sum + minutes, 0) !== course.total_travel_time_minutes) warnings.push('leg_total_mismatch')
  // Transit legitimately includes walking access legs; driving can include nearby walks.
  for (const leg of course.legs ?? []) {
    const mode = leg.travel?.mode
    // Some route providers return only travel_time_minutes. An omitted mode is
    // unknown, not a contradiction; validate only when the backend supplied it.
    if (mode && ((request.transport_mode === 'walk' && mode !== 'walk') || (request.transport_mode === 'car' && !['car', 'walk'].includes(mode)) || (request.transport_mode === 'public_transit' && !['transit', 'public_transit', 'walk'].includes(mode)))) warnings.push('transport_mismatch')
  }
  if (course.optimized_places?.length !== request.selected_places?.length) warnings.push('place_count_mismatch')
  return [...new Set(warnings)]
}
