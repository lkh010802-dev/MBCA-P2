export function normalizedActivitySequence(sequence) {
  if (!Array.isArray(sequence)) return [];
  return sequence.map((item) => String(item ?? "").trim()).filter(Boolean);
}

export function hasOrderedActivitySequence(sequence) {
  return normalizedActivitySequence(sequence).length >= 2;
}

const ACTIVITY_PATTERNS = {
  food: /(밥|식사|먹(?:고|기|으)|맛집|음식|점심|저녁|아침)/,
  cafe: /(카페|커피|디저트|차\s*마시)/,
  culture: /(전시|미술관|박물관|공연|연극|문화|갤러리)/,
  walk: /(산책|걷|걸(?:을|으)|공원)/,
  entertainment: /(놀(?:고|기)|오락|게임|영화|즐길)/,
  shopping: /(쇼핑|구경|시장|백화점)/,
  drink: /(술|맥주|와인|한잔|포차|바\b)/,
};

export function inferActivitySequence(message) {
  const text = String(message ?? "");
  return Object.entries(ACTIVITY_PATTERNS)
    .map(([category, pattern]) => ({ category, index: text.search(pattern) }))
    .filter(({ index }) => index >= 0)
    .sort((left, right) => left.index - right.index)
    .map(({ category }) => category);
}

export function resolveActivitySequence(message, backendSequence) {
  const inferred = inferActivitySequence(message);
  return inferred.length >= 2
    ? inferred
    : normalizedActivitySequence(backendSequence);
}

// 사용자가 말한 활동 순서를 우선하고, 언급되지 않은 장소는 뒤에 유지한다.
export function orderPlacesByActivitySequence(places, sequence) {
  const orderedCategories = normalizedActivitySequence(sequence);
  if (orderedCategories.length < 2) return [...places];
  const rank = new Map(
    orderedCategories.map((category, index) => [category, index]),
  );
  return places
    .map((place, index) => ({ place, index }))
    .sort((left, right) => {
      const leftRank = rank.get(left.place?.category) ?? Number.MAX_SAFE_INTEGER;
      const rightRank = rank.get(right.place?.category) ?? Number.MAX_SAFE_INTEGER;
      return leftRank - rightRank || left.index - right.index;
    })
    .map(({ place }) => place);
}
