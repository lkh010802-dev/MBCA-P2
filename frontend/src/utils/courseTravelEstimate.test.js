import assert from "node:assert/strict";
import test from "node:test";
import {
  buildCourseSegments,
  courseSegmentCacheKey,
  estimateFallbackRoute,
  routeDurationMinutes,
} from "./courseTravelEstimate.js";

const start = { latitude: 37.48, longitude: 126.93 };
const first = { latitude: 37.49, longitude: 126.94 };
const end = { latitude: 37.5, longitude: 126.95 };

test("현재 위치부터 장소와 다음 일정까지 순서대로 구간을 만든다", () => {
  assert.deepEqual(buildCourseSegments(start, [first], end), [
    { from: start, to: first },
    { from: first, to: end },
  ]);
});

test("좌표가 없으면 0분 대신 계산 불가를 반환한다", () => {
  assert.equal(buildCourseSegments(start, [{ name: "좌표 없음" }], end), null);
  assert.equal(routeDurationMinutes(null), null);
  assert.equal(routeDurationMinutes({ duration_min: 0 }), 0);
});

test("교통수단이 다르면 별도 캐시 키를 사용한다", () => {
  const segment = { from: start, to: first };
  assert.notEqual(
    courseSegmentCacheKey(segment, "walk"),
    courseSegmentCacheKey(segment, "public_transit"),
  );
});

test("외부 경로 실패 시 0분이 아닌 보수적 예상시간을 만든다", () => {
  const fallback = estimateFallbackRoute({ from: start, to: first }, "public_transit");
  assert.equal(fallback.status, "estimated");
  assert.equal(fallback.source, "distance_fallback");
  assert.ok(fallback.durationMinutes > 0);
  assert.equal(fallback.route.calculation_status, "estimated");
});

test("좌표가 없으면 예상시간을 만들지 않는다", () => {
  assert.equal(
    estimateFallbackRoute({ from: start, to: { name: "좌표 없음" } }, "walk"),
    null,
  );
});
