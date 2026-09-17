import { test } from 'node:test'
import assert from 'node:assert/strict'
import { courseWarnings } from './contractAudit.js'
import { normalizeRecommendation, normalizeCandidate } from './normalizeRecommendation.js'

test('backend context supplies start and final destination without map_context', () => {
  const context = { start_location: { latitude: 37.49, longitude: 126.89 }, end_location: { latitude: 37.48, longitude: 126.93 }, available_time_minutes: 120 }
  const result = normalizeRecommendation({ recommendation_context: context })
  assert.deepEqual(result.mapContext.start, context.start_location)
  assert.deepEqual(result.mapContext.end, context.end_location)
  assert.equal(result.mapContext.available_time_minutes, 120)
})
test('car does not appear as transit', () => {
  assert.equal(normalizeCandidate({ start_to_candidate_transport: { mode: 'car' } }, 1).fromStartTransport, '자동차')
})
const request = { available_time_minutes: 120, transport_mode: 'public_transit', selected_places: [{}, {}] }
const course = { total_required_minutes: 107, total_travel_time_minutes: 2, total_stay_time_minutes: 105, remaining_time_minutes: 13, available_time_minutes: 120, status: 'FEASIBLE', optimized_places: [{}, {}], legs: [{ travel_time_minutes: 1, travel: { mode: 'walk' } }, { travel_time_minutes: 1, travel: { mode: 'walk' } }] }
test('107 of 120 minutes is feasible, transit may include walk', () => assert.deepEqual(courseWarnings(course, request), []))
test('contradictory status is rejected', () => assert.ok(courseWarnings({ ...course, status: 'INFEASIBLE' }, request).includes('status_mismatch')))
test('changed time budget is rejected', () => assert.ok(courseWarnings(course, { ...request, available_time_minutes: 360 }).includes('budget_mismatch')))
test('wrong transport mode is rejected', () => assert.ok(courseWarnings({ ...course, legs: [{ travel_time_minutes: 1, travel: { mode: 'car' } }, course.legs[1]] }, request).includes('transport_mismatch')))
test('missing optional leg mode is not treated as a contradiction', () => assert.deepEqual(courseWarnings({ ...course, legs: [{ travel_time_minutes: 1 }, { travel_time_minutes: 1 }] }, request), []))
test('final destination requires one additional timed leg', () => {
  const withEnd = { ...request, end_location: { latitude: 37.48, longitude: 126.93 } }
  assert.ok(courseWarnings(course, withEnd).includes('leg_count_mismatch'))
})
test('missing leg time is calculation unavailable, not zero', () => {
  const warnings = courseWarnings({ ...course, legs: [{ travel_time_minutes: 2 }, { travel_time_minutes: null }] }, request)
  assert.ok(warnings.includes('missing_leg_time'))
})
test('a genuine zero-minute same-point leg remains a numeric value', () => {
  const onePlaceRequest = { ...request, selected_places: [{}] }
  const zeroCourse = { ...course, total_required_minutes: 105, total_travel_time_minutes: 0, remaining_time_minutes: 15, optimized_places: [{}], legs: [{ travel_time_minutes: 0 }] }
  assert.deepEqual(courseWarnings(zeroCourse, onePlaceRequest), [])
})
