import { measureAsync } from "../utils/performanceMetric";
import { getTrace, audit } from "../utils/auditTrace";
import { courseWarnings } from "../utils/contractAudit";
import { API_BASE_URL, apiAssetUrl } from "./apiConfig";

const responses = new Map();
const pending = new Map();
// The mvp-v2 backend does not expose the optional route-preview endpoint.
// Remember a 404 so every area does not repeatedly trigger the same request.
let routePreviewUnavailable = false;

function requestErrorMessage(path, status, data) {
  if (status === 422 && Array.isArray(data.detail)) {
    const fields = data.detail.map((item) => {
      const field = (item.loc ?? [])
        .filter((part) => part !== "body")
        .join(".");
      return `${field || "요청값"}: ${item.msg ?? "형식이 올바르지 않아요"}`;
    });
    return `코스 요청값을 확인해 주세요. ${fields.join(" / ")}`;
  }
  if (typeof data.detail === "string" && status < 500) return data.detail;
  if (status >= 500 && path === "/recommend/course")
    return "실제 이동 경로를 계산하지 못했어요. 이동수단을 바꾸거나 잠시 후 다시 시도해 주세요.";
  if (status >= 500 && path === "/recommend/places")
    return "주변 장소를 불러오지 못했어요. 기존 화면을 유지한 채 다시 시도해 주세요.";
  if (status === 404 || status === 410)
    return "추가 장소 목록이 만료됐어요. 지역을 다시 선택해 주세요.";
  return (
    data.message ??
    data.detail ??
    "요청을 처리하지 못했어요. 잠시 후 다시 시도해 주세요."
  );
}

function postJson(path, payload, { fresh = false } = {}) {
  const key = JSON.stringify([getTrace(), path, payload]);
  const cached = fresh ? null : responses.get(key);
  if (cached?.expires > Date.now()) return Promise.resolve(cached.data);
  if (pending.has(key)) return pending.get(key);
  const request = sendJson(path, payload)
    .then((data) => {
      if (responses.size >= 50) responses.delete(responses.keys().next().value);
      responses.set(key, { data, expires: Date.now() + 60000 });
      return data;
    })
    .finally(() => pending.delete(key));
  pending.set(key, request);
  return request;
}

async function sendJson(path, payload) {
  return measureAsync(`${path}-request`, async () => {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 30000);
    try {
      const response = await fetch(`${API_BASE_URL}${path}`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Koala-Trace-Id": getTrace(),
        },
        body: JSON.stringify(payload),
        signal: controller.signal,
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok)
        throw new Error(requestErrorMessage(path, response.status, data));
      const warnings =
        path === "/recommend/course" ? courseWarnings(data, payload) : [];
      audit("api_result", { path, response: data, warnings });
      if (warnings.length)
        throw new Error(
          `코스 계산 정보가 일치하지 않아요. 다시 시도해 주세요. (${getTrace()})`,
        );
      return data;
    } catch (error) {
      if (error?.name === "AbortError") {
        throw new Error(
          path === "/recommend/course"
            ? "경로 계산이 평소보다 오래 걸리고 있어요. 선택한 장소를 유지한 채 다시 시도해 주세요."
            : "장소 검색이 평소보다 오래 걸리고 있어요. 잠시 후 다시 시도해 주세요.",
        );
      }
      throw error;
    } finally {
      clearTimeout(timeout);
    }
  });
}

export function requestPlaces({
  areaName,
  latitude,
  longitude,
  activities = [],
  recommendationContext = null,
}) {
  return postJson("/recommend/places", {
    area_name: areaName,
    latitude,
    longitude,
    activities: activities.length
      ? activities
      : (recommendationContext?.activities ?? []),
    companions: recommendationContext?.companions ?? [],
    budget_max: recommendationContext?.budget_max ?? null,
    budget_preference: recommendationContext?.budget_preference ?? null,
    space_preference: recommendationContext?.space_preference ?? null,
  });
}

export function requestMorePlaces({ cursor, offset }) {
  return postJson("/recommend/places/more", { cursor, offset });
}

export async function requestPlacePhotos(places) {
  const data = await postJson(
    "/place-media/photos",
    {
      places: places.slice(0, 6).map((place) => ({
        client_key: place.id,
        name: place.name,
        address: place.address ?? null,
        latitude: Number(place.latitude),
        longitude: Number(place.longitude),
        category: place.category,
      })),
    },
    { fresh: true },
  );
  return {
    ...data,
    photos: (data.photos ?? []).map((photo) => ({
      ...photo,
      image_url: photo.image_url?.startsWith("/")
        ? apiAssetUrl(photo.image_url)
        : photo.image_url,
    })),
  };
}

export function validatePlaceSelection({
  startLatitude,
  startLongitude,
  selectedPlaces,
  availableTimeMinutes,
}) {
  return postJson("/recommend/places/validate-selection", {
    start_latitude: startLatitude,
    start_longitude: startLongitude,
    selected_places: selectedPlaces.map((place) => ({
      category: place.category,
      latitude: place.latitude,
      longitude: place.longitude,
      specified_duration_minutes: place.specifiedDurationMinutes ?? null,
    })),
    available_time_minutes: availableTimeMinutes,
  });
}

function serializeSelectedPlace(place) {
  return {
    category: place.category,
    latitude: place.latitude,
    longitude: place.longitude,
    specified_duration_minutes: place.specifiedDurationMinutes ?? null,
    preferred_first: Boolean(place.preferredFirst),
    name: place.name,
    source: place.source,
    source_id: place.sourceId ?? place.source_id,
    operation_schedule: place.operationSchedule ?? place.operation_schedule,
    event_start_date: place.eventStartDate ?? place.event_start_date,
    event_end_date: place.eventEndDate ?? place.event_end_date,
  };
}

export function requestCourse({
  startLocation,
  selectedPlaces,
  availableTimeMinutes,
  departureDatetime,
  endLocation,
  transportMode = "auto",
  optimizeOrder = true,
  fresh = false,
}) {
  const latitude = Number(startLocation?.latitude);
  const longitude = Number(startLocation?.longitude);
  const availableMinutes = Number(availableTimeMinutes);
  if (!Number.isFinite(latitude) || !Number.isFinite(longitude)) {
    return Promise.reject(
      new Error(
        "시작 위치 좌표를 확인할 수 없어요. 위치를 다시 설정해 주세요.",
      ),
    );
  }
  if (!Number.isInteger(availableMinutes) || availableMinutes <= 0) {
    return Promise.reject(
      new Error(
        "사용 가능한 시간이 없어요. 이전 화면에서 종료 시각이나 여유 시간을 다시 입력해 주세요.",
      ),
    );
  }
  if (
    !Array.isArray(selectedPlaces) ||
    selectedPlaces.length < 1 ||
    selectedPlaces.length > 6
  ) {
    return Promise.reject(
      new Error("코스 장소는 1곳 이상 6곳 이하로 선택해 주세요."),
    );
  }
  const invalidPlace = selectedPlaces.find(
    (place) =>
      !place?.category ||
      !Number.isFinite(Number(place.latitude)) ||
      !Number.isFinite(Number(place.longitude)),
  );
  if (invalidPlace) {
    return Promise.reject(
      new Error(
        `${invalidPlace.name ?? "선택한 장소"}의 위치 정보가 올바르지 않아요. 다른 장소를 선택해 주세요.`,
      ),
    );
  }
  return postJson(
    "/recommend/course",
    {
      start_location: { latitude, longitude },
      selected_places: selectedPlaces.map(serializeSelectedPlace),
      available_time_minutes: availableMinutes,
      optimize_order: optimizeOrder,
      departure_datetime: departureDatetime ?? null,
      end_location: endLocation ?? null,
      transport_mode: transportMode,
    },
    { fresh },
  );
}

export async function requestRoutePreview({
  startLatitude,
  startLongitude,
  endLatitude,
  endLongitude,
  transportMode = "auto",
}) {
  if (routePreviewUnavailable) return null;
  const parameters = new URLSearchParams({
    start_latitude: startLatitude,
    start_longitude: startLongitude,
    end_latitude: endLatitude,
    end_longitude: endLongitude,
    transport_mode: transportMode,
  });
  return measureAsync("/route-preview-request", async () => {
    let lastError;
    for (let attempt = 0; attempt < 2; attempt += 1) {
      try {
        const controller = new AbortController();
        const timeout = setTimeout(() => controller.abort(), 12000);
        let response;
        try {
          response = await fetch(
            `${API_BASE_URL}/route-preview?${parameters}`,
            {
              headers: { "X-Koala-Trace-Id": getTrace() },
              signal: controller.signal,
            },
          );
        } finally {
          clearTimeout(timeout);
        }
        const data = await response.json().catch(() => ({}));
        if (response.status === 404) {
          routePreviewUnavailable = true;
          audit("optional_api_unavailable", {
            path: "/route-preview",
            status: 404,
          });
          return null;
        }
        if (!response.ok) {
          lastError = new Error(
            data.detail ?? "이동 경로를 불러오지 못했어요.",
          );
          if (response.status < 500 || attempt === 1) throw lastError;
          continue;
        }
        return data;
      } catch (error) {
        lastError = error;
        if (attempt === 1) throw error;
      }
    }
    throw lastError ?? new Error("이동 경로를 불러오지 못했어요.");
  });
}
