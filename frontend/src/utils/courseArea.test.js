import assert from "node:assert/strict";
import test from "node:test";

import { resolveCourseArea } from "./courseArea.js";

test("completed automatic course keeps the area used for calculation", () => {
  const sillim = { name: "신림역", latitude: 37.484, longitude: 126.929 };
  const resolved = resolveCourseArea({
    pinnedArea: sillim,
    autoCourseMode: false,
    targetArea: sillim,
    currentArea: sillim,
    rankingAreas: [{ name: "대림역" }],
    selectedIndex: 0,
  });
  assert.equal(resolved, sillim);
});

test("ordinary area selection still follows the selected ranking", () => {
  const areas = [{ name: "신림역" }, { name: "보라매공원" }];
  assert.equal(
    resolveCourseArea({
      pinnedArea: null,
      autoCourseMode: false,
      targetArea: null,
      currentArea: { name: "대림역" },
      rankingAreas: areas,
      selectedIndex: 1,
    }),
    areas[1],
  );
});
