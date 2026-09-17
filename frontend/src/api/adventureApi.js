const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000";

async function post(path, body) {
  let lastError;
  for (let attempt = 0; attempt < 2; attempt += 1) {
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 20000);
    try {
      const response = await fetch(`${API_BASE_URL}${path}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
        signal: controller.signal,
      });
      const data = await response.json().catch(() => ({}));
      if (response.ok) return data;
      const rawMessage =
        typeof data.detail === "string"
          ? data.detail
          : (data.message ?? "랜덤 추천을 준비하지 못했어요.");
      const message = response.status === 404 &&
        rawMessage.includes("방문 가능한 2장소")
        ? "주변 장소를 잠시 불러오지 못했어요. 잠시 후 다시 시도하거나 활동을 하나만 선택해 주세요."
        : rawMessage;
      lastError = new Error(message);
      if (![502, 503, 504].includes(response.status) || attempt === 1)
        throw lastError;
    } catch (error) {
      lastError =
        error?.name === "AbortError"
          ? new Error(
              "랜덤 추천이 평소보다 오래 걸리고 있어요. 잠시 후 다시 시도해 주세요.",
            )
          : error;
      if (
        attempt === 1 ||
        (error?.name !== "AbortError" && !(error instanceof TypeError))
      )
        throw lastError;
    } finally {
      window.clearTimeout(timeout);
    }
  }
  throw lastError ?? new Error("랜덤 추천을 준비하지 못했어요.");
}

export const requestAdventure = (body) => post("/recommend/adventure", body);
export const requestAdventureCourse = (body) =>
  post("/recommend/adventure/course", body);
export const requestBlindAdventure = (body) =>
  post("/recommend/adventure/blind", body);
export const revealBlindAdventure = (token) =>
  post("/recommend/adventure/blind/reveal", { token });
export const requestBlindAdventureCourse = (body) =>
  post("/recommend/adventure/blind/course", body);
export const revealBlindAdventureCourse = (token) =>
  post("/recommend/adventure/blind/course/reveal", { token });
export const requestRandomQuest = (activity) =>
  post("/recommend/adventure/quest", { activity });
export const requestSeoulGacha = (body) =>
  post("/recommend/adventure/seoul", body);
