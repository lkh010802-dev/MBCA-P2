import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { normalizeRecommendation } from "../utils/normalizeRecommendation";
import {
  availabilityLabel,
  formatCalculatedMinutes,
  formatClock,
  formatDistance,
  formatMinutes,
} from "../utils/recommendationFormatting";
import {
  eventUrgency,
  formatEventPeriod,
  placeSourceKind,
  recommendationReason,
} from "../utils/recommendationPresentation";
import {
  categoryFallbackImages,
  categoryIcons,
  categoryLabels,
  courseStopColors,
  stayMinutesByCategory,
  timeHourOptions,
  timeMinuteOptions,
  transportOptions,
} from "../config/recommendationDisplay";
import { readSession, writeSession } from "../utils/sessionStore";
import {
  hasOrderedActivitySequence,
  orderPlacesByActivitySequence,
  resolveActivitySequence,
} from "../utils/activitySequence";
import { resolveCourseArea } from "../utils/courseArea";
import KakaoCourseMap from "../components/recommendation/KakaoCourseMap";
import AdventurePanel from "../components/recommendation/AdventurePanel";
import TimeWheelColumn from "../components/common/TimeWheelColumn";
import {
  requestCourse,
  requestMorePlaces,
  requestPlacePhotos,
  requestPlaces,
  requestRoutePreview,
  validatePlaceSelection,
} from "../api/placesApi";
import {
  addFavoritePlace,
  excludePlace,
  getExcludedPlaces,
  getFavoritePlaces,
  recordInteraction,
  removeFavoritePlace,
  saveCourse,
} from "../api/accountApi";
import { audit } from "../utils/auditTrace";
import { useCourseTravelEstimate } from "../hooks/useCourseTravelEstimate";
import iconBack from "../assets/images/icon-back.png";
import koalaSearching from "../assets/images/koala-searching.png";
import koalaComplete from "../assets/images/koala-complete.png";
import placeCulture from "../assets/images/place-culture.png";
import placePopup from "../assets/images/place-popup.png";

const ARRIVAL_RADIUS_METERS = 30;
const ARRIVAL_DWELL_SECONDS = 60;
const MAX_ACCEPTED_GPS_ACCURACY_METERS = 80;
const MAX_ARRIVAL_GPS_ACCURACY_METERS = 35;

const QUEST_COPY = {
  food: "이곳의 대표 메뉴를 하나 골라보세요.",
  cafe: "평소 고르지 않던 음료나 디저트를 하나 골라보세요.",
  walk: "마음에 드는 풍경을 하나 찾아 잠깐 바라보세요.",
  culture: "가장 기억에 남는 작품이나 공간을 하나 골라보세요.",
  entertainment: "처음 해보는 활동을 하나 시도해보세요.",
  shopping: "1만 원 이하의 재미있는 물건을 하나 찾아보세요.",
  drink: "처음 보는 메뉴를 하나 골라 천천히 즐겨보세요.",
};

function questForPlace(place, fallback, index) {
  if (index === 0 && fallback) return fallback;
  return QUEST_COPY[place.category] ?? "이 장소에서 평소와 다른 선택을 하나 해보세요.";
}

function placeIdentity(place) {
  const sourceId = place.source_id ?? place.sourceId;
  if (sourceId) return `${place.source ?? "place"}:${sourceId}`;
  const name = String(place.name ?? "")
    .toLowerCase()
    .replace(/\s+/g, "");
  const latitude = Number(place.latitude).toFixed(4);
  const longitude = Number(place.longitude).toFixed(4);
  return `${name}:${latitude}:${longitude}`;
}

function buildAutoCourseCandidates(
  places,
  preferredActivities = [],
  hasPersonalPreferences = false,
  requestedPlaceCount = 3,
  variationIndex = 0,
  recentPlaceIds = [],
) {
  const unique = [
    ...new Map(places.map((place) => [placeIdentity(place), place])).values(),
  ];
  const count = Math.min(Math.max(2, requestedPlaceCount), unique.length);
  if (count < 2) return [];
  const recentSet = new Set(recentPlaceIds);
  const recentRank = (place) => (recentSet.has(placeIdentity(place)) ? 1 : 0);
  const categoryRank = (place, order) => {
    const index = order.indexOf(place.category);
    return index < 0 ? order.length : index;
  };
  let foodFirst = [...unique].sort(
    (left, right) =>
      categoryRank(left, [
        "food",
        "cafe",
        "walk",
        "culture",
        "entertainment",
        "shopping",
        "drink",
      ]) -
        categoryRank(right, [
          "food",
          "cafe",
          "walk",
          "culture",
          "entertainment",
          "shopping",
          "drink",
      ]) ||
      recentRank(left) - recentRank(right) ||
      left.distanceMeters - right.distanceMeters,
  );
  let cultureFirst = [...unique].sort((left, right) => {
    const leftEvent = left.sourceKind === "general" ? 0 : 1;
    const rightEvent = right.sourceKind === "general" ? 0 : 1;
    return (
      rightEvent - leftEvent ||
      categoryRank(left, [
        "culture",
        "entertainment",
        "walk",
        "cafe",
        "food",
        "shopping",
        "drink",
      ]) -
        categoryRank(right, [
          "culture",
          "entertainment",
          "walk",
          "cafe",
          "food",
          "shopping",
          "drink",
        ]) ||
      recentRank(left) - recentRank(right) ||
      left.distanceMeters - right.distanceMeters
    );
  });
  let balanced = [...unique].sort((left, right) => {
    const leftPreferred = preferredActivities.includes(left.category) ? 1 : 0;
    const rightPreferred = preferredActivities.includes(right.category) ? 1 : 0;
    return (
      rightPreferred - leftPreferred ||
      categoryRank(left, [
        "food",
        "culture",
        "cafe",
        "walk",
        "entertainment",
        "shopping",
        "drink",
      ]) -
        categoryRank(right, [
          "food",
          "culture",
          "cafe",
          "walk",
          "entertainment",
          "shopping",
          "drink",
        ]) ||
      recentRank(left) - recentRank(right) ||
      left.distanceMeters - right.distanceMeters
    );
  });
  // 점수가 높은 후보군은 유지하되 재추천할 때마다 그 안의 시작점을 바꾼다.
  // 완전 무작위로 먼 장소가 올라오는 문제 없이 같은 코스만 반복되는 현상을 줄인다.
  const rotateTopPool = (ordered, offset) => {
    const poolSize = Math.min(ordered.length, Math.max(4, count + 2));
    if (poolSize < 2) return ordered;
    const pool = ordered.slice(0, poolSize);
    const shift = Math.abs(Number(offset) || 0) % poolSize;
    return [
      ...pool.slice(shift),
      ...pool.slice(0, shift),
      ...ordered.slice(poolSize),
    ];
  };
  foodFirst = rotateTopPool(foodFirst, variationIndex);
  cultureFirst = rotateTopPool(cultureFirst, variationIndex * 2 + 1);
  balanced = rotateTopPool(balanced, variationIndex * 3 + 2);
  const selectVaried = (ordered, offset = 0, desiredCount = count) => {
    const rotated = [...ordered.slice(offset), ...ordered.slice(0, offset)];
    const selected = [];
    const selectedCategories = new Set();
    for (const place of rotated) {
      if (!selectedCategories.has(place.category)) {
        selected.push(place);
        selectedCategories.add(place.category);
      }
      if (selected.length === desiredCount) break;
    }
    for (const place of rotated) {
      if (selected.length === desiredCount) break;
      if (!selected.includes(place)) selected.push(place);
    }
    return selected;
  };
  const alternateCount =
    unique.length <= count + 1 ? Math.max(2, count - 1) : count;
  const hasLimitedEvent = cultureFirst.some(
    (place) => place.sourceKind !== "general",
  );
  const prioritizeCategories = (ordered, preferred) => [
    ...ordered.filter((place) => preferred.includes(place.category)),
    ...ordered.filter((place) => !preferred.includes(place.category)),
  ];
  const usedAcrossCourses = new Set();
  const selectLowOverlap = (ordered, desiredCount) => {
    const selected = [];
    for (const place of ordered) {
      if (!usedAcrossCourses.has(placeIdentity(place))) selected.push(place);
      if (selected.length === desiredCount) break;
    }
    for (const place of ordered) {
      if (selected.length === desiredCount) break;
      if (!selected.includes(place)) selected.push(place);
    }
    selected.forEach((place) => usedAcrossCourses.add(placeIdentity(place)));
    return selected;
  };
  const selectLowOverlapByCategory = (ordered, categories, desiredCount) => {
    const selected = [];
    for (const category of categories) {
      const place = ordered.find(
        (item) =>
          item.category === category &&
          !usedAcrossCourses.has(placeIdentity(item)) &&
          !selected.includes(item),
      );
      if (place) selected.push(place);
      if (selected.length === desiredCount) break;
    }
    for (const place of ordered) {
      if (selected.length === desiredCount) break;
      if (
        !usedAcrossCourses.has(placeIdentity(place)) &&
        !selected.includes(place)
      )
        selected.push(place);
    }
    for (const place of ordered) {
      if (selected.length === desiredCount) break;
      if (!selected.includes(place)) selected.push(place);
    }
    selected.forEach((place) => usedAcrossCourses.add(placeIdentity(place)));
    return selected;
  };
  const candidates = [
    // 식사 코스는 "밥만 여러 곳"이 아니라 식사 뒤 카페로 이어지는 흐름을 우선한다.
    {
      id: "food",
      icon: "🍽",
      title: "배가 고프다면",
      description: "식사 뒤 카페에서 쉬는 자연스러운 동선이에요",
      places: selectLowOverlapByCategory(
        foodFirst,
        ["food", "cafe", "walk", "culture", "drink"],
        count,
      ),
    },
    // 문화·균형 코스에도 서로 다른 카페를 우선 배치한다. 사용자는 밥을 먹은 뒤
    // 쉬거나, 전시 뒤 커피를 마시는 선택지를 한 번에 비교할 수 있다.
    {
      id: "culture",
      icon: "🎟",
      title: hasLimitedEvent ? "지금만 볼 수 있다면" : "문화로 채우고 싶다면",
      description: hasLimitedEvent
        ? "팝업을 보고 다른 카페에서 쉬어가요"
        : "전시를 보고 카페에서 쉬어가요",
      places: selectLowOverlapByCategory(
        cultureFirst,
        ["culture", "cafe", "entertainment", "walk", "food"],
        alternateCount,
      ),
    },
    {
      id: "balance",
      icon: hasPersonalPreferences ? "💙" : "✨",
      title: "먹고 보고 쉬기",
      description: hasPersonalPreferences
        ? "저장한 취향과 서로 다른 카페를 함께 담았어요"
        : "식사·문화와 카페를 고르게 담았어요",
      places: selectLowOverlapByCategory(
        balanced,
        ["cafe", "food", "culture", "walk", "entertainment"],
        count,
      ),
    },
  ];
  const used = new Set();
  return candidates.map((candidate, index) => {
    let selected = candidate.places;
    let signature = selected.map(placeIdentity).join("|");
    if (used.has(signature)) {
      selected = selectVaried(
        candidate.id === "culture" ? cultureFirst : unique,
        Math.min(index, unique.length - 1),
        candidate.places.length,
      );
      signature = selected.map(placeIdentity).join("|");
    }
    used.add(signature);
    return { ...candidate, places: selected };
  });
}

function normalizePlace(place, index) {
  const category = place.category ?? "culture";
  const sourceKind = placeSourceKind(place.source);
  const eventStart =
    place.start_at ??
    place.start_date ??
    place.event_start_date ??
    place.eventStartDate;
  const eventEnd =
    place.end_at ??
    place.end_date ??
    place.event_end_date ??
    place.eventEndDate;
  const actualImageUrl = place.image_url ?? place.imageUrl ?? null;
  const fallbackImageUrl =
    sourceKind === "popup"
      ? placePopup
      : (categoryFallbackImages[category] ?? placeCulture);
  return {
    ...place,
    id: `${place.source ?? "place"}-${place.source_id ?? index}-${place.name}`,
    name: place.name ?? "추천 장소",
    category,
    categoryLabel: categoryLabels[category] ?? place.category_detail ?? "장소",
    categoryIcon: categoryIcons[category] ?? "📍",
    stayMinutes:
      place.stay_duration_minutes ??
      place.specified_duration_minutes ??
      stayMinutesByCategory[category] ??
      45,
    specifiedDurationMinutes: place.specified_duration_minutes ?? null,
    distanceMeters: Number(place.distance_m ?? 0),
    sourceKind,
    sourceLabel:
      sourceKind === "popup"
        ? "팝업"
        : sourceKind === "culture"
          ? "문화행사"
          : null,
    eventPeriod: formatEventPeriod(eventStart, eventEnd),
    eventUrgency: eventUrgency(eventEnd),
    imageUrl: actualImageUrl ?? fallbackImageUrl,
    imageStatus: actualImageUrl ? "available" : "fallback",
    imageSource: place.image_source ?? place.imageSource ?? null,
    imageAttribution:
      place.image_attribution ?? place.imageAttribution ?? null,
    imageAttributionUrl:
      place.image_attribution_url ?? place.imageAttributionUrl ?? null,
  };
}

function distanceMetersBetween(from, to) {
  if (!from || !to || from.latitude == null || to.latitude == null)
    return Infinity;
  const radius = 6371000;
  const latitudeDelta =
    ((Number(to.latitude) - Number(from.latitude)) * Math.PI) / 180;
  const longitudeDelta =
    ((Number(to.longitude) - Number(from.longitude)) * Math.PI) / 180;
  const a =
    Math.sin(latitudeDelta / 2) ** 2 +
    Math.cos((Number(from.latitude) * Math.PI) / 180) *
      Math.cos((Number(to.latitude) * Math.PI) / 180) *
      Math.sin(longitudeDelta / 2) ** 2;
  return 2 * radius * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}

function bearingBetween(from, to) {
  if (!from || !to || from.latitude == null || to.latitude == null) return null;
  const fromLatitude = (Number(from.latitude) * Math.PI) / 180;
  const toLatitude = (Number(to.latitude) * Math.PI) / 180;
  const longitudeDelta =
    ((Number(to.longitude) - Number(from.longitude)) * Math.PI) / 180;
  const y = Math.sin(longitudeDelta) * Math.cos(toLatitude);
  const x =
    Math.cos(fromLatitude) * Math.sin(toLatitude) -
    Math.sin(fromLatitude) * Math.cos(toLatitude) * Math.cos(longitudeDelta);
  return ((Math.atan2(y, x) * 180) / Math.PI + 360) % 360;
}

function AreaCard({ area, selected, onSelect, onPreview }) {
  const reason =
    area.activityScore >= 0.7
      ? "원하는 활동과 잘 맞아요"
      : area.fromStartMinutes > 0 && area.fromStartMinutes <= 15
        ? "현재 위치에서 가까워요"
        : area.congestion === "여유"
          ? "비교적 여유롭게 머물 수 있어요"
          : "이동시간과 지역에서 쓸 수 있는 시간을 함께 고려했어요";
  return (
    <button
      className={`area-card${selected ? " is-selected" : ""}`}
      type="button"
      onMouseEnter={onPreview}
      onFocus={onPreview}
      onTouchStart={onPreview}
      onClick={onSelect}
    >
      <div className="area-card-top">
        <span>{area.rank}위</span>
        <strong>{area.name}</strong>
        {area.score && <em>{area.score}점</em>}
      </div>
      <div className="area-route">
        {area.fromStartMinutes > 0 && (
          <span>
            이동 시간{" "}
            <b>
              {formatMinutes(area.fromStartMinutes)}
              {area.fromStartTransport && ` · ${area.fromStartTransport}`}
            </b>
          </span>
        )}
        {area.stayMinutes !== null && (
          <span>
            도착 후 여유시간 <b>{formatMinutes(area.stayMinutes)}</b>
          </span>
        )}
        {area.toNextMinutes > 0 && (
          <span>
            다음 일정까지{" "}
            <b>
              {formatMinutes(area.toNextMinutes)}
              {area.toNextTransport && ` · ${area.toNextTransport}`}
            </b>
          </span>
        )}
      </div>
      <div className="area-metrics">
        <span>
          예상 혼잡도 <b>{area.congestion}</b>
        </span>
        {area.arrivalTime && (
          <span>
            도착 <b>{area.arrivalTime}</b>
          </span>
        )}
      </div>
      <p className="area-reason">{reason}</p>
    </button>
  );
}

function findSelectedPlace(optimizedPlace, selectedPlaces) {
  return selectedPlaces.find(
    (place) =>
      place.category === optimizedPlace.category &&
      Math.abs(Number(place.latitude) - Number(optimizedPlace.latitude)) <
        0.000001 &&
      Math.abs(Number(place.longitude) - Number(optimizedPlace.longitude)) <
        0.000001,
  );
}

function formatLegTransport(travel) {
  if (!travel) return "이동 경로 확인 중";
  if (travel.nearby) return "아주 가까운 거리 · 약 1분";
  const duration = formatCalculatedMinutes(travel.duration_min);
  if (travel.mode === "walk") return `도보 ${duration}`;
  if (travel.mode === "car") return `자동차 ${duration}`;
  const type =
    travel.route_type === "SUBWAY"
      ? "지하철"
      : travel.route_type === "BUS"
        ? "버스"
        : travel.route_type === "BUS_AND_SUBWAY"
          ? "버스·지하철"
          : "대중교통";
  const vehicles = [
    ...new Set(
      (travel.paths ?? [])
        .filter(
          (path) =>
            (path.type === "BUS" || path.type === "SUBWAY") && path.vehicle,
        )
        .map((path) => path.vehicle),
    ),
  ];
  const routeName = vehicles.length ? vehicles.join(" · ") : type;
  const transfer = travel.transfers > 0 ? ` · 환승 ${travel.transfers}회` : "";
  return `${routeName} · ${duration}${transfer}`;
}

function transitBoardingDetails(travel) {
  if (!travel?.paths?.length) return [];
  const seen = new Set();
  return travel.paths.flatMap((path) => {
    if (path.type !== "BUS" && path.type !== "SUBWAY") return [];
    const rawVehicle = String(path.vehicle ?? "").trim();
    const vehicle =
      path.type === "BUS"
        ? rawVehicle && !/(버스|번)$/.test(rawVehicle)
          ? `${rawVehicle}번 버스`
          : rawVehicle || "버스"
        : rawVehicle && !/호선$/.test(rawVehicle)
          ? `${rawVehicle}호선`
          : rawVehicle || "지하철";
    const key = `${path.type}:${vehicle}`;
    if (seen.has(key)) return [];
    seen.add(key);
    const seconds = Number(path.time);
    return [
      {
        type: path.type,
        vehicle,
        minutes:
          Number.isFinite(seconds) && seconds > 0
            ? Math.max(1, Math.round(seconds / 60))
            : null,
      },
    ];
  });
}

function routePoints(route) {
  return (route?.paths ?? []).flatMap((path) => {
    let points = path.points;
    if (typeof points === "string") {
      try {
        points = JSON.parse(points);
      } catch {
        return [];
      }
    }
    if (!Array.isArray(points)) points = points?.coordinates ?? points?.points;
    if (!Array.isArray(points)) return [];
    return points
      .map((point) =>
        Array.isArray(point)
          ? { longitude: Number(point[0]), latitude: Number(point[1]) }
          : {
              longitude: Number(point?.x ?? point?.longitude),
              latitude: Number(point?.y ?? point?.latitude),
            },
      )
      .filter(
        (point) =>
          Number.isFinite(point.latitude) && Number.isFinite(point.longitude),
      );
  });
}

function distanceToRouteMeters(location, route) {
  const points = routePoints(route);
  if (!location || points.length < 2) return Infinity;
  const latitudeScale = 111000;
  const longitudeScale =
    111000 * Math.cos((Number(location.latitude) * Math.PI) / 180);
  let minimum = Infinity;
  for (let index = 1; index < points.length; index += 1) {
    const start = points[index - 1];
    const end = points[index];
    const ax = (start.longitude - location.longitude) * longitudeScale;
    const ay = (start.latitude - location.latitude) * latitudeScale;
    const bx = (end.longitude - location.longitude) * longitudeScale;
    const by = (end.latitude - location.latitude) * latitudeScale;
    const dx = bx - ax;
    const dy = by - ay;
    const ratio = Math.max(
      0,
      Math.min(1, -(ax * dx + ay * dy) / (dx * dx + dy * dy || 1)),
    );
    minimum = Math.min(minimum, Math.hypot(ax + ratio * dx, ay + ratio * dy));
  }
  return minimum;
}

function nextRouteInstruction(route, travel, boarding) {
  const instructions = [...(route?.paths ?? []), ...(travel?.paths ?? [])]
    .map((path) => path.guidance)
    .filter(Boolean);
  const instruction =
    instructions.find(
      (value) => !/^(출발지|도착지|출발|도착)$/.test(String(value).trim()),
    ) ?? instructions[0];
  if (instruction) return instruction;
  if (boarding.length) return `${boarding[0].vehicle}에 탑승하세요`;
  if (travel?.mode === "car") return "표시된 자동차 경로를 따라 이동하세요";
  return "파란 점선을 따라 이동하세요";
}

function RecommendationPage({ response, onBack, account, onOpenAccount }) {
  const result = useMemo(() => normalizeRecommendation(response), [response]);
  const userMessage = response?._client_user_message ?? "";
  const requestedActivitySequence = useMemo(
    () =>
      resolveActivitySequence(
        userMessage,
        result.recommendationContext?.activity_sequence,
      ),
    [userMessage, result.recommendationContext?.activity_sequence],
  );
  const restoredCourse = response?._client_saved_course?.course_data ?? null;
  const rankingAreas = useMemo(
    () => [
      ...(result.targetArea ? [result.targetArea] : []),
      ...result.otherAreas,
      ...result.extendedAreas,
    ],
    [result],
  );
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [pinnedCourseArea, setPinnedCourseArea] = useState(null);
  const [placeMode, setPlaceMode] = useState(
    response?._client_mode === "auto-course" || Boolean(restoredCourse),
  );
  const [autoCourseMode, setAutoCourseMode] = useState(
    response?._client_mode === "auto-course",
  );
  const [autoCourseCalculating, setAutoCourseCalculating] = useState(false);
  const [autoCourseNotice, setAutoCourseNotice] = useState("");
  const [autoCourseVariation] = useState(() => {
    if (response?._client_mode !== "auto-course") return 0;
    try {
      const key = "koala-auto-course-variation";
      const next = (Number(window.sessionStorage.getItem(key)) || 0) + 1;
      window.sessionStorage.setItem(key, String(next));
      return next;
    } catch {
      return Date.now() % 11;
    }
  });
  const [recentAutoPlaceIds] = useState(() =>
    readSession("koala-auto-course-place-history", []),
  );
  const [selectedAutoCourseId, setSelectedAutoCourseId] = useState(null);
  const [verifiedAutoCourses, setVerifiedAutoCourses] = useState([]);
  const [hoveredCoursePlaces, setHoveredCoursePlaces] = useState([]);
  const [sidebarWidth, setSidebarWidth] = useState(
    () => Number(localStorage.getItem("koala-sidebar-width")) || 390,
  );
  const autoCourseVerificationRef = useRef(0);
  const [selectedPlaces, setSelectedPlaces] = useState(
    () => restoredCourse?.selected_places ?? [],
  );
  const [calculated, setCalculated] = useState(Boolean(restoredCourse?.course));
  const [places, setPlaces] = useState([]);
  const [excludedPlaceKeys, setExcludedPlaceKeys] = useState(() => new Set());
  const [favoritePlaceKeys, setFavoritePlaceKeys] = useState(() => new Set());
  const photoLookupAttemptedRef = useRef(new Set());
  const [placeSourceFilter, setPlaceSourceFilter] = useState("all");
  const [placeCursor, setPlaceCursor] = useState(null);
  const [nextOffset, setNextOffset] = useState(null);
  const [hasMorePlaces, setHasMorePlaces] = useState(false);
  const [placeStatus, setPlaceStatus] = useState("idle");
  const [placeError, setPlaceError] = useState("");
  const [moreLoadError, setMoreLoadError] = useState("");
  const [photoPreview, setPhotoPreview] = useState(null);
  const [adventureExperience, setAdventureExperience] = useState(null);
  const [questProgress, setQuestProgress] = useState({});
  const [mysteryRevealed, setMysteryRevealed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    if (!account?.token) {
      setExcludedPlaceKeys(new Set());
      setFavoritePlaceKeys(new Set());
      return undefined;
    }
    Promise.all([
      getExcludedPlaces(account.token),
      getFavoritePlaces(account.token),
    ])
      .then(([excluded, favorites]) => {
        if (!cancelled) {
          setExcludedPlaceKeys(
            new Set((excluded ?? []).map((item) => item.place_key)),
          );
          setFavoritePlaceKeys(
            new Set((favorites ?? []).map((item) => item.place_key)),
          );
        }
      })
      .catch(() => {
        /* 저장 기능 장애가 핵심 추천을 막지 않게 한다. */
      });
    return () => {
      cancelled = true;
    };
  }, [account?.token]);
  const [calculationStatus, setCalculationStatus] = useState(
    restoredCourse?.course ? "ready" : "idle",
  );
  const [calculationError, setCalculationError] = useState("");
  const [manualAvailableTimeMinutes, setManualAvailableTimeMinutes] =
    useState(null);
  const [timeBudgetPromptOpen, setTimeBudgetPromptOpen] = useState(false);
  const [timeBudgetDraft, setTimeBudgetDraft] = useState(120);
  const [courseResult, setCourseResult] = useState(() =>
    restoredCourse?.course
      ? { validation: null, course: restoredCourse.course }
      : null,
  );
  const [courseConfirmed, setCourseConfirmed] = useState(
    Boolean(restoredCourse?.course),
  );
  const [proactivePromptMode, setProactivePromptMode] = useState(null);
  const [proactiveDismissed, setProactiveDismissed] = useState(false);
  const [liveProactiveShown, setLiveProactiveShown] = useState(false);
  const [replacementPreviewOpen, setReplacementPreviewOpen] = useState(false);
  const [guidanceStarted, setGuidanceStarted] = useState(false);
  const [guideStep, setGuideStep] = useState(0);
  const [liveLocation, setLiveLocation] = useState(null);
  const [liveLocationStatus, setLiveLocationStatus] = useState("idle");
  const [deviceHeading, setDeviceHeading] = useState(null);
  const [guideRoute, setGuideRoute] = useState(null);
  const [guideRouteStatus, setGuideRouteStatus] = useState("idle");
  const [arrivalSeconds, setArrivalSeconds] = useState(0);
  const [transportMode, setTransportMode] = useState(() => {
    const initialMode =
      restoredCourse?.transport_mode ??
      result.recommendationContext?.transport_mode ??
      account?.preferences?.transport_mode;
    return ["public_transit", "car", "walk"].includes(initialMode)
      ? initialMode
      : "public_transit";
  });
  const [transportMenuOpen, setTransportMenuOpen] = useState(false);
  const mapTopbarRef = useRef(null);
  const [preferredPlaceId, setPreferredPlaceId] = useState(null);
  const [serverSaveStatus, setServerSaveStatus] = useState("idle");
  const historyKey = `koala-history-${JSON.stringify(response.map_context)}`;
  const [courseHistory, setCourseHistory] = useState(() =>
    readSession(historyKey, []),
  );
  useEffect(() => {
    writeSession(historyKey, courseHistory);
  }, [historyKey, courseHistory]);
  const [focusedStopIndex, setFocusedStopIndex] = useState(null);
  const [sheetExpanded, setSheetExpanded] = useState(false);
  // 모바일 지역 목록은 기본 높이 아래로도 내려 지도를 더 넓게 볼 수 있다.
  const [sheetMinimized, setSheetMinimized] = useState(false);
  const [routeCache, setRouteCache] = useState({});
  const [routeLoading, setRouteLoading] = useState({});
  const [routeErrors, setRouteErrors] = useState({});
  const dragStartY = useRef(null);
  const didDrag = useRef(false);
  const requestingRouteKeys = useRef(new Set());
  const loadMoreRequestRef = useRef(false);
  const lastLoadMoreAtRef = useRef(0);
  const placeScrollRef = useRef(null);
  const dividerDragRef = useRef(null);
  const placeRequestGenerationRef = useRef(0);
  const calculationRequest = useRef(0);
  const lastLiveLocation = useRef(null);
  const lastGuideRouteRequest = useRef(null);
  const routeDeviationRef = useRef({ count: 0, lastRerouteAt: 0 });
  const arrivalRef = useRef({
    targetId: null,
    enteredAt: null,
    lastLocationAt: null,
  });
  const lastHeadingRef = useRef({ value: null, updatedAt: 0 });
  useEffect(
    () => () => {
      calculationRequest.current += 1;
    },
    [],
  );

  const useAdventurePlaces = async (adventurePlaces, options = {}) => {
    setPinnedCourseArea(null);
    const normalized = adventurePlaces.map((place, index) =>
      normalizePlace(place, `adventure-${index}`),
    );
    setPlaces((current) => [
      ...normalized,
      ...current.filter(
        (place) => !normalized.some((item) => item.id === place.id),
      ),
    ]);
    setSelectedPlaces(
      normalized.map((place, index) => ({
        ...place,
        preferredFirst: index === 0,
      })),
    );
    setPreferredPlaceId(normalized[0]?.id ?? null);
    setAutoCourseMode(false);
    setPlaceMode(true);
    setCalculated(false);
    setCourseResult(null);
    setCourseConfirmed(false);
    setGuidanceStarted(false);
    setGuideStep(0);
    setQuestProgress({});
    setMysteryRevealed(false);
    setAdventureExperience({
      mode: options.mode ?? null,
      quest: options.quest ?? null,
    });
    setSheetExpanded(true);
    if (!options.autoConfirm || !normalized.length) return;
    const requestId = ++calculationRequest.current;
    setCalculationStatus("loading");
    setCalculationError("");
    try {
      const course = await requestCourse({
        startLocation,
        selectedPlaces: normalized,
        availableTimeMinutes,
        departureDatetime: result.recommendationContext?.departure_datetime,
        endLocation:
          result.mapContext?.end ?? result.recommendationContext?.end_location,
        transportMode,
        optimizeOrder: false,
        fresh: true,
      });
      if (requestId !== calculationRequest.current) return;
      if (course.status !== "FEASIBLE") {
        setCalculationStatus("warning");
        setCalculationError("실제 이동시간을 포함하면 시간이 부족해요. 자동으로 다른 코스를 찾는 중이에요.");
        setPlaceMode(false);
        return;
      }
      setCourseResult({ validation: null, course });
      setCourseHistory((current) => [
        {
          id: `${Date.now()}-${options.mode ?? "adventure"}`,
          areaName: selectedArea?.name,
          selectedPlaces: [...normalized],
          validation: null,
          course,
        },
        ...current,
      ].slice(0, 3));
      setCalculated(true);
      setCourseConfirmed(true);
      setGuidanceStarted(Boolean(options.startGuidance));
      setSheetExpanded(Boolean(options.startGuidance));
      setCalculationStatus("ready");
    } catch (error) {
      if (requestId !== calculationRequest.current) return;
      setCalculationStatus("error");
      setCalculationError(error.message ?? "코스를 완성하지 못했어요.");
      setPlaceMode(false);
    }
  };
  const useAdventureArea = (adventureArea) => {
    setPinnedCourseArea(null);
    const index = rankingAreas.findIndex(
      (area) => area.name === adventureArea?.AREA_NM,
    );
    if (index >= 0) setSelectedIndex(index);
    setSelectedPlaces([]);
    setPreferredPlaceId(null);
    setAutoCourseMode(false);
    setPlaceMode(true);
    setCalculated(false);
    setCourseResult(null);
    setSheetExpanded(true);
  };
  useEffect(() => {
    if (!transportMenuOpen) return undefined;
    const closeOnOutsidePress = (event) => {
      if (!mapTopbarRef.current?.contains(event.target))
        setTransportMenuOpen(false);
    };
    const closeOnEscape = (event) => {
      if (event.key === "Escape") setTransportMenuOpen(false);
    };
    document.addEventListener("pointerdown", closeOnOutsidePress);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("pointerdown", closeOnOutsidePress);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [transportMenuOpen]);
  // 사용자가 문장에 활동 지역을 명시했다면 그 지역을 코스 중심으로 쓴다.
  // 명시 지역이 없을 때만 현재 위치 주변 자동 코스를 만든다.
  const selectedArea = resolveCourseArea({
    pinnedArea: pinnedCourseArea,
    autoCourseMode,
    targetArea: result.targetArea,
    currentArea: result.currentArea,
    rankingAreas,
    selectedIndex,
  });
  const selectedTransport =
    transportOptions.find((option) => option.id === transportMode) ??
    transportOptions[0];
  const startLocation = useMemo(
    () =>
      result.mapContext?.start ?? {
        latitude: null,
        longitude: null,
      },
    [result.mapContext?.start],
  );
  const routeCacheKey =
    selectedArea?.latitude != null && selectedArea?.longitude != null
      ? `${transportMode}:${Number(selectedArea.latitude).toFixed(5)},${Number(selectedArea.longitude).toFixed(5)}`
      : null;
  const selectedAreaRoute =
    (routeCacheKey && routeCache[routeCacheKey]) ??
    selectedArea?.startRoute ??
    null;
  const isWalkingRouteLoading = Boolean(
    routeCacheKey && routeLoading[routeCacheKey] && !routeCache[routeCacheKey],
  );
  const savedCoursesForArea = courseHistory.filter(
    (item) => item.areaName === selectedArea?.name,
  );
  const displayArea = (area) => {
    const key =
      area?.latitude != null && area?.longitude != null
        ? `${transportMode}:${Number(area.latitude).toFixed(5)},${Number(area.longitude).toFixed(5)}`
        : null;
    const route = key ? routeCache[key] : null;
    if (!route?.duration_min) return area;
    const modeLabel =
      route.mode === "walk"
        ? "도보"
        : route.mode === "car"
          ? "자동차"
          : "대중교통";
    return {
      ...area,
      fromStartMinutes: route.duration_min,
      fromStartTransport: modeLabel,
      arrivalTime: null,
    };
  };

  const prepareAreaRoute = useCallback(
    (area) => {
      if (!area || area.latitude == null || area.longitude == null) return;
      const areaKey = `${transportMode}:${Number(area.latitude).toFixed(5)},${Number(area.longitude).toFixed(5)}`;
      if (routeCache[areaKey] || requestingRouteKeys.current.has(areaKey))
        return;
      requestingRouteKeys.current.add(areaKey);
      setRouteLoading((current) => ({ ...current, [areaKey]: true }));
      requestRoutePreview({
        startLatitude: startLocation.latitude,
        startLongitude: startLocation.longitude,
        endLatitude: area.latitude,
        endLongitude: area.longitude,
        transportMode,
      })
        .then((route) => {
          // route-preview is an optional enhancement; the aligned backend may not provide it.
          // Keep the backend's existing area times/routes when it is unavailable.
          if (route) {
            setRouteCache((current) => ({ ...current, [areaKey]: route }));
            setRouteErrors((current) => {
              const next = { ...current };
              delete next[areaKey];
              return next;
            });
          }
        })
        .catch((error) => {
          setRouteErrors((current) => ({
            ...current,
            [areaKey]: error?.message ?? "상세 경로를 확인하지 못했어요.",
          }));
        })
        .finally(() => {
          requestingRouteKeys.current.delete(areaKey);
          setRouteLoading((current) => ({ ...current, [areaKey]: false }));
        });
    },
    [
      routeCache,
      startLocation.latitude,
      startLocation.longitude,
      transportMode,
    ],
  );

  useEffect(() => {
    if (placeMode) {
      setSheetMinimized(false);
      setSheetExpanded(true);
    }
  }, [placeMode]);
  useEffect(() => {
    // 1순위는 서버가 미리 준비해 준 Tmap 보행 경로를 즉시 사용한다.
    // 다른 지역은 기존 지도 경로를 먼저 그리고, 보행 보강본만 뒤에서 받아 캐시한다.
    if (!routeCacheKey) return;
    prepareAreaRoute(selectedArea);
  }, [routeCacheKey, selectedArea, prepareAreaRoute]);

  useEffect(() => {
    // 세 후보 모두 이동수단 표시를 완성한다. 이전 서버 응답과의 호환을 위해
    // 상세 이동수단이 없는 후보만 짧은 간격으로 미리 계산한다.
    const pendingAreas = rankingAreas.filter(
      (area) => !area.hasPreparedMapRoute,
    );
    const timers = pendingAreas.map((area, index) =>
      window.setTimeout(() => prepareAreaRoute(area), 250 + index * 180),
    );
    return () => timers.forEach((timer) => window.clearTimeout(timer));
  }, [rankingAreas, prepareAreaRoute]);

  useEffect(() => {
    if (
      !placeMode ||
      !selectedArea?.name ||
      selectedArea.latitude == null ||
      selectedArea.longitude == null
    )
      return undefined;
    const requestGeneration = ++placeRequestGenerationRef.current;
    let cancelled = false;
    setPlaceSourceFilter("all");
    setPlaceStatus("loading");
    setPlaceError("");
    setMoreLoadError("");
    requestPlaces({
      areaName: selectedArea.name,
      latitude: selectedArea.latitude,
      longitude: selectedArea.longitude,
      recommendationContext: result.recommendationContext,
    })
      .then(async (data) => {
        if (
          cancelled ||
          requestGeneration !== placeRequestGenerationRef.current
        )
          return;
        let combinedPlaces = data.places ?? [];
        let nextCursor = data.cursor ?? null;
        let followingOffset = data.next_offset ?? null;
        let moreAvailable = Boolean(data.has_more);
        // 자동 코스 3종이 같은 6개 후보만 돌려 쓰지 않도록 캐시에 준비된
        // 다음 페이지를 한 번 더 가져온다. 추가 외부 검색은 없어 응답 부담이 작다.
        if (
          autoCourseMode &&
          nextCursor &&
          followingOffset != null &&
          moreAvailable
        ) {
          try {
            const more = await requestMorePlaces({
              cursor: nextCursor,
              offset: followingOffset,
            });
            if (
              cancelled ||
              requestGeneration !== placeRequestGenerationRef.current
            )
              return;
            combinedPlaces = [...combinedPlaces, ...(more.places ?? [])];
            nextCursor = more.cursor ?? nextCursor;
            followingOffset = more.next_offset ?? null;
            moreAvailable = Boolean(more.has_more);
          } catch {
            /* 첫 페이지 후보만으로도 자동 코스는 계속 만든다. */
          }
        }
        const seen = new Set();
        setPlaces(
          combinedPlaces.map(normalizePlace).filter((place) => {
            const identity = placeIdentity(place);
            if (excludedPlaceKeys.has(identity)) return false;
            if (seen.has(identity)) return false;
            seen.add(identity);
            return true;
          }),
        );
        setPlaceCursor(nextCursor);
        setNextOffset(followingOffset);
        setHasMorePlaces(moreAvailable);
        setPlaceStatus("ready");
      })
      .catch((error) => {
        if (!cancelled) {
          setPlaces([]);
          setPlaceStatus("error");
          setPlaceError(error.message);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [
    placeMode,
    autoCourseMode,
    selectedArea?.name,
    selectedArea?.latitude,
    selectedArea?.longitude,
    result.recommendationContext,
    excludedPlaceKeys,
  ]);

  useEffect(() => {
    if (!placeMode || placeStatus !== "ready") return undefined;
    if (photoLookupAttemptedRef.current.size >= 6) return undefined;
    const candidates = places
      .filter(
        (place) =>
          place.sourceKind === "general" &&
          ["food", "cafe", "culture", "walk", "entertainment", "shopping", "drink"].includes(
            place.category,
          ) &&
          place.imageStatus !== "available" &&
          !photoLookupAttemptedRef.current.has(place.id),
      )
      .slice(0, 6 - photoLookupAttemptedRef.current.size);
    if (!candidates.length) return undefined;

    candidates.forEach((place) =>
      photoLookupAttemptedRef.current.add(place.id),
    );
    let cancelled = false;
    requestPlacePhotos(candidates)
      .then((data) => {
        if (cancelled || !data?.enabled || !data.photos?.length) return;
        const photos = new Map(
          data.photos.map((photo) => [photo.client_key, photo]),
        );
        setPlaces((current) =>
          current.map((place) => {
            const photo = photos.get(place.id);
            return photo
              ? {
                  ...place,
                  imageUrl: photo.image_url,
                  imageStatus: "available",
                  imageSource: photo.image_source,
                  imageAttribution: photo.image_attribution,
                  imageAttributionUrl: photo.image_attribution_url,
                }
              : place;
          }),
        );
      })
      .catch((error) => {
        audit("optional_place_photo_error", { message: error?.message });
      });
    return () => {
      cancelled = true;
    };
  }, [placeMode, placeStatus, places]);

  const handleLoadMore = async ({ force = false } = {}) => {
    const now = Date.now();
    if (
      !placeCursor ||
      nextOffset == null ||
      !hasMorePlaces ||
      (moreLoadError && !force) ||
      placeStatus === "more-loading" ||
      loadMoreRequestRef.current ||
      (!force && now - lastLoadMoreAtRef.current < 700)
    )
      return;

    loadMoreRequestRef.current = true;
    lastLoadMoreAtRef.current = now;
    const requestGeneration = placeRequestGenerationRef.current;
    const requestedOffset = nextOffset;
    setMoreLoadError("");
    setPlaceStatus("more-loading");
    try {
      const data = await requestMorePlaces({
        cursor: placeCursor,
        offset: requestedOffset,
      });
      if (requestGeneration !== placeRequestGenerationRef.current) return;

      setPlaces((current) => {
        const seen = new Set(current.map(placeIdentity));
        const additions = (data.places ?? [])
          .map((place, index) => normalizePlace(place, current.length + index))
          .filter((place) => {
            const identity = placeIdentity(place);
            if (excludedPlaceKeys.has(identity)) return false;
            if (seen.has(identity)) return false;
            seen.add(identity);
            return true;
          })
          .slice(0, 4);
        return [...current, ...additions];
      });

      // 서버는 6개 단위 페이지를 반환하지만 화면에는 한 번에 4개 정도만 추가한다.
      // 다음 요청을 4칸만 전진시켜 이번 응답에서 아직 노출하지 않은 후보도 다음 번에 다시 받는다.
      const nextClientOffset = requestedOffset + 4;
      const receivedCount = (data.places ?? []).length;
      const moreCandidatesRemain = Boolean(data.has_more) || receivedCount > 4;
      setNextOffset(moreCandidatesRemain ? nextClientOffset : null);
      setHasMorePlaces(moreCandidatesRemain);
      setPlaceStatus("ready");
    } catch (error) {
      setPlaceStatus("ready");
      setMoreLoadError(error.message || "장소를 불러오지 못했어요");
    } finally {
      loadMoreRequestRef.current = false;
    }
  };

  const handleExcludePlace = async (place) => {
    if (!account?.token) {
      onOpenAccount?.();
      return;
    }
    const placeKey = placeIdentity(place);
    try {
      await excludePlace(account.token, {
        place_key: placeKey,
        place_name: place.name,
      });
      setExcludedPlaceKeys((current) => new Set([...current, placeKey]));
      setPlaces((current) =>
        current.filter((item) => placeIdentity(item) !== placeKey),
      );
      setSelectedPlaces((current) =>
        current.filter((item) => placeIdentity(item) !== placeKey),
      );
      setCalculated(false);
      setCourseResult(null);
      void recordInteraction(account.token, {
        event_type: "hide",
        place_key: placeKey,
        place_name: place.name,
        category: place.category,
        context_data: { area_name: selectedArea?.name ?? null },
      }).catch(() => {});
    } catch (error) {
      setPlaceError(error.message ?? "이 장소를 숨기지 못했어요.");
    }
  };

  const toggleFavoritePlace = async (place) => {
    if (!account?.token) {
      onOpenAccount?.();
      return;
    }
    const placeKey = placeIdentity(place);
    const isFavorite = favoritePlaceKeys.has(placeKey);
    try {
      if (isFavorite) {
        await removeFavoritePlace(account.token, placeKey);
      } else {
        await addFavoritePlace(account.token, {
          place_key: placeKey,
          place_name: place.name,
          category: place.category,
          // 다른 기기에서도 코스에 다시 넣을 수 있는 최소 정보만 보관한다.
          place_data: {
            id: place.id,
            source_id: place.source_id ?? null,
            name: place.name,
            address: place.address ?? null,
            category: place.category,
            latitude: place.latitude,
            longitude: place.longitude,
            image_url: place.imageUrl ?? null,
          },
        });
      }
      setFavoritePlaceKeys((current) => {
        const next = new Set(current);
        if (isFavorite) next.delete(placeKey);
        else next.add(placeKey);
        return next;
      });
      if (!isFavorite) {
        void recordInteraction(account.token, {
          event_type: "favorite",
          place_key: placeKey,
          place_name: place.name,
          category: place.category,
          context_data: { area_name: selectedArea?.name ?? null },
        }).catch(() => {});
      }
    } catch (error) {
      setPlaceError(error.message ?? "즐겨찾기를 변경하지 못했어요.");
    }
  };

  const handleDividerPointerDown = (event) => {
    if (window.innerWidth < 900) return;
    dividerDragRef.current = true;
    event.currentTarget.setPointerCapture?.(event.pointerId);
  };
  const handleDividerPointerMove = (event) => {
    if (!dividerDragRef.current) return;
    setSidebarWidth(
      Math.round(
        Math.max(340, Math.min(window.innerWidth * 0.58, event.clientX)),
      ),
    );
  };
  const handleDividerPointerUp = (event) => {
    if (!dividerDragRef.current) return;
    dividerDragRef.current = false;
    event.currentTarget.releasePointerCapture?.(event.pointerId);
    localStorage.setItem("koala-sidebar-width", String(sidebarWidth));
    window.dispatchEvent(new Event("resize"));
  };

  const handleSheetPointerDown = (event) => {
    dragStartY.current = event.clientY;
    didDrag.current = false;
    // 손가락이나 마우스가 좁은 손잡이 밖으로 나가도 drag 이벤트를 계속 받는다.
    event.currentTarget.setPointerCapture?.(event.pointerId);
  };
  const handleSheetPointerMove = (event) => {
    if (
      dragStartY.current !== null &&
      Math.abs(event.clientY - dragStartY.current) > 10
    )
      didDrag.current = true;
  };
  const handleSheetPointerUp = (event) => {
    if (dragStartY.current === null) return;
    const distance = event.clientY - dragStartY.current;
    if (distance < -24) {
      if (sheetMinimized) setSheetMinimized(false);
      else setSheetExpanded(true);
    }
    if (distance > 24) {
      if (sheetExpanded) setSheetExpanded(false);
      else if (!placeMode) setSheetMinimized(true);
    }
    dragStartY.current = null;
    event.currentTarget.releasePointerCapture?.(event.pointerId);
  };
  const handleSheetPointerCancel = (event) => {
    dragStartY.current = null;
    didDrag.current = false;
    event.currentTarget.releasePointerCapture?.(event.pointerId);
  };
  const togglePlace = (place) => {
    calculationRequest.current += 1;
    setFocusedStopIndex(null);
    setCalculated(false);
    setCalculationError("");
    setCalculationStatus("idle");
    setCourseResult(null);
    setCourseConfirmed(false);
    setGuidanceStarted(false);
    setGuideStep(0);
    setProactiveDismissed(false);
    setLiveProactiveShown(false);
    const existingIndex = selectedPlaces.findIndex(
      (item) => item.id === place.id,
    );
    if (existingIndex >= 0) {
      const remaining = selectedPlaces.filter((item) => item.id !== place.id);
      const nextPreferredId =
        preferredPlaceId === place.id
          ? (remaining[0]?.id ?? null)
          : preferredPlaceId;
      setPreferredPlaceId(nextPreferredId);
      setSelectedPlaces(
        remaining.map((item) => ({
          ...item,
          preferredFirst: item.id === nextPreferredId,
        })),
      );
      setFocusedStopIndex(null);
      return;
    }
    const nextPreferredId = preferredPlaceId ?? place.id;
    // 선택 기록은 추천을 막지 않도록 실패를 무시하는 비동기 보조 요청이다.
    void recordInteraction(account?.token, {
      event_type: "place_select",
      place_key: placeIdentity(place),
      place_name: place.name,
      category: place.category,
      context_data: { area_name: selectedArea?.name ?? null },
    }).catch(() => {});
    setPreferredPlaceId(nextPreferredId);
    setFocusedStopIndex(selectedPlaces.length);
    setSelectedPlaces([
      ...selectedPlaces,
      { ...place, preferredFirst: place.id === nextPreferredId },
    ]);
  };
  const estimatedStay = selectedPlaces.reduce(
    (sum, place) => sum + place.stayMinutes,
    0,
  );
  const travelEstimate = useCourseTravelEstimate({
    startLocation,
    selectedPlaces,
    endLocation: result.mapContext?.end,
    transportMode,
  });
  const estimatedTravel = travelEstimate.travelMinutes;
  const rawAvailableTimeMinutes =
    manualAvailableTimeMinutes ??
    result.mapContext?.available_time_minutes ??
    result.recommendationContext?.available_time_minutes ??
    (response?._client_mode === "auto-course"
      ? response._client_selected_duration_minutes
      : null) ??
    (selectedArea?.stayMinutes != null
      ? selectedArea.stayMinutes +
        selectedArea.fromStartMinutes +
        selectedArea.toNextMinutes
      : null);
  const availableTimeMinutes =
    Number.isFinite(Number(rawAvailableTimeMinutes)) &&
    Number(rawAvailableTimeMinutes) > 0
      ? Number(rawAvailableTimeMinutes)
      : null;

  const applyManualTimeBudget = (minutes) => {
    const normalizedMinutes = Math.max(
      30,
      Math.min(480, Math.round(Number(minutes) / 10) * 10),
    );
    setManualAvailableTimeMinutes(normalizedMinutes);
    setTimeBudgetDraft(normalizedMinutes);
    setTimeBudgetPromptOpen(false);
    setSelectedPlaces([]);
    setPreferredPlaceId(null);
    setCalculated(false);
    setCourseResult(null);
    setCalculationError("");
    setPlaceMode(true);
    setSheetExpanded(true);
  };

  const setTimeBudgetPart = (part, value) => {
    const currentHours = Math.floor(timeBudgetDraft / 60);
    const currentMinutes = timeBudgetDraft % 60;
    const nextMinutes =
      part === "hours"
        ? Number(value) * 60 + currentMinutes
        : currentHours * 60 + Number(value);
    setTimeBudgetDraft(Math.max(30, Math.min(480, nextMinutes)));
  };
  const actualTravel = courseResult?.course?.total_travel_time_minutes;
  const displayedTravel = actualTravel ?? estimatedTravel ?? 0;
  const displayedStay =
    courseResult?.course?.total_stay_time_minutes ?? estimatedStay;
  const estimatedTotal =
    estimatedTravel == null ? null : estimatedTravel + estimatedStay;
  const displayedTotal =
    courseResult?.course?.total_required_minutes ?? estimatedTotal;
  const hasActualTime = courseResult?.course?.total_required_minutes != null;
  const calculationIsEstimated =
    courseResult?.course?.calculation_status === "estimated" ||
    (!hasActualTime && travelEstimate.status === "estimated");
  const timeGaugeOver =
    displayedTotal != null && displayedTotal > availableTimeMinutes;
  const timeCalculationLabel = hasActualTime
    ? `${calculationIsEstimated ? "일부 예상" : "실제 계산"} ${displayedTotal}분`
    : displayedTotal != null
      ? `사전 계산 ${displayedTotal}분`
      : travelEstimate.status === "loading"
        ? "실제 경로 계산 중"
        : "이동시간 계산 불가";
  useEffect(() => {
    audit("frontend_display", {
      frontend_display: {
        start: startLocation,
        end: result.mapContext?.end,
        transport_mode: transportMode,
        available_time_minutes: availableTimeMinutes,
        total_required_minutes: displayedTotal,
        total_travel_time_minutes: displayedTravel,
        total_stay_time_minutes: displayedStay,
        actual: hasActualTime,
        selected_place_ids: selectedPlaces.map((place) => place.id),
      },
    });
  }, [
    startLocation,
    result.mapContext?.end,
    transportMode,
    availableTimeMinutes,
    displayedTotal,
    displayedTravel,
    displayedStay,
    hasActualTime,
    selectedPlaces,
  ]);

  const handleCalculate = async (
    placesToCalculate = selectedPlaces,
    transportModeOverride = transportMode,
  ) => {
    if (!placesToCalculate.length) return;
    if (!availableTimeMinutes) {
      setCalculationStatus("error");
      setCalculationError(
        "사용 가능한 시간을 확인할 수 없어요. 이전 화면에서 시간을 입력해 주세요.",
      );
      return;
    }
    if (
      !Number.isFinite(Number(startLocation.latitude)) ||
      !Number.isFinite(Number(startLocation.longitude))
    ) {
      setCalculationStatus("error");
      setCalculationError(
        "시작 위치를 확인할 수 없어요. 위치를 입력하거나 현재 위치 사용을 허용해 주세요.",
      );
      return;
    }
    const requestId = ++calculationRequest.current;
    const activitySequence = requestedActivitySequence;
    const preserveActivityOrder = hasOrderedActivitySequence(activitySequence);
    const orderedPlacesToCalculate = preserveActivityOrder
      ? orderPlacesByActivitySequence(placesToCalculate, activitySequence)
      : [...placesToCalculate];
    setCalculationStatus("loading");
    setCalculationError("");
    try {
      const validation = await validatePlaceSelection({
        startLatitude: startLocation.latitude,
        startLongitude: startLocation.longitude,
        selectedPlaces: orderedPlacesToCalculate,
        availableTimeMinutes,
      });
      if (requestId !== calculationRequest.current) return;
      setCourseResult({ validation, course: null });
      // The straight-distance estimate is advisory; actual routing decides feasibility.
      const course = await requestCourse({
        startLocation,
        selectedPlaces: orderedPlacesToCalculate,
        availableTimeMinutes,
        departureDatetime: result.recommendationContext?.departure_datetime,
        endLocation:
          result.mapContext?.end ?? result.recommendationContext?.end_location,
        transportMode: transportModeOverride,
        optimizeOrder: !preserveActivityOrder,
      });
      if (requestId !== calculationRequest.current) return;
      setCourseResult({ validation, course });
      if (course.status !== "FEASIBLE") {
        setCalculationStatus("warning");
        setCalculationError(
          `실제 이동을 포함하면 총 ${course.total_required_minutes ?? "확인 불가"}분이에요. 사용할 수 있는 ${availableTimeMinutes}분을 초과했어요.`,
        );
        return;
      }
      setCourseHistory((current) =>
        [
          {
            id: `${Date.now()}-${selectedArea?.name ?? "course"}`,
            areaName: selectedArea?.name,
            selectedPlaces: [...orderedPlacesToCalculate],
            validation,
            course,
          },
          ...current,
        ].slice(0, 3),
      );
      setCalculated(true);
      setCourseConfirmed(false);
      setGuidanceStarted(false);
      setGuideStep(0);
      setFocusedStopIndex(null);
      setSheetExpanded(false);
      setCalculationStatus("ready");
    } catch (error) {
      if (requestId !== calculationRequest.current) return;
      setCalculationStatus("error");
      setCalculationError(error.message);
    }
  };

  const finishCalculatedCourse = (placesToCalculate, validation, course) => {
    // Auto-course mode is turned off on completion. Pin the area used for the
    // calculation first so the header cannot fall back to ranking index 0.
    setPinnedCourseArea(selectedArea);
    setSelectedPlaces(placesToCalculate);
    setCourseResult({ validation, course });
    setCourseHistory((current) =>
      [
        {
          id: `${Date.now()}-${selectedArea?.name ?? "course"}`,
          areaName: selectedArea?.name,
          selectedPlaces: [...placesToCalculate],
          validation,
          course,
        },
        ...current,
      ].slice(0, 3),
    );
    setCalculated(true);
    setAutoCourseMode(false);
    setCourseConfirmed(false);
    setGuidanceStarted(false);
    setGuideStep(0);
    setFocusedStopIndex(null);
    setSheetExpanded(false);
    setCalculationStatus("ready");
  };

  const orderedPlaces = useMemo(() => {
    const remaining = [...selectedPlaces];
    return (courseResult?.course?.optimized_places ?? [])
      .map((place) => {
        const match = findSelectedPlace(place, remaining);
        if (match) remaining.splice(remaining.indexOf(match), 1);
        return match
          ? {
              ...match,
              stayMinutes: place.stay_duration_minutes ?? match.stayMinutes,
              availability: place.availability,
            }
          : null;
      })
      .filter(Boolean);
  }, [courseResult, selectedPlaces]);
  const visiblePlaces =
    calculated && orderedPlaces.length ? orderedPlaces : selectedPlaces;
  const mysteryMode = adventureExperience?.mode === "blind-course";
  const mysteryName = (place, index) =>
    mysteryMode && !mysteryRevealed && index >= guideStep
      ? `비밀 장소 ${index + 1}`
      : place.name;
  const mapVisiblePlaces = visiblePlaces.map((place, index) => ({
    ...place,
    name: mysteryName(place, index),
  }));
  const replacementTarget =
    visiblePlaces[focusedStopIndex ?? Math.max(0, visiblePlaces.length - 1)] ??
    null;
  const replacementPlace = useMemo(() => {
    if (!replacementTarget) return null;
    const selectedIds = new Set(selectedPlaces.map((place) => place.id));
    return (
      [...places]
        .filter((place) => !selectedIds.has(place.id))
        .sort((left, right) => {
          const leftSameCategory =
            left.category === replacementTarget.category ? 1 : 0;
          const rightSameCategory =
            right.category === replacementTarget.category ? 1 : 0;
          return (
            rightSameCategory - leftSameCategory ||
            left.distanceMeters - right.distanceMeters
          );
        })[0] ?? null
    );
  }, [places, selectedPlaces, replacementTarget]);
  const hasEventPlaces = places.some((place) => place.sourceKind !== "general");
  const proactiveOffer = useMemo(() => {
    if (result.proactiveSuggestion?.place) {
      return {
        place: normalizePlace(result.proactiveSuggestion.place, "proactive"),
        reason: result.proactiveSuggestion.reason,
        message: result.proactiveSuggestion.message,
        travelMinutes: Number(
          result.proactiveSuggestion.travel?.duration_min ?? 0,
        ),
        visitableMinutes: Number(
          result.proactiveSuggestion.visitable_minutes ?? 0,
        ),
      };
    }
    // 확정·안내 중 개입은 백엔드가 영업시간과 다음 일정까지 검증한 제안만 쓴다.
    return null;
  }, [result.proactiveSuggestion]);
  const proactiveExtraMinutes = proactiveOffer?.place
    ? Math.max(
        20,
        Math.min(
          proactiveOffer.visitableMinutes ||
            proactiveOffer.place.stayMinutes ||
            30,
          45,
        ),
      ) + Math.max(0, proactiveOffer.travelMinutes || 0)
    : Infinity;
  const proactiveFitsCourse = Boolean(
    proactiveOffer?.place &&
    !selectedPlaces.some(
      (place) => placeIdentity(place) === placeIdentity(proactiveOffer.place),
    ) &&
    Number(courseResult?.course?.remaining_time_minutes ?? 0) >=
      proactiveExtraMinutes,
  );
  const filteredPlaces =
    placeSourceFilter === "events"
      ? places.filter((place) => place.sourceKind !== "general")
      : placeSourceFilter === "general"
        ? places.filter((place) => place.sourceKind === "general")
        : places;
  const autoCourseTargetPlaceCount = Math.min(
    6,
    Math.max(2, Math.floor((availableTimeMinutes * 0.9) / 65)),
  );
  const autoCourseNearbyPlaces = useMemo(
    () =>
      places.filter((place) => {
        // "이 주변" 자동 추천은 장소 검색 반경 2km를 넘지 않는다. 실제 경로
        // 검증은 이 다음 단계에서 다시 수행한다.
        return (
          !Number.isFinite(place.distanceMeters) || place.distanceMeters <= 2000
        );
      }),
    [places],
  );
  const autoCourseCandidates = useMemo(
    () =>
      buildAutoCourseCandidates(
        autoCourseNearbyPlaces,
        result.recommendationContext?.activities ??
          Object.entries(account?.preferences?.activity_preferences ?? {})
            .filter(([, level]) => Number(level) >= 4)
            .map(([code]) => code),
        Boolean(
          account?.user &&
          Object.values(account?.preferences?.activity_preferences ?? {}).some(
            (level) => Number(level) >= 4,
          ),
        ),
        autoCourseTargetPlaceCount,
        autoCourseVariation,
        recentAutoPlaceIds,
      ),
    [
      autoCourseNearbyPlaces,
      result.recommendationContext?.activities,
      account?.user,
      account?.preferences?.activity_preferences,
      autoCourseTargetPlaceCount,
      autoCourseVariation,
      recentAutoPlaceIds,
    ],
  );
  useEffect(() => {
    if (
      !autoCourseMode ||
      placeStatus !== "ready" ||
      !autoCourseCandidates.length
    )
      return undefined;
    const verificationId = ++autoCourseVerificationRef.current;
    let cancelled = false;
    setAutoCourseCalculating(true);
    setVerifiedAutoCourses([]);
    setAutoCourseNotice("");
    // 자동 추천 카드는 선택 전에 실제 이동시간으로 검증한다. 사용자가 카드 선택
    // 뒤에 시간 초과 오류를 보지 않도록, 가능한 코스만 보여준다.
    Promise.allSettled(
      autoCourseCandidates.slice(0, 3).map(async (candidate) => {
        const activitySequence = requestedActivitySequence;
        const orderedCandidatePlaces = orderPlacesByActivitySequence(
          candidate.places,
          activitySequence,
        );
        const course = await requestCourse({
          startLocation,
          selectedPlaces: orderedCandidatePlaces,
          availableTimeMinutes,
          departureDatetime: result.recommendationContext?.departure_datetime,
          endLocation:
            result.mapContext?.end ??
            result.recommendationContext?.end_location,
          transportMode,
          optimizeOrder: false,
        });
        if (course.status !== "FEASIBLE") return null;
        return {
          ...candidate,
          places: orderedCandidatePlaces,
          course,
          verificationStatus: "verified",
          estimatedStayMinutes: course.total_stay_time_minutes,
          estimatedTravelMinutes: course.total_travel_time_minutes,
        };
      }),
    )
      .then((outcomes) => {
        if (cancelled || verificationId !== autoCourseVerificationRef.current)
          return;
        const verified = outcomes
          .filter((outcome) => outcome.status === "fulfilled" && outcome.value)
          .map((outcome) => outcome.value);
        if (verified.length) {
          const shownPlaceIds = verified.flatMap((candidate) =>
            candidate.places.map(placeIdentity),
          );
          writeSession(
            "koala-auto-course-place-history",
            [...recentAutoPlaceIds, ...shownPlaceIds].slice(-30),
          );
        }
        setVerifiedAutoCourses(verified);
        setAutoCourseNotice(
          verified.length
            ? verified.length < 3
              ? `현재 조건에서 실제 시간 안에 맞는 코스 ${verified.length}개를 준비했어요.`
              : ""
            : "현재 시간과 주변 장소 조건을 모두 맞추는 코스를 찾지 못했어요. 장소를 직접 골라주세요.",
        );
      })
      .finally(() => {
        if (!cancelled && verificationId === autoCourseVerificationRef.current)
          setAutoCourseCalculating(false);
      });
    return () => {
      cancelled = true;
      autoCourseVerificationRef.current += 1;
    };
  }, [
    autoCourseMode,
    placeStatus,
    autoCourseCandidates,
    startLocation,
    availableTimeMinutes,
    result.recommendationContext?.departure_datetime,
    requestedActivitySequence,
    result.mapContext?.end,
    result.recommendationContext?.end_location,
    transportMode,
    recentAutoPlaceIds,
  ]);

  const chooseAutoCourse = async (candidate) => {
    if (autoCourseCalculating) return;
    if (!availableTimeMinutes) {
      setCalculationError(
        "사용 가능한 시간이 없어요. 이전 화면에서 종료 시각이나 여유 시간을 다시 입력해 주세요.",
      );
      return;
    }
    const requestId = ++calculationRequest.current;
    const orderedCandidatePlaces = orderPlacesByActivitySequence(
      candidate.places,
      requestedActivitySequence,
    );
    setSelectedPlaces(orderedCandidatePlaces);
    setPreferredPlaceId(orderedCandidatePlaces[0]?.id ?? null);
    setSelectedAutoCourseId(candidate.id);
    setAutoCourseNotice("");
    if (candidate.course?.status === "FEASIBLE") {
      finishCalculatedCourse(orderedCandidatePlaces, null, candidate.course);
      return;
    }
    setAutoCourseCalculating(true);
    try {
      const course = await requestCourse({
        startLocation,
        selectedPlaces: orderedCandidatePlaces,
        availableTimeMinutes,
        departureDatetime: result.recommendationContext?.departure_datetime,
        endLocation:
          result.mapContext?.end ?? result.recommendationContext?.end_location,
        transportMode,
        optimizeOrder: false,
      });
      if (requestId !== calculationRequest.current) return;
      if (course.status !== "FEASIBLE") {
        setCalculationError(
          "이 코스는 실제 이동시간을 포함하면 여유가 부족해요. 다른 코스를 골라주세요.",
        );
        return;
      }
      finishCalculatedCourse(orderedCandidatePlaces, null, course);
    } catch (error) {
      setCalculationError(
        error.message ?? "실제 이동경로를 확인하지 못했어요.",
      );
    } finally {
      setAutoCourseCalculating(false);
    }
  };
  const acceptProactiveSuggestion = () => {
    if (!proactiveOffer?.place) return;
    const proactivePlace = { ...proactiveOffer.place, preferredFirst: false };
    const nextPlaces = [
      ...selectedPlaces.filter(
        (place) => placeIdentity(place) !== placeIdentity(proactivePlace),
      ),
      proactivePlace,
    ];
    setPlaces((current) => [
      proactivePlace,
      ...current.filter(
        (place) => placeIdentity(place) !== placeIdentity(proactivePlace),
      ),
    ]);
    setSelectedPlaces(nextPlaces);
    setProactivePromptMode(null);
    setProactiveDismissed(true);
    setAutoCourseMode(false);
    setCalculated(false);
    setCourseResult(null);
    setSheetExpanded(true);
    void handleCalculate(nextPlaces);
  };
  const returnToAutoCourses = () => {
    calculationRequest.current += 1;
    // 자동 코스 카드 화면에는 직전에 선택한 코스의 마커를 남기지 않는다.
    setSelectedPlaces([]);
    setPreferredPlaceId(null);
    setFocusedStopIndex(null);
    setGuideStep(0);
    setCalculated(false);
    setCourseResult(null);
    setCourseConfirmed(false);
    setGuidanceStarted(false);
    setCalculationStatus("idle");
    setCalculationError("");
    setAutoCourseCalculating(false);
    setVerifiedAutoCourses([]);
    setSelectedAutoCourseId(null);
    setPinnedCourseArea(null);
    setAutoCourseMode(true);
    setReplacementPreviewOpen(false);
    setSheetExpanded(true);
  };
  const canReturnToAutoCourses =
    response?._client_mode === "auto-course" &&
    (calculated || Boolean(selectedAutoCourseId));
  const handleResultsBack = () => {
    if (!placeMode) {
      onBack();
      return;
    }
    if (canReturnToAutoCourses) {
      returnToAutoCourses();
      return;
    }
    returnToRegions();
  };
  const confirmReplacement = () => {
    if (!replacementTarget || !replacementPlace) return;
    const nextPlaces = selectedPlaces.map((place) =>
      place.id === replacementTarget.id
        ? { ...replacementPlace, preferredFirst: place.preferredFirst }
        : place,
    );
    setReplacementPreviewOpen(false);
    setSelectedPlaces(nextPlaces);
    setPreferredPlaceId(
      nextPlaces.find((place) => place.preferredFirst)?.id ??
        nextPlaces[0]?.id ??
        null,
    );
    void handleCalculate(nextPlaces);
  };
  const guideStopCount =
    visiblePlaces.length + (result.mapContext?.end ? 1 : 0);
  const guideIsComplete = guidanceStarted && guideStep >= guideStopCount;
  const guidePlace =
    guideStep < visiblePlaces.length ? visiblePlaces[guideStep] : null;
  const guideDestination = useMemo(
    () =>
      guidePlace ??
      (guideStep === visiblePlaces.length && result.mapContext?.end
        ? { id: "next-schedule", name: "다음 일정", ...result.mapContext.end }
        : null),
    [guidePlace, guideStep, visiblePlaces.length, result.mapContext],
  );
  const guidePreviousPlace =
    guideStep > 0 ? visiblePlaces[guideStep - 1] : null;
  const guideOrigin = liveLocation ?? guidePreviousPlace ?? startLocation;
  const guideOriginLabel = guidePreviousPlace
    ? `${guideStep}번 출발`
    : "현재 위치";
  const guideTravel = courseResult?.course?.legs?.[guideStep]?.travel;
  const guideBoarding = transitBoardingDetails(guideTravel);
  const guideInstruction = nextRouteInstruction(
    guideRoute,
    guideTravel,
    guideBoarding,
  );
  const guideTransportMode =
    guideTravel?.mode === "walk"
      ? "walk"
      : guideTravel?.mode === "car"
        ? "car"
        : guideTravel?.mode === "transit"
          ? "public_transit"
          : transportMode;
  const mapFocusIndex =
    courseConfirmed && guidanceStarted
      ? guideStep < visiblePlaces.length
        ? guideStep
        : null
      : focusedStopIndex;
  useEffect(() => {
    if (!guidanceStarted) {
      lastLiveLocation.current = null;
      setLiveLocation(null);
      setLiveLocationStatus("idle");
      arrivalRef.current = {
        targetId: null,
        enteredAt: null,
        lastLocationAt: null,
      };
      setArrivalSeconds(0);
      return undefined;
    }
    if (!navigator.geolocation) {
      setLiveLocationStatus("unavailable");
      return undefined;
    }
    let watchId = null;
    const stopWatch = () => {
      if (watchId !== null) navigator.geolocation.clearWatch(watchId);
      watchId = null;
    };
    const startWatch = () => {
      stopWatch();
      setLiveLocationStatus("requesting");
      watchId = navigator.geolocation.watchPosition(
        (position) => {
          // 실내·고층 환경에서 튀는 좌표가 도착 판정이나 경로 재탐색을
          // 일으키지 않도록 정확도가 낮은 측정값은 화면에 반영하지 않는다.
          if (
            Number.isFinite(position.coords.accuracy) &&
            position.coords.accuracy > MAX_ACCEPTED_GPS_ACCURACY_METERS
          ) {
            setLiveLocationStatus("low_accuracy");
            return;
          }
          const nextLocation = {
            latitude: position.coords.latitude,
            longitude: position.coords.longitude,
            accuracy: position.coords.accuracy,
            heading: position.coords.heading,
            updatedAt: Date.now(),
          };
          const previous = lastLiveLocation.current;
          const elapsed = Date.now() - (previous?.updatedAt ?? 0);
          if (
            !previous ||
            distanceMetersBetween(previous, nextLocation) >= 10 ||
            elapsed >= 5000
          ) {
            const movedDistance = previous
              ? distanceMetersBetween(previous, nextLocation)
              : 0;
            const gpsHeading =
              Number.isFinite(position.coords.heading) &&
              position.coords.heading >= 0
                ? position.coords.heading
                : movedDistance >= 4
                  ? bearingBetween(previous, nextLocation)
                  : null;
            if (Number.isFinite(gpsHeading)) {
              setDeviceHeading(Math.round(gpsHeading));
              document.documentElement.style.setProperty(
                "--device-heading",
                `${Math.round(gpsHeading)}deg`,
              );
            }
            lastLiveLocation.current = {
              ...nextLocation,
              updatedAt: Date.now(),
            };
            setLiveLocation(nextLocation);
          }
          setLiveLocationStatus("ready");
        },
        (error) => {
          setLiveLocationStatus(
            error.code === error.PERMISSION_DENIED ? "denied" : "unavailable",
          );
        },
        { enableHighAccuracy: true, maximumAge: 5000, timeout: 20000 },
      );
    };
    const handleVisibilityChange = () => {
      if (document.visibilityState === "visible") startWatch();
      else stopWatch();
    };
    startWatch();
    document.addEventListener("visibilitychange", handleVisibilityChange);
    window.addEventListener("pageshow", startWatch);
    return () => {
      stopWatch();
      document.removeEventListener("visibilitychange", handleVisibilityChange);
      window.removeEventListener("pageshow", startWatch);
    };
  }, [guidanceStarted]);

  useEffect(() => {
    if (!guidanceStarted) {
      setDeviceHeading(null);
      return undefined;
    }
    const handleOrientation = (event) => {
      const heading = Number.isFinite(event.webkitCompassHeading)
        ? event.webkitCompassHeading
        : Number.isFinite(event.alpha)
          ? (360 - event.alpha) % 360
          : null;
      if (heading !== null) {
        const now = Date.now();
        const previous = lastHeadingRef.current;
        const delta =
          previous.value === null
            ? 360
            : Math.abs(((heading - previous.value + 540) % 360) - 180);
        if (delta >= 5 && now - previous.updatedAt >= 250) {
          lastHeadingRef.current = { value: heading, updatedAt: now };
          document.documentElement.style.setProperty(
            "--device-heading",
            `${Math.round(heading)}deg`,
          );
          setDeviceHeading(Math.round(heading));
        }
      }
    };
    window.addEventListener(
      "deviceorientationabsolute",
      handleOrientation,
      true,
    );
    window.addEventListener("deviceorientation", handleOrientation, true);
    return () => {
      window.removeEventListener(
        "deviceorientationabsolute",
        handleOrientation,
        true,
      );
      window.removeEventListener("deviceorientation", handleOrientation, true);
    };
  }, [guidanceStarted, deviceHeading]);

  useEffect(() => {
    if (!guidanceStarted || !guideDestination || !liveLocation) return;
    const distance = distanceMetersBetween(liveLocation, guideDestination);
    const current = arrivalRef.current;
    // 지도 표시는 다소 넓은 정확도까지 허용하되, 자동 도착은 신뢰할 수 있는
    // GPS 측정값으로만 판정해 건물 안이나 맞은편 도로의 오인식을 줄인다.
    const arrivalAccuracyOk =
      !Number.isFinite(liveLocation.accuracy) ||
      liveLocation.accuracy <= MAX_ARRIVAL_GPS_ACCURACY_METERS;
    if (distance <= ARRIVAL_RADIUS_METERS && arrivalAccuracyOk) {
      if (current.targetId !== guideDestination.id || !current.enteredAt) {
        arrivalRef.current = {
          targetId: guideDestination.id,
          enteredAt: Date.now(),
          lastLocationAt: liveLocation.updatedAt,
        };
        setArrivalSeconds(0);
      } else {
        arrivalRef.current = {
          ...current,
          lastLocationAt: liveLocation.updatedAt,
        };
      }
    } else if (current.targetId === guideDestination.id) {
      arrivalRef.current = {
        targetId: guideDestination.id,
        enteredAt: null,
        lastLocationAt: liveLocation.updatedAt,
      };
      setArrivalSeconds(0);
    }
  }, [guidanceStarted, guideDestination, liveLocation]);

  useEffect(() => {
    if (!guidanceStarted || !guideDestination) return undefined;
    const timer = window.setInterval(() => {
      const current = arrivalRef.current;
      if (current.targetId !== guideDestination.id || !current.enteredAt)
        return;
      // 오래된 GPS 좌표만 남아 있을 때 자동 도착 처리되는 것을 막는다.
      if (
        !current.lastLocationAt ||
        Date.now() - current.lastLocationAt > 20000
      ) {
        setArrivalSeconds(0);
        return;
      }
      const elapsedSeconds = Math.floor(
        (Date.now() - current.enteredAt) / 1000,
      );
      setArrivalSeconds(Math.min(ARRIVAL_DWELL_SECONDS, elapsedSeconds));
      if (elapsedSeconds >= ARRIVAL_DWELL_SECONDS) {
        arrivalRef.current = {
          targetId: null,
          enteredAt: null,
          lastLocationAt: null,
        };
        setArrivalSeconds(0);
        setGuideStep((currentStep) =>
          Math.min(currentStep + 1, guideStopCount),
        );
      }
    }, 1000);
    return () => window.clearInterval(timer);
  }, [guidanceStarted, guideDestination, guideStopCount]);

  useEffect(() => {
    if (!guidanceStarted || !guideDestination || !guideOrigin) {
      if (!guidanceStarted) setGuideRoute(null);
      return undefined;
    }
    const previous = lastGuideRouteRequest.current;
    const targetChanged =
      previous?.targetId !== guideDestination.id ||
      previous?.transportMode !== guideTransportMode;
    const deviationThreshold = guideTransportMode === "walk" ? 45 : 90;
    const deviation = guideRoute
      ? distanceToRouteMeters(guideOrigin, guideRoute)
      : Infinity;
    if (!targetChanged && guideRoute && deviation > deviationThreshold)
      routeDeviationRef.current.count += 1;
    else if (!targetChanged) routeDeviationRef.current.count = 0;
    const now = Date.now();
    const shouldReroute =
      routeDeviationRef.current.count >= 2 &&
      now - routeDeviationRef.current.lastRerouteAt >= 20000;
    if (!targetChanged && guideRoute && !shouldReroute) return undefined;
    let cancelled = false;
    lastGuideRouteRequest.current = {
      ...guideOrigin,
      targetId: guideDestination.id,
      transportMode: guideTransportMode,
    };
    if (targetChanged) {
      setGuideRoute(null);
      routeDeviationRef.current = { count: 0, lastRerouteAt: 0 };
    } else {
      routeDeviationRef.current = { count: 0, lastRerouteAt: now };
    }
    setGuideRouteStatus(shouldReroute ? "rerouting" : "loading");
    requestRoutePreview({
      startLatitude: guideOrigin.latitude,
      startLongitude: guideOrigin.longitude,
      endLatitude: guideDestination.latitude,
      endLongitude: guideDestination.longitude,
      transportMode: guideTransportMode,
    })
      .then((route) => {
        if (!cancelled) {
          setGuideRoute(route);
          setGuideRouteStatus("ready");
        }
      })
      .catch(() => {
        if (!cancelled) setGuideRouteStatus("error");
      });
    return () => {
      cancelled = true;
    };
  }, [
    guidanceStarted,
    guideDestination,
    guideOrigin,
    guideTransportMode,
    guideRoute,
  ]);
  const returnToRegions = () => {
    calculationRequest.current += 1;
    setPlaceMode(false);
    setCalculated(false);
    setCourseResult(null);
    setCourseConfirmed(false);
    setGuidanceStarted(false);
    setGuideStep(0);
    setFocusedStopIndex(null);
    setCalculationStatus("idle");
    setCalculationError("");
    setPinnedCourseArea(null);
  };
  const resetCourseSelection = () => {
    calculationRequest.current += 1;
    setCalculated(false);
    setCourseResult(null);
    setCourseConfirmed(false);
    setGuidanceStarted(false);
    setGuideStep(0);
    setFocusedStopIndex(null);
    setCalculationStatus("idle");
    setCalculationError("");
    setProactivePromptMode(null);
    setProactiveDismissed(false);
    setLiveProactiveShown(false);
  };
  const confirmCourse = async (options = {}) => {
    if (calculationStatus === "loading") return;
    if (
      options?.skipProactive !== true &&
      proactiveFitsCourse &&
      !proactiveDismissed
    ) {
      setProactivePromptMode("confirm");
      return;
    }
    if (!availableTimeMinutes) {
      setCalculationStatus("error");
      setCalculationError(
        "사용 가능한 시간이 없어요. 이전 화면에서 종료 시각이나 여유 시간을 다시 입력해 주세요.",
      );
      return;
    }
    setCalculationStatus("loading");
    setCalculationError("");
    try {
      const activitySequence = requestedActivitySequence;
      const preserveActivityOrder = hasOrderedActivitySequence(activitySequence);
      const orderedPlacesToConfirm = preserveActivityOrder
        ? orderPlacesByActivitySequence(selectedPlaces, activitySequence)
        : [...selectedPlaces];
      // 확정 지도는 이전 화면의 캐시가 아니라 최신 혼합 이동 정책으로 다시
      // 계산한 코스를 사용한다. 백엔드의 구간 캐시는 재사용돼 응답은 빠르다.
      const course = await requestCourse({
        startLocation,
        selectedPlaces: orderedPlacesToConfirm,
        availableTimeMinutes,
        departureDatetime: result.recommendationContext?.departure_datetime,
        endLocation:
          result.mapContext?.end ?? result.recommendationContext?.end_location,
        transportMode,
        optimizeOrder: !preserveActivityOrder,
        fresh: true,
      });
      if (course.status !== "FEASIBLE") {
        setCourseResult((current) => ({ ...current, course }));
        setCalculationStatus("warning");
        setCalculationError(
          "최신 경로로 다시 계산하니 예정 시간보다 여유가 부족해요.",
        );
        return;
      }
      setCourseResult((current) => ({ ...current, course }));
      setSelectedPlaces(orderedPlacesToConfirm);
      setFocusedStopIndex(null);
      setCourseConfirmed(true);
      setGuidanceStarted(false);
      setGuideStep(0);
      setSheetExpanded(false);
      setCalculationStatus("ready");
      if (account?.token) {
        // 확정은 개인화에서 가장 신뢰할 수 있는 행동이므로 코스의 각 활동을 기록한다.
        orderedPlacesToConfirm.forEach((place) => {
          void recordInteraction(account.token, {
            event_type: "course_confirm",
            place_key: placeIdentity(place),
            place_name: place.name,
            category: place.category,
            context_data: {
              area_name: selectedArea?.name ?? null,
              transport_mode: transportMode,
            },
          }).catch(() => {});
        });
        setServerSaveStatus("saving");
        try {
          await saveCourse(account.token, {
            title: `${selectedArea?.name ?? "추천 지역"} 코스`,
            area_name: selectedArea?.name ?? null,
            course_data: {
              selected_places: orderedPlacesToConfirm,
              course,
              transport_mode: transportMode,
              recommendation_response: response,
            },
          });
          setServerSaveStatus("saved");
        } catch {
          setServerSaveStatus("error");
        }
      }
    } catch (error) {
      setCalculationStatus("error");
      setCalculationError(
        error.message ?? "확정 경로를 다시 계산하지 못했어요.",
      );
    }
  };
  const dismissProactivePrompt = () => {
    const wasConfirmation = proactivePromptMode === "confirm";
    setProactivePromptMode(null);
    setProactiveDismissed(true);
    if (wasConfirmation) void confirmCourse({ skipProactive: true });
  };
  useEffect(() => {
    if (
      !guidanceStarted ||
      !liveLocation ||
      !proactiveOffer?.place ||
      proactiveDismissed ||
      liveProactiveShown
    )
      return;
    const distance = distanceMetersBetween(liveLocation, proactiveOffer.place);
    const hasTime =
      Number(courseResult?.course?.remaining_time_minutes ?? 0) >=
      proactiveExtraMinutes;
    if (distance <= 500 && hasTime) {
      setLiveProactiveShown(true);
      setProactivePromptMode("live");
    }
  }, [
    guidanceStarted,
    liveLocation,
    proactiveOffer,
    proactiveDismissed,
    liveProactiveShown,
    courseResult?.course?.remaining_time_minutes,
    proactiveExtraMinutes,
  ]);
  const startGuidance = async () => {
    if (
      typeof DeviceOrientationEvent !== "undefined" &&
      typeof DeviceOrientationEvent.requestPermission === "function"
    ) {
      try {
        await DeviceOrientationEvent.requestPermission();
      } catch {
        /* 방향 권한 없이도 위치 안내는 계속한다. */
      }
    }
    setGuideStep(0);
    setGuidanceStarted(true);
  };

  return (
    <main
      className="results-page"
      style={{ "--results-sidebar-width": `${sidebarWidth}px` }}
    >
      <KakaoCourseMap
        mapContext={result.mapContext}
        selectedArea={selectedArea}
        areaRoute={selectedAreaRoute}
        walkingRouteLoading={isWalkingRouteLoading}
        selectedPlaces={mapVisiblePlaces}
        previewPlaces={hoveredCoursePlaces}
        focusedStopIndex={mapFocusIndex}
        course={calculated ? courseResult?.course : null}
        courseConfirmed={courseConfirmed}
        liveLocation={liveLocation}
        guideRoute={guideRoute}
        guidanceActive={guidanceStarted}
        guidanceStartLocation={guideOrigin}
        guidanceStartLabel={guideOriginLabel}
        deviceHeading={deviceHeading}
        sheetExpanded={sheetExpanded}
      />
      <button
        className="results-divider"
        type="button"
        aria-label="추천 목록과 지도 너비 조절"
        onPointerDown={handleDividerPointerDown}
        onPointerMove={handleDividerPointerMove}
        onPointerUp={handleDividerPointerUp}
      >
        <i />
      </button>
      <aside className={`results-sidebar${placeMode ? " is-place-mode" : ""}`}>
        {routeCacheKey && routeErrors[routeCacheKey] && (
          <p className="place-status is-error">
            상세 경로를 확인하지 못해 예상 이동시간을 표시하고 있어요. 잠시 후
            다시 시도해 주세요.
          </p>
        )}
        <header className="map-topbar" ref={mapTopbarRef}>
          <button
            className={`results-back${placeMode ? " has-label" : " is-icon-only"}`}
            type="button"
            aria-label={
              canReturnToAutoCourses
                ? "자동 코스 후보로 돌아가기"
                : placeMode
                  ? "추천 경로로 돌아가기"
                  : "이전 화면으로 돌아가기"
            }
            onClick={handleResultsBack}
          >
            <img src={iconBack} alt="" aria-hidden="true" />
            {placeMode && <b>추천 경로</b>}
          </button>
          <button
            className="map-topbar-title map-home-button"
            type="button"
            onClick={onBack}
            aria-label="코알라 첫 화면으로 돌아가기"
          >
            {placeMode
              ? (selectedArea?.name ?? "지역 코스")
              : "KOALA 추천 경로"}
          </button>
          <button
            className="result-account-button"
            type="button"
            onClick={onOpenAccount}
          >
            {account?.user ? account.user.nickname : "로그인"}
          </button>
          {!guidanceStarted && (
            <button
              className="transport-current-trigger"
              type="button"
              aria-label={`현재 이동수단 ${selectedTransport.label}. 변경하기`}
              aria-expanded={transportMenuOpen}
              onClick={() => setTransportMenuOpen((open) => !open)}
            >
              <i aria-hidden="true">
                <img src={selectedTransport.icon} alt="" />
              </i>
              <span>{selectedTransport.label}</span>
              <b aria-hidden="true">⌄</b>
            </button>
          )}
          {!guidanceStarted && (
            <section
              className={`map-transport-selector${transportMenuOpen ? " is-open" : ""}`}
              aria-label="이동수단 선택"
            >
              {transportOptions.map((option) => (
                <button
                  key={option.id}
                  type="button"
                  className={transportMode === option.id ? "is-active" : ""}
                  aria-pressed={transportMode === option.id}
                  onClick={() => {
                    setTransportMenuOpen(false);
                    if (transportMode === option.id) return;
                    setTransportMode(option.id);
                    setCalculated(false);
                    setCourseResult(null);
                    setCourseConfirmed(false);
                    setGuidanceStarted(false);
                    setGuideStep(0);
                    setCalculationStatus("idle");
                    setCalculationError("");
                    if (selectedPlaces.length && availableTimeMinutes) {
                      void handleCalculate(selectedPlaces, option.id);
                    }
                  }}
                >
                  <i aria-hidden="true">
                    <img src={option.icon} alt="" />
                  </i>
                  <span>{option.label}</span>
                </button>
              ))}
            </section>
          )}
        </header>
        {rankingAreas.length > 0 && (
          <section
            className={`map-ranking-sheet${placeMode ? " is-place-mode" : " is-region-mode"}${sheetExpanded ? " is-expanded" : ""}${sheetMinimized && !placeMode ? " is-minimized" : ""}${calculated && !sheetExpanded ? " is-course-collapsed" : ""}${guideIsComplete ? " is-guide-complete" : ""}`}
          >
            <button
              className="sheet-handle"
              type="button"
              aria-label={
                sheetMinimized
                  ? "추천 지역 목록 기본 크기로 올리기"
                  : sheetExpanded
                    ? "추천 지역 목록 내리기"
                    : "추천 지역 목록 펼치기"
              }
              aria-expanded={sheetExpanded}
              onPointerDown={handleSheetPointerDown}
              onPointerMove={handleSheetPointerMove}
              onPointerUp={handleSheetPointerUp}
              onPointerCancel={handleSheetPointerCancel}
              onClick={() => {
                if (didDrag.current) {
                  didDrag.current = false;
                  return;
                }
                if (sheetMinimized) {
                  setSheetMinimized(false);
                  return;
                }
                setSheetExpanded(!sheetExpanded);
              }}
            >
              <i />
            </button>
            {placeMode ? (
              <>
                <div className="place-picker-head">
                  <div>
                    <h2>
                      {guideIsComplete
                        ? "코스 안내가 끝났어요"
                        : guidanceStarted
                          ? "코스 안내 중이에요"
                          : courseConfirmed
                            ? adventureExperience?.mode === "course"
                              ? "랜덤 코스를 완성했어요"
                              : adventureExperience?.mode === "quest"
                                ? "오늘의 퀘스트 코스예요"
                                : mysteryMode
                                  ? "미스터리 안내를 시작해요"
                                  : "코스가 확정됐어요"
                            : calculated
                              ? "코스가 완성됐어요"
                              : autoCourseCalculating
                                ? "가능한 코스를 확인하고 있어요"
                                : autoCourseMode
                                  ? "코알라가 코스를 준비했어요"
                                  : `${selectedArea?.name ?? "추천 지역"}에서 어디를 가볼까요?`}
                    </h2>
                    <p>
                      {guideIsComplete
                        ? "오늘 이동을 완료했어요"
                          : guidanceStarted
                            ? mysteryMode
                              ? "다음 행동만 따라가면 목적지에서 장소가 공개돼요"
                              : "도착하면 다음 장소를 안내해 드려요"
                          : courseConfirmed
                            ? "전체 동선을 마지막으로 확인해 보세요"
                            : calculated
                              ? "지도에서 전체 동선을 확인해 보세요"
                              : autoCourseCalculating
                                ? "보여드리기 전에 실제 이동시간까지 계산해요"
                                : autoCourseMode
                                  ? "화면에 보이는 장소 그대로 코스가 확정돼요"
                                  : ""}
                    </p>
                  </div>
                  <span>
                    {guidanceStarted
                      ? `${Math.min(guideStep + 1, guideStopCount)}/${guideStopCount}`
                      : autoCourseCalculating
                        ? "검증 중"
                        : autoCourseMode
                          ? `${verifiedAutoCourses.length}코스`
                          : `${selectedPlaces.length}곳`}
                  </span>
                </div>
                {calculated && courseConfirmed && guidanceStarted ? (
                  <div className="course-guide">
                    {guideIsComplete ? (
                      <div className="guide-complete">
                        <img
                          className="guide-complete-koala"
                          src={koalaComplete}
                          alt="추천 완료를 알리는 코알라"
                        />
                        <b>오늘의 빈 시간을 잘 채웠어요</b>
                        <p>
                          {visiblePlaces.length}곳 방문 · 이동{" "}
                          {formatCalculatedMinutes(
                            courseResult?.course?.total_travel_time_minutes,
                          )} · 머문 시간{" "}
                          {formatCalculatedMinutes(
                            courseResult?.course?.total_stay_time_minutes,
                          )}
                        </p>
                        <strong>
                          {account?.token
                            ? serverSaveStatus === "saved"
                              ? "내 코스에 저장됐어요"
                              : "코스 저장을 확인하고 있어요"
                            : "로그인하면 오늘 코스를 보관할 수 있어요"}
                        </strong>
                        <button type="button" onClick={onBack}>
                          새 코스 추천받기
                        </button>
                        <button
                          className="guide-complete-secondary"
                          type="button"
                          onClick={() => {
                            setGuidanceStarted(false);
                            setGuideStep(0);
                            setSheetExpanded(true);
                          }}
                        >
                          방문한 코스 다시 보기
                        </button>
                      </div>
                    ) : (
                      <>
                        <div className="guide-progress">
                          <span>
                            {guideRouteStatus === "rerouting"
                              ? "경로를 벗어나 다시 찾는 중"
                              : arrivalSeconds > 0
                                ? `도착 확인 중 · ${ARRIVAL_DWELL_SECONDS - arrivalSeconds}초`
                                : liveLocationStatus === "ready"
                                  ? "현재 위치로 안내 중"
                                  : liveLocationStatus === "low_accuracy"
                                    ? "현재 위치 신호가 약해 확인 중"
                                    : liveLocationStatus === "unavailable"
                                      ? "기존 경로로 안내 중"
                                      : "현재 위치 확인 중"}
                          </span>
                          <b>
                            {guideStep + 1} / {guideStopCount}
                          </b>
                        </div>
                        <section
                          className="guide-current"
                          style={{
                            "--place-color": guidePlace
                              ? courseStopColors[
                                  guideStep % courseStopColors.length
                                ]
                              : "#ef6259",
                          }}
                        >
                          <small>
                            {guidePlace
                              ? mysteryMode && !mysteryRevealed
                                ? "다음 행동"
                                : "다음 장소"
                              : "다음 일정"}
                          </small>
                          <h3>
                            {guidePlace
                              ? mysteryName(guidePlace, guideStep)
                              : "다음 일정 장소"}
                          </h3>
                          <strong>{formatLegTransport(guideTravel)}</strong>
                          <div
                            className={`guide-next-action${sheetExpanded ? "" : " is-compact"}`}
                          >
                            {sheetExpanded && <small>다음 행동</small>}
                            <b>{guideInstruction}</b>
                          </div>
                          {sheetExpanded && guideBoarding.length > 0 && (
                            <div
                              className="guide-boarding"
                              aria-label="탑승할 대중교통"
                            >
                              {guideBoarding.map((boarding) => (
                                <span
                                  key={`${boarding.type}-${boarding.vehicle}`}
                                >
                                  <i aria-hidden="true">
                                    {boarding.type === "SUBWAY" ? "🚇" : "🚌"}
                                  </i>
                                  <b>{boarding.vehicle}</b>
                                  {boarding.minutes && (
                                    <small>약 {boarding.minutes}분</small>
                                  )}
                                </span>
                              ))}
                            </div>
                          )}
                          {sheetExpanded && (
                            <p>
                              {guidePlace
                                ? `도착 후 약 ${formatMinutes(guidePlace.stayMinutes)} 머무르기`
                                : "약속 장소까지 이동해요"}
                            </p>
                          )}
                        </section>
                        {mysteryMode && guidePreviousPlace && (
                          <div className="mystery-arrival-card" role="status">
                            <small>방금 도착한 장소</small>
                            <b>{guidePreviousPlace.name}</b>
                            <span>
                              {QUEST_COPY[guidePreviousPlace.category] ??
                                "이곳을 천천히 둘러보세요."}
                            </span>
                          </div>
                        )}
                        <div className="guide-stops">
                          {visiblePlaces.map((place, index) => (
                            <button
                              key={place.id}
                              type="button"
                              className={guideStep === index ? "is-active" : ""}
                              style={{
                                "--place-color":
                                  courseStopColors[
                                    index % courseStopColors.length
                                  ],
                              }}
                              onClick={() => setGuideStep(index)}
                            >
                              <i>{index + 1}</i>
                              <span>{mysteryName(place, index)}</span>
                            </button>
                          ))}
                          {result.mapContext?.end && (
                            <button
                              type="button"
                              className={
                                guideStep === visiblePlaces.length
                                  ? "is-active is-end"
                                  : "is-end"
                              }
                              onClick={() => setGuideStep(visiblePlaces.length)}
                            >
                              <i>✓</i>
                              <span>다음 일정</span>
                            </button>
                          )}
                        </div>
                        <button
                          className="guide-next-button"
                          type="button"
                          onClick={() =>
                            setGuideStep((current) =>
                              Math.min(current + 1, guideStopCount),
                            )
                          }
                        >
                          {mysteryMode && guideBoarding.length
                            ? "내렸어요"
                            : "도착했어요"}{" "}
                          <span>→</span>
                        </button>
                        {mysteryMode && !mysteryRevealed && (
                          <button
                            className="mystery-reveal-button"
                            type="button"
                            onClick={() => setMysteryRevealed(true)}
                          >
                            길을 잃었어요 · 목적지 확인
                          </button>
                        )}
                        <button
                          className="guide-reset-button"
                          type="button"
                          onClick={resetCourseSelection}
                        >
                          코스 다시 설정하기
                        </button>
                      </>
                    )}
                  </div>
                ) : calculated ? (
                  <div className="place-result">
                    <div className="course-total">
                      <b>
                        {courseConfirmed
                          ? "이 코스를 저장했어요"
                          : courseResult?.course?.status === "FEASIBLE"
                            ? "시간 안에 방문 가능해요"
                            : "예정 시간보다 여유가 부족해요"}
                      </b>
                      <span>
                        이동{" "}
                        {formatCalculatedMinutes(
                          courseResult?.course?.total_travel_time_minutes,
                        )}
                        · 체류{" "}
                        {formatCalculatedMinutes(
                          courseResult?.course?.total_stay_time_minutes,
                        )}
                      </span>
                    </div>
                    <div className="course-compact-route">
                      <b>
                        {visiblePlaces
                          .map((place, index) => mysteryName(place, index))
                          .join(" → ")}
                      </b>
                      <button
                        type="button"
                        aria-expanded={sheetExpanded}
                        onClick={(event) => {
                          event.stopPropagation();
                          setFocusedStopIndex(null);
                          setSheetExpanded((expanded) => !expanded);
                        }}
                      >
                        전체 코스 보기
                      </button>
                    </div>
                    {adventureExperience?.mode === "quest" && (
                      <section className="course-quest-list" aria-label="오늘의 퀘스트">
                        <div>
                          <small>오늘의 작은 도전</small>
                          <b>
                            {Object.values(questProgress).filter(
                              (status) => status === "done",
                            ).length} / {visiblePlaces.length} 완료
                          </b>
                        </div>
                        {visiblePlaces.map((place, index) => {
                          const status = questProgress[place.id];
                          return (
                            <article key={place.id} className={status ? `is-${status}` : ""}>
                              <span>{index + 1}</span>
                              <p>
                                <strong>{place.name}</strong>
                                <small>
                                  {questForPlace(
                                    place,
                                    adventureExperience.quest,
                                    index,
                                  )}
                                </small>
                              </p>
                              <div>
                                <button
                                  type="button"
                                  onClick={() =>
                                    setQuestProgress((current) => ({
                                      ...current,
                                      [place.id]: "done",
                                    }))
                                  }
                                >
                                  완료했어요
                                </button>
                                <button
                                  type="button"
                                  onClick={() =>
                                    setQuestProgress((current) => ({
                                      ...current,
                                      [place.id]: "skipped",
                                    }))
                                  }
                                >
                                  건너뛰기
                                </button>
                              </div>
                            </article>
                          );
                        })}
                      </section>
                    )}
                    <div className="course-edit-actions">
                      <button
                        className="place-calc-button is-active course-reset-button"
                        type="button"
                        onClick={resetCourseSelection}
                      >
                        장소 조정 <span>↺</span>
                      </button>
                      {response?._client_mode === "auto-course" &&
                        !courseConfirmed && (
                        <button
                          className="auto-course-return"
                          type="button"
                          onClick={returnToAutoCourses}
                        >
                          새 코스 추천
                        </button>
                        )}
                      {adventureExperience?.mode === "course" && courseConfirmed && (
                        <button
                          className="auto-course-return"
                          type="button"
                          onClick={returnToRegions}
                        >
                          한 번 더 뽑기
                        </button>
                      )}
                    </div>
                    <div className="course-timeline">
                      <b>지도에 표시된 실제 이동 동선</b>
                      {visiblePlaces.map((place, index) => (
                        <div
                          className="course-timeline-stop"
                          key={place.id}
                          style={{
                            "--place-color":
                              courseStopColors[index % courseStopColors.length],
                          }}
                        >
                          <div className="course-timeline-leg">
                            <span>
                              {index === 0
                                ? "현재 위치"
                                : mysteryName(visiblePlaces[index - 1], index - 1)}{" "}
                              → {mysteryName(place, index)}
                            </span>
                            <small>
                              {formatLegTransport(
                                courseResult?.course?.legs?.[index]?.travel,
                              )}
                            </small>
                          </div>
                          <button
                            className={`place-result-route${focusedStopIndex === index ? " is-focused" : ""}`}
                            type="button"
                            onClick={() => setFocusedStopIndex(index)}
                          >
                            <span>{index + 1}</span>
                            <strong>{mysteryName(place, index)}</strong>
                            <small>
                              {place.categoryLabel} · {place.stayMinutes}분
                              머무르기
                              {availabilityLabel(place.availability) &&
                                ` · ${availabilityLabel(place.availability)}`}
                            </small>
                          </button>
                        </div>
                      ))}
                      {result.mapContext?.end &&
                        courseResult?.course?.legs?.[visiblePlaces.length] && (
                          <div className="course-timeline-leg is-final">
                            <span>
                              {visiblePlaces.at(-1)?.name} → 다음 일정
                            </span>
                            <small>
                              {formatLegTransport(
                                courseResult.course.legs[visiblePlaces.length]
                                  .travel,
                              )}
                            </small>
                          </div>
                        )}
                    </div>
                    <div
                      className={`place-warning${courseResult?.course?.status === "INFEASIBLE" || calculationError ? " is-warning" : ""}`}
                    >
                      {calculationError ||
                        (courseResult?.course
                          ? `총 ${courseResult.course.total_required_minutes}분 · ${Math.abs(courseResult.course.remaining_time_minutes)}분 ${courseResult.course.remaining_time_minutes >= 0 ? "여유" : "초과"}`
                          : "실제 경로 시간 계산 불가")}
                    </div>
                    {autoCourseNotice && (
                      <div className="auto-course-adjustment">
                        ✓ {autoCourseNotice}
                      </div>
                    )}
                    {courseResult?.validation?.travel_time_precheck
                      ?.warning && (
                      <div className="place-warning is-warning">
                        이동시간을 포함하면 일정이 빠듯해요. 최적 경로를
                        확인하거나 장소 수를 줄여주세요.
                      </div>
                    )}
                    {visiblePlaces.some((place) =>
                      ["closed", "event_ended"].includes(
                        place.availability?.status,
                      ),
                    ) && (
                      <div className="place-warning is-warning">
                        도착할 때 운영이 끝난 장소가 있어요. 확정 전에 다른
                        장소를 권장해요.
                      </div>
                    )}
                    {!courseConfirmed && replacementPlace && (
                      <div className="course-replacement">
                        <div className="replacement-target-picker">
                          <strong>어느 장소를 바꿀까요?</strong>
                          <div>
                            {visiblePlaces.map((place, index) => (
                              <button
                                key={place.id}
                                type="button"
                                className={
                                  replacementTarget?.id === place.id
                                    ? "is-active"
                                    : ""
                                }
                                onClick={() => {
                                  setFocusedStopIndex(index);
                                  setReplacementPreviewOpen(false);
                                }}
                              >
                                {index + 1}. {place.name}
                              </button>
                            ))}
                          </div>
                        </div>
                        <button
                          type="button"
                          onClick={() =>
                            setReplacementPreviewOpen((open) => !open)
                          }
                        >
                          <b>{replacementTarget.name}</b> 바꾸기{" "}
                          <span>
                            {replacementPreviewOpen ? "접기" : "후보 보기"}
                          </span>
                        </button>
                        {replacementPreviewOpen && (
                          <div>
                            <span
                              className={`place-category-icon${replacementPlace.imageUrl ? " has-image" : ""}`}
                            >
                              {replacementPlace.categoryIcon}
                              {replacementPlace.imageUrl && (
                                <img
                                  src={replacementPlace.imageUrl}
                                  alt=""
                                  loading="lazy"
                                  onError={(event) => {
                                    event.currentTarget.style.display = "none";
                                  }}
                                />
                              )}
                            </span>
                            <p>
                              <small>{replacementTarget.name} 대신 추천</small>
                              <b>{replacementPlace.name}</b>
                              <em>{recommendationReason(replacementPlace)}</em>
                            </p>
                            <button type="button" onClick={confirmReplacement}>
                              이 장소로 교체
                            </button>
                          </div>
                        )}
                      </div>
                    )}
                    {courseResult?.course?.status === "FEASIBLE" &&
                      !courseConfirmed && (
                        <button
                          className="place-calc-button is-active course-finalize-button"
                          type="button"
                          disabled={calculationStatus === "loading"}
                          onClick={confirmCourse}
                        >
                          {calculationStatus === "loading"
                            ? "최적 경로 확인 중…"
                            : "이 코스로 확정하기"}{" "}
                          {calculationStatus !== "loading" && <span>→</span>}
                        </button>
                      )}
                    {courseConfirmed && (
                      <button
                        className="place-calc-button is-active course-finalize-button"
                        type="button"
                        onClick={startGuidance}
                      >
                        안내 시작 <span>→</span>
                      </button>
                    )}
                    {courseConfirmed && account?.token && (
                      <p className="server-save-status">
                        {serverSaveStatus === "saving"
                          ? "계정에 코스를 저장하는 중…"
                          : serverSaveStatus === "saved"
                            ? "계정에 코스를 저장했어요."
                            : serverSaveStatus === "error"
                              ? "기기에는 남겼지만 서버 저장은 실패했어요."
                              : ""}
                      </p>
                    )}
                  </div>
                ) : autoCourseMode ? (
                  <div className="auto-course-picker">
                    {(placeStatus === "idle" || placeStatus === "loading") && (
                      <div className="auto-course-loading" role="status">
                        <img src={koalaSearching} alt="장소를 찾는 코알라" />
                        <strong>코알라가 장소를 고르고 있어요</strong>
                        <p>지도와 별개로 주변 장소를 먼저 준비하고 있어요.</p>
                        <span>
                          <b />
                        </span>
                      </div>
                    )}
                    {placeStatus === "error" && (
                      <p className="place-status is-error">{placeError}</p>
                    )}
                    {autoCourseCalculating &&
                      verifiedAutoCourses.length > 0 && (
                        <p
                          className="auto-course-background-status"
                          role="status"
                        >
                          실제 이동시간을 확인하고 있어요
                        </p>
                      )}
                    {placeStatus === "ready" &&
                      verifiedAutoCourses.map((candidate, candidateIndex) => (
                        <button
                          className={`auto-course-card is-${candidate.id}${selectedAutoCourseId === candidate.id ? " is-selected" : ""}`}
                          key={candidate.id}
                          type="button"
                          disabled={
                            selectedAutoCourseId === candidate.id &&
                            autoCourseCalculating
                          }
                          onMouseEnter={() =>
                            setHoveredCoursePlaces(candidate.places)
                          }
                          onMouseLeave={() => setHoveredCoursePlaces([])}
                          onFocus={() =>
                            setHoveredCoursePlaces(candidate.places)
                          }
                          onBlur={() => setHoveredCoursePlaces([])}
                          onClick={() => chooseAutoCourse(candidate)}
                        >
                          <i aria-hidden="true">
                            <small>{candidateIndex + 1}</small>
                            {candidate.icon}
                            {candidate.places.find(
                              (place) => place.imageUrl,
                            ) && (
                              <img
                                src={
                                  candidate.places.find(
                                    (place) => place.imageUrl,
                                  ).imageUrl
                                }
                                alt=""
                                loading="lazy"
                                onError={(event) => {
                                  event.currentTarget.style.display = "none";
                                }}
                              />
                            )}
                          </i>
                          <span>
                            <strong>{candidate.title}</strong>
                            <small>{candidate.description}</small>
                            <span className="auto-course-badges">
                              {candidate.places.some(
                                (place) => place.sourceKind === "popup",
                              ) && <b>팝업 포함</b>}
                              {candidate.places.some(
                                (place) => place.sourceKind === "culture",
                              ) && <b>문화행사</b>}
                            </span>
                            <b>
                              {candidate.places.map((place, placeIndex) => (
                                <span key={place.id}>
                                  <em>{placeIndex + 1}</em>
                                  {place.name}
                                </span>
                              ))}
                            </b>
                            <span className="auto-course-time">
                              예상 이동 {candidate.estimatedTravelMinutes}분 ·
                              체류 {candidate.estimatedStayMinutes}분
                            </span>
                          </span>
                          <em>선택해서 실제 경로 확인</em>
                        </button>
                      ))}
                    {!autoCourseCalculating && autoCourseNotice && (
                      <div className="auto-course-adjustment">
                        {autoCourseNotice}
                      </div>
                    )}
                    {placeStatus === "ready" &&
                      !autoCourseCalculating &&
                      !verifiedAutoCourses.length && (
                        <p className="place-status">
                          코스를 만들 장소가 부족해요. 장소를 직접 골라주세요.
                        </p>
                      )}
                    {calculationError && (
                      <p className="place-status is-error">
                        {calculationError}
                      </p>
                    )}
                    <button
                      className="auto-course-manual"
                      type="button"
                      onClick={() => setAutoCourseMode(false)}
                    >
                      장소를 직접 고를게요
                    </button>
                  </div>
                ) : (
                  <>
                    {placeStatus === "loading" && (
                      <p className="place-status">
                        주변 실제 장소를 찾고 있어요…
                      </p>
                    )}
                    {placeStatus === "error" && (
                      <p className="place-status is-error">
                        {placeError || "장소를 불러오지 못했어요."}
                      </p>
                    )}
                    {placeStatus === "ready" && !places.length && (
                      <p className="place-status">추천할 장소가 아직 없어요.</p>
                    )}
                    {selectedPlaces.length > 0 ? (
                      <section
                        className={`time-budget${timeGaugeOver ? " is-over" : ""}`}
                        aria-label={`사용 가능 ${availableTimeMinutes}분 중 ${timeCalculationLabel}`}
                      >
                      <div>
                        <b>
                          {displayedTotal == null
                            ? travelEstimate.status === "loading"
                              ? "이동시간 계산 중"
                              : "이동시간 확인 불가"
                            : timeGaugeOver
                            ? `${displayedTotal - availableTimeMinutes}분 초과`
                            : `${displayedTotal}분 사용`}
                        </b>
                        <span>총 {availableTimeMinutes}분</span>
                      </div>
                      <div className="time-budget-track">
                        {displayedTravel > 0 && (
                          <i
                            className="is-travel"
                            style={{
                              width: `${Math.min(100, (displayedTravel / Math.max(displayedTotal, availableTimeMinutes)) * 100)}%`,
                            }}
                            title={`이동 ${displayedTravel}분`}
                          />
                        )}
                        {selectedPlaces.map((place) => (
                          <i
                            key={place.id}
                            className={`is-${place.category}`}
                            style={{
                              width: `${Math.min(100, (place.stayMinutes / Math.max(displayedTotal, availableTimeMinutes)) * 100)}%`,
                            }}
                            title={`${place.name} ${place.stayMinutes}분`}
                          />
                        ))}
                      </div>
                      <small>
                        {hasActualTime
                          ? "파랑은 실제 경로 이동 · 나머지는 장소에서 보내는 시간"
                          : travelEstimate.status === "ready"
                            ? "선택한 교통수단의 실제 경로로 미리 계산했어요"
                            : travelEstimate.status === "loading"
                              ? "선택한 교통수단의 실제 경로를 계산하고 있어요"
                              : "이동 경로를 확인할 수 있어야 총시간을 표시해요"}
                      </small>
                      </section>
                    ) : (
                      <div className="time-budget-empty">
                        <span>사용 가능한 시간</span>
                        <b>{formatMinutes(availableTimeMinutes)}</b>
                      </div>
                    )}
                    {selectedPlaces.length > 0 && (
                      <div
                        className={`place-picker-summary${calculationStatus === "warning" ? " is-warning" : ""}`}
                      >
                        <b>
                          {calculationIsEstimated
                            ? "일부 예상"
                            : hasActualTime
                              ? "실제 계산"
                              : "사전 계산"}{" "}
                          {displayedTotal == null ? "확인 중" : `${displayedTotal}분`}
                        </b>
                        <span>
                          {displayedTotal == null
                            ? travelEstimate.status === "loading"
                              ? "실제 이동 경로를 확인하고 있어요"
                              : "이동시간을 확인할 수 없어요"
                            : `이동 ${displayedTravel}분 · 체류 ${displayedStay}분${calculationIsEstimated ? " · 실패 구간은 예상시간 적용" : ""}`}
                        </span>
                      </div>
                    )}
                    {savedCoursesForArea.length > 0 && (
                      <button
                        className="saved-course-button"
                        type="button"
                        onClick={() => {
                          const saved = savedCoursesForArea[0];
                          setSelectedPlaces(saved.selectedPlaces);
                          setCourseResult({
                            validation: saved.validation,
                            course: saved.course,
                          });
                          setCalculated(true);
                          setCalculationStatus("ready");
                        }}
                      >
                        최근 계산한 코스 다시 보기
                      </button>
                    )}
                    {hasEventPlaces && (
                      <div
                        className="place-source-filters"
                        aria-label="추천 장소 종류"
                      >
                        <button
                          type="button"
                          className={
                            placeSourceFilter === "all" ? "is-active" : ""
                          }
                          onClick={() => setPlaceSourceFilter("all")}
                        >
                          전체
                        </button>
                        <button
                          type="button"
                          className={
                            placeSourceFilter === "general" ? "is-active" : ""
                          }
                          onClick={() => setPlaceSourceFilter("general")}
                        >
                          일반 장소
                        </button>
                        <button
                          type="button"
                          className={
                            placeSourceFilter === "events" ? "is-active" : ""
                          }
                          onClick={() => setPlaceSourceFilter("events")}
                        >
                          팝업·행사
                        </button>
                      </div>
                    )}
                    <div
                      className="ranking-scroll place-scroll"
                      ref={placeScrollRef}
                      onScroll={(event) => {
                        const target = event.currentTarget;
                        const distanceToBottom =
                          target.scrollHeight - target.scrollTop - target.clientHeight;
                        if (distanceToBottom <= 180) void handleLoadMore();
                      }}
                    >
                      {filteredPlaces.map((place) => {
                        const selected = selectedPlaces.some(
                          (item) => item.id === place.id,
                        );
                        const favorite = favoritePlaceKeys.has(
                          placeIdentity(place),
                        );
                        const spaceLabel =
                          place.space_type === "indoor"
                            ? "실내"
                            : place.space_type === "outdoor"
                              ? "야외"
                              : place.space_type === "mixed"
                                ? "실내·야외"
                                : null;
                        return (
                          <div
                            className={`place-card-row${selected ? " is-selected" : ""}`}
                            key={place.id}
                          >
                            <button
                              className={`place-card${selected ? " is-selected" : ""}`}
                              type="button"
                              onClick={() => togglePlace(place)}
                            >
                              <span className="place-check">
                                {selected ? "✓" : ""}
                              </span>
                              <span
                                className={`place-category-icon${place.imageUrl ? " has-image" : ""}${place.imageStatus === "available" ? " has-actual-image" : " is-fallback-image"}`}
                                onClick={place.imageStatus === "available" ? (event) => {
                                  event.stopPropagation();
                                  setPhotoPreview(place);
                                } : undefined}
                              >
                                {place.categoryIcon}
                                {place.imageUrl && (
                                  <img
                                    src={place.imageUrl}
                                    alt={
                                      place.imageStatus === "available"
                                        ? `${place.name} 대표 사진`
                                        : `${place.categoryLabel} 카테고리 이미지`
                                    }
                                    loading="lazy"
                                    onLoad={(event) => {
                                      event.currentTarget.style.display = "";
                                      event.currentTarget.parentElement?.classList.remove(
                                        "is-image-error",
                                      );
                                    }}
                                    onError={(event) => {
                                      event.currentTarget.style.display =
                                        "none";
                                      event.currentTarget.parentElement?.classList.remove(
                                        "has-actual-image",
                                      );
                                      event.currentTarget.parentElement?.classList.add(
                                        "is-image-error",
                                      );
                                    }}
                                  />
                                )}
                              </span>
                              <div>
                                {place.sourceLabel && (
                                  <span
                                    className={`place-source-badge is-${place.sourceKind}`}
                                  >
                                    {place.sourceLabel}
                                    {place.eventUrgency && (
                                      <b>{place.eventUrgency}</b>
                                    )}
                                  </span>
                                )}
                                <strong>{place.name}</strong>
                                <small>
                                  {place.address ?? place.categoryLabel}
                                </small>
                                {place.eventPeriod && (
                                  <small className="place-event-period">
                                    운영 {place.eventPeriod}
                                  </small>
                                )}
                                <span className="place-badge-row">
                                  {spaceLabel &&
                                    place.space_type_confidence !==
                                      "unknown" && (
                                      <span
                                        className={`space-badge is-${place.space_type}`}
                                      >
                                        {spaceLabel}
                                      </span>
                                    )}
                                </span>
                              </div>
                              <em>{formatDistance(place.distanceMeters)}</em>
                              <span
                                className="place-corner-icon"
                                aria-label={place.categoryLabel}
                              >
                                {place.categoryIcon}
                              </span>
                            </button>
                            <button
                              className={`place-favorite-button${favorite ? " is-active" : ""}`}
                              type="button"
                              onClick={() => toggleFavoritePlace(place)}
                              aria-label={
                                favorite
                                  ? `${place.name} 즐겨찾기 해제`
                                  : `${place.name} 즐겨찾기`
                              }
                              title={
                                account?.token
                                  ? favorite
                                    ? "즐겨찾기 해제"
                                    : "즐겨찾기에 저장"
                                  : "로그인하면 장소를 저장할 수 있어요"
                              }
                            >
                              {favorite ? "★" : "☆"}
                            </button>
                            <button
                              className="place-hide-button"
                              type="button"
                              onClick={() => handleExcludePlace(place)}
                              title={
                                account?.token
                                  ? "앞으로 이 장소를 추천하지 않기"
                                  : "로그인 후 추천에서 숨길 수 있어요"
                              }
                            >
                              {account?.token ? "다시 추천하지 않기" : "숨기기"}
                            </button>
                            {selected && (
                              <button
                                className={`preferred-first${preferredPlaceId === place.id ? " is-active" : ""}`}
                                type="button"
                                onClick={() => {
                                  if (preferredPlaceId === place.id) return;
                                  setPreferredPlaceId(place.id);
                                  setSelectedPlaces((current) => {
                                    const preferred = current.find(
                                      (item) => item.id === place.id,
                                    );
                                    if (!preferred) return current;
                                    return [
                                      { ...preferred, preferredFirst: true },
                                      ...current
                                        .filter((item) => item.id !== place.id)
                                        .map((item) => ({
                                          ...item,
                                          preferredFirst: false,
                                        })),
                                    ];
                                  });
                                  setFocusedStopIndex(0);
                                  setCalculated(false);
                                  setCourseResult(null);
                                }}
                              >
                                {preferredPlaceId === place.id
                                  ? "1번 장소"
                                  : "1번으로 변경"}
                              </button>
                            )}
                          </div>
                        );
                      })}
                      {filteredPlaces.length === 0 && (
                        <p className="place-status">
                          이 종류의 추천 장소가 아직 없어요.
                        </p>
                      )}
                    </div>
                    <div
                      className="place-auto-load-status"
                      role="status"
                      aria-live="polite"
                      aria-atomic="true"
                    >
                      {placeStatus === "more-loading" && (
                        <span>새로운 장소를 찾고 있어요</span>
                      )}
                      {moreLoadError && placeStatus !== "more-loading" && (
                        <span className="is-error">
                          장소를 불러오지 못했어요
                          <button type="button" onClick={() => void handleLoadMore({ force: true })}>
                            다시 불러오기
                          </button>
                        </span>
                      )}
                      {!hasMorePlaces && places.length > 0 && !moreLoadError && (
                        <span>추천 가능한 장소를 모두 확인했어요</span>
                      )}
                    </div>
                    {calculationStatus === "warning" && (
                      <div className="place-warning is-warning">
                        선택한 장소를 모두 방문하면 시간이 부족해요. 장소를 하나
                        이상 빼고 다시 코스를 짜주세요.
                      </div>
                    )}
                    {calculationError && (
                      <p className="place-status is-error">
                        {calculationError}
                      </p>
                    )}
                    {response?._client_mode === "auto-course" && (
                      <button
                        className="auto-course-return"
                        type="button"
                        onClick={returnToAutoCourses}
                      >
                        자동 코스 3가지 보기
                      </button>
                    )}
                    <button
                      className={`place-calc-button${selectedPlaces.length && availableTimeMinutes && calculationStatus !== "loading" ? " is-active" : ""}`}
                      type="button"
                      disabled={
                        !selectedPlaces.length ||
                        !availableTimeMinutes ||
                        calculationStatus === "loading"
                      }
                      onClick={() => handleCalculate()}
                    >
                      {calculationStatus === "loading"
                        ? "코스 계산 중…"
                        : calculationStatus === "warning"
                          ? "장소를 조정해 주세요"
                          : "선택한 장소로 코스 짜기"}{" "}
                      <span>→</span>
                    </button>
                  </>
                )}
              </>
            ) : (
              <>
                <div className="ranking-heading">
                  <div>
                    <h2>
                      {result.targetArea
                        ? "요청한 지역 코스"
                        : "지금 가기 좋은 지역"}
                    </h2>
                    <p>지역을 누르면 실제 장소를 선택할 수 있어요</p>
                  </div>
                  <AdventurePanel
                    area={selectedArea}
                    areas={rankingAreas}
                    recommendationContext={result.recommendationContext}
                    initialMode={response?._client_adventure_mode}
                    onUsePlaces={useAdventurePlaces}
                    onUseArea={useAdventureArea}
                  />
                  <span>{rankingAreas.length}곳</span>
                </div>
                <div className="ranking-scroll">
                  {rankingAreas.map((area, index) => (
                    <AreaCard
                      key={`${area.name}-${index}`}
                      area={{ ...displayArea(area), rank: index + 1 }}
                      selected={selectedIndex === index}
                      onPreview={() => prepareAreaRoute(area)}
                      onSelect={() => {
                        prepareAreaRoute(area);
                        setPinnedCourseArea(null);
                        setSelectedIndex(index);
                        setSelectedPlaces([]);
                        setPreferredPlaceId(null);
                        setCalculated(false);
                        setCourseResult(null);
                        if (availableTimeMinutes == null) {
                          setTimeBudgetPromptOpen(true);
                          return;
                        }
                        setPlaceMode(true);
                      }}
                    />
                  ))}
                </div>
              </>
            )}
          </section>
        )}
        {guideIsComplete && !sheetExpanded && (
          <button
            className="guide-complete-floating-cta"
            type="button"
            onClick={onBack}
          >
            <span aria-hidden="true">✨</span>
            <b>새 코스 추천받기</b>
            <i aria-hidden="true">→</i>
          </button>
        )}
      </aside>
      {timeBudgetPromptOpen && (
        <div
          className="time-budget-prompt-backdrop"
          role="presentation"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget)
              setTimeBudgetPromptOpen(false);
          }}
        >
          <section
            className="time-budget-prompt"
            role="dialog"
            aria-modal="true"
            aria-labelledby="time-budget-prompt-title"
          >
            <small>코스를 계산하려면 시간이 필요해요</small>
            <h2 id="time-budget-prompt-title">얼마나 여유가 있나요?</h2>
            <p>선택한 시간 안에 식사·카페와 실제 이동을 맞춰드릴게요.</p>
            <div className="time-budget-quick-options">
              {[60, 120, 180].map((minutes) => (
                <button
                  key={minutes}
                  type="button"
                  onClick={() => applyManualTimeBudget(minutes)}
                >
                  {minutes / 60}시간
                </button>
              ))}
            </div>
            <div className="time-wheel-picker" aria-label="여유 시간 선택">
              <div className="time-wheel-selection" aria-hidden="true" />
              <TimeWheelColumn
                label="시간"
                options={timeHourOptions}
                value={Math.floor(timeBudgetDraft / 60)}
                onChange={(value) => setTimeBudgetPart("hours", value)}
              />
              <TimeWheelColumn
                label="분"
                options={timeMinuteOptions}
                value={timeBudgetDraft % 60}
                onChange={(value) => setTimeBudgetPart("minutes", value)}
              />
            </div>
            <strong className="time-wheel-summary">
              선택한 시간 {Math.floor(timeBudgetDraft / 60)}시간
              {timeBudgetDraft % 60 > 0 ? ` ${timeBudgetDraft % 60}분` : ""}
            </strong>
            <button
              className="time-budget-apply"
              type="button"
              onClick={() => applyManualTimeBudget(timeBudgetDraft)}
            >
              이 시간으로 장소 보기 <span>→</span>
            </button>
            <button
              className="time-budget-cancel"
              type="button"
              onClick={() => setTimeBudgetPromptOpen(false)}
            >
              취소
            </button>
          </section>
        </div>
      )}
      {proactivePromptMode && proactiveOffer?.place && (
        <div className="proactive-prompt-backdrop" role="presentation">
          <section
            className="proactive-prompt"
            role="dialog"
            aria-modal="true"
            aria-labelledby="proactive-prompt-title"
          >
            <small>
              {proactiveOffer.reason === "ending_today"
                ? "오늘이 마지막 날"
                : "이번 주 종료 예정"}
            </small>
            <div>
              {proactiveOffer.place.imageUrl && (
                <img
                  src={proactiveOffer.place.imageUrl}
                  alt=""
                  onError={(event) => {
                    event.currentTarget.style.display = "none";
                  }}
                />
              )}
              <span>
                <strong id="proactive-prompt-title">
                  {proactiveOffer.place.name}
                </strong>
                <p>
                  {proactivePromptMode === "live"
                    ? `현재 위치에서 가까워요. 약 ${proactiveExtraMinutes}분을 사용해 코스에 추가할까요?`
                    : `현재 코스의 남는 시간 안에 들를 수 있어요. 약 ${proactiveExtraMinutes}분을 추가할까요?`}
                </p>
              </span>
            </div>
            <button
              className="is-accept"
              type="button"
              onClick={acceptProactiveSuggestion}
            >
              {proactivePromptMode === "live"
                ? "추가하고 경로 다시 계산"
                : "코스에 추가하기"}
            </button>
            <button
              className="is-dismiss"
              type="button"
              onClick={dismissProactivePrompt}
            >
              {proactivePromptMode === "live"
                ? "지금 코스 유지"
                : "괜찮아요, 이대로 확정"}
            </button>
          </section>
        </div>
      )}
      {photoPreview && (
        <div
          className="place-photo-preview-backdrop"
          role="presentation"
          onClick={() => setPhotoPreview(null)}
        >
          <section
            className="place-photo-preview"
            role="dialog"
            aria-modal="true"
            aria-label={`${photoPreview.name} 사진`}
            onClick={(event) => event.stopPropagation()}
          >
            <button
              className="place-photo-preview-close"
              type="button"
              onClick={() => setPhotoPreview(null)}
              aria-label="사진 닫기"
            >
              ×
            </button>
            <img src={photoPreview.imageUrl} alt={`${photoPreview.name} 검색 사진`} />
            <strong>{photoPreview.name}</strong>
            <small>{photoPreview.address ?? photoPreview.categoryLabel}</small>
            <div className="place-photo-preview-source">
              <span>이미지 검색 결과</span>
              {photoPreview.imageAttributionUrl && (
                <>
                  <span aria-hidden="true"> · </span>
                  <a href={photoPreview.imageAttributionUrl} target="_blank" rel="noreferrer">
                    원본 보기
                  </a>
                </>
              )}
            </div>
          </section>
        </div>
      )}
    </main>
  );
}

export default RecommendationPage;
