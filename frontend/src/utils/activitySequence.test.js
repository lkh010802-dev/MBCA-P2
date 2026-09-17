import test from "node:test";
import assert from "node:assert/strict";

import {
  hasOrderedActivitySequence,
  orderPlacesByActivitySequence,
  resolveActivitySequence,
} from "./activitySequence.js";

test("explicit activity sequence orders selected places", () => {
  const places = [
    { id: "exhibition", category: "culture" },
    { id: "coffee", category: "cafe" },
  ];

  assert.deepEqual(
    orderPlacesByActivitySequence(places, ["cafe", "culture"]).map(
      (place) => place.id,
    ),
    ["coffee", "exhibition"],
  );
});

test("unmentioned categories remain stable after requested activities", () => {
  const places = [
    { id: "walk", category: "walk" },
    { id: "coffee", category: "cafe" },
    { id: "meal", category: "food" },
  ];

  assert.deepEqual(
    orderPlacesByActivitySequence(places, ["food", "cafe"]).map(
      (place) => place.id,
    ),
    ["meal", "coffee", "walk"],
  );
});

test("single activity keeps optimization available", () => {
  assert.equal(hasOrderedActivitySequence(["cafe"]), false);
  assert.equal(hasOrderedActivitySequence(["cafe", "culture"]), true);
});

test("user wording corrects a reversed backend sequence", () => {
  assert.deepEqual(
    resolveActivitySequence(
      "친구랑 카페 갔다가 전시 보고 싶어",
      ["culture", "cafe"],
    ),
    ["cafe", "culture"],
  );
});

test("meal then cafe follows the wording order", () => {
  assert.deepEqual(
    resolveActivitySequence("밥 먹고 카페에서 쉬고 싶어", ["cafe", "food"]),
    ["food", "cafe"],
  );
});
