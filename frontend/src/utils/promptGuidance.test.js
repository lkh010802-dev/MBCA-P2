import test from "node:test";
import assert from "node:assert/strict";
import {
  PROMPT_EXAMPLES,
  RECOMMENDATION_GUIDES,
} from "./promptGuidance.js";

test("질문 도움말은 서로 다른 상황의 예시 세 개를 제공한다", () => {
  assert.equal(PROMPT_EXAMPLES.length, 3);
  assert.deepEqual(
    PROMPT_EXAMPLES.map((example) => example.id),
    ["available-time", "activity-combination", "next-appointment"],
  );
});

test("예시에는 추천에 필요한 지역·시간·활동 단서가 포함된다", () => {
  const combined = PROMPT_EXAMPLES.map((example) => example.text).join(" ");
  assert.match(combined, /신림역|현재 위치|잠실/);
  assert.match(combined, /3시간|8시/);
  assert.match(combined, /카페|산책|전시/);
});

test("도움말은 자동 코스와 색다른 추천의 차이를 설명한다", () => {
  assert.deepEqual(
    RECOMMENDATION_GUIDES.map(({ id }) => id),
    ["auto-course", "blind-course", "random-course", "daily-quest"],
  );
  RECOMMENDATION_GUIDES.forEach((guide) => {
    assert.ok(guide.summary.length > 0);
    assert.ok(guide.description.length > 0);
  });
});
