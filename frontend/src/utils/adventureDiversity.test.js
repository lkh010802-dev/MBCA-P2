import assert from "node:assert/strict";
import test from "node:test";
import {
  adventureSignature,
  rememberAdventure,
} from "./adventureDiversity.js";

test("같은 두 장소는 순서가 달라도 같은 코스로 본다", () => {
  assert.equal(
    adventureSignature({ places: [{ name: "카페" }, { name: "전시" }] }),
    adventureSignature({ places: [{ name: "전시" }, { name: "카페" }] }),
  );
});

test("최근 추천은 중복 없이 최신순으로 보관한다", () => {
  assert.deepEqual(rememberAdventure(["old", "same"], "same"), [
    "same",
    "old",
  ]);
});
