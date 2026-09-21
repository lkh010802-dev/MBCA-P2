import assert from "node:assert/strict";
import test from "node:test";
import {
  addAppointmentTime,
  needsAppointmentTimeClarification,
  suggestedAppointmentHours,
} from "./timeIntent.js";

test("모호한 저녁 약속만 시간 확인이 필요하다", () => {
  assert.equal(
    needsAppointmentTimeClarification("오늘 저녁에 신도림에서 약속이 있어"),
    true,
  );
  assert.equal(
    needsAppointmentTimeClarification("오늘 저녁 7시에 신도림에서 약속이 있어"),
    false,
  );
});

test("시간대에 맞는 빠른 선택지를 제공한다", () => {
  assert.deepEqual(suggestedAppointmentHours("저녁 약속"), [18, 19, 20]);
  assert.deepEqual(suggestedAppointmentHours("아침 미팅"), [8, 9, 10]);
});

test("선택한 약속 시간을 원문에 명시적으로 덧붙인다", () => {
  assert.match(addAppointmentTime("저녁 약속 전에 카페", 19), /오후 7시/);
});
