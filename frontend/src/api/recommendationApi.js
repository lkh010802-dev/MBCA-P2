import { measureAsync } from "../utils/performanceMetric";
import { startTrace, getTrace, audit } from "../utils/auditTrace";
import { hasAutoCourseStartLocationMismatch } from "../utils/locationContract";

const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000";

export async function requestRecommendation(
  {
    message,
    location,
    preferences,
    fastAutoCourse = false,
    autoCourseDurationMinutes = null,
  },
  { signal } = {},
) {
  startTrace();
  audit("input", {
    user_input: message,
    gps_provided: Boolean(location),
    fastAutoCourse,
  });
  return measureAsync("recommend-request", async () => {
    const timeoutController = new AbortController();
    // LLM과 지도 조회가 함께 실행되는 정상 요청도 15초를 넘길 수 있다.
    // 무한 대기는 막되, 정상 응답을 너무 일찍 실패시키지 않는다.
    const timeoutId = window.setTimeout(
      () => timeoutController.abort("timeout"),
      30000,
    );
    const abortFromCaller = () => timeoutController.abort("cancelled");
    signal?.addEventListener("abort", abortFromCaller, { once: true });
    let response;
    try {
      response = await fetch(`${API_BASE_URL}/recommend`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Koala-Trace-Id": getTrace(),
        },
        signal: timeoutController.signal,
        body: JSON.stringify({
          user_message: message,
          gps_latitude: location?.latitude ?? null,
          gps_longitude: location?.longitude ?? null,
          preferred_transport_mode: preferences?.transport_mode ?? null,
          preferred_space: preferences?.space_preference ?? null,
          preferred_activities: Object.entries(
            preferences?.activity_preferences ?? {},
          )
            .filter(([, level]) => Number(level) >= 4)
            .map(([code]) => code),
          auto_course: fastAutoCourse,
          auto_course_duration_minutes: autoCourseDurationMinutes,
        }),
      });
    } catch (error) {
      if (timeoutController.signal.reason === "timeout")
        throw new Error(
          "추천이 평소보다 오래 걸리고 있어요. 잠시 후 다시 시도해 주세요.",
        );
      throw error;
    } finally {
      window.clearTimeout(timeoutId);
      signal?.removeEventListener("abort", abortFromCaller);
    }

    const data = await response.json().catch(() => ({}));
    if (!response.ok || data.error) {
      const fallback =
        response.status >= 500
          ? "추천 서버 연결이 불안정해요. 잠시 후 다시 시도해 주세요."
          : response.status === 400 || response.status === 422
            ? "입력한 위치와 일정 조건을 다시 확인해 주세요."
            : "추천 정보를 불러오지 못했어요.";
      throw new Error(data.message ?? data.detail ?? fallback);
    }
    if (
      fastAutoCourse &&
      location &&
      hasAutoCourseStartLocationMismatch(
        location,
        data.recommendation_context?.start_location,
      )
    ) {
      audit("contract_warning", {
        warning: "auto_course_start_location_mismatch",
        requested_location: location,
        response_start_location:
          data.recommendation_context?.start_location ?? null,
      });
      throw new Error(
        "현재 위치와 다른 지역으로 추천하려고 했어요. 서버를 재시작한 뒤 다시 추천받아 주세요.",
      );
    }
    if (fastAutoCourse && Number.isInteger(Number(autoCourseDurationMinutes))) {
      const selectedMinutes = Number(autoCourseDurationMinutes);
      const backendMinutes = Number(
        data.recommendation_context?.available_time_minutes,
      );
      if (
        Number.isFinite(backendMinutes) &&
        backendMinutes > 0 &&
        backendMinutes !== selectedMinutes
      ) {
        audit("contract_warning", {
          warning: "auto_course_duration_mismatch",
          selected_minutes: selectedMinutes,
          backend_minutes: backendMinutes,
        });
        throw new Error(
          `선택한 시간(${selectedMinutes}분)과 서버 계산 시간(${backendMinutes}분)이 달라요. 서버를 재시작한 뒤 다시 시도해 주세요.`,
        );
      }
      // 사용자가 직접 고른 구조화된 시간은 LLM 결과가 아니며 요청의 원본이다.
      // 구버전 서버가 context 값을 누락한 경우에만 원본을 복구한다.
      if (!Number.isFinite(backendMinutes) || backendMinutes <= 0) {
        audit("contract_recovery", {
          field: "available_time_minutes",
          source: "auto_course_duration_minutes",
          value: selectedMinutes,
        });
        return {
          ...data,
          recommendation_context: {
            ...(data.recommendation_context ?? {}),
            available_time_minutes: selectedMinutes,
          },
        };
      }
    }
    return data;
  });
}
