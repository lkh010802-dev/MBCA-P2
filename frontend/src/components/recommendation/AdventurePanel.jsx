import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import {
  requestAdventure,
  requestAdventureCourse,
  requestBlindAdventure,
  requestBlindAdventureCourse,
  requestRandomQuest,
  requestSeoulGacha,
  revealBlindAdventure,
  revealBlindAdventureCourse,
} from "../../api/adventureApi";

const labels = {
  food: "맛집",
  cafe: "카페",
  walk: "산책",
  culture: "문화",
  entertainment: "놀거리",
  shopping: "쇼핑",
  drink: "술집",
};

function areaPayload(area) {
  return {
    area_name: area.name,
    latitude: area.latitude,
    longitude: area.longitude,
  };
}
function seoulAreaPayload(area) {
  return {
    AREA_NM: area.name,
    latitude: area.latitude,
    longitude: area.longitude,
  };
}

export default function AdventurePanel({
  area,
  areas,
  recommendationContext,
  initialMode,
  onUsePlaces,
  onUseArea,
}) {
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState("");
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");
  const [moreOpen, setMoreOpen] = useState(false);
  const initialModeHandled = useRef(false);
  const context = useMemo(
    () => ({
      activities: recommendationContext?.activities?.length
        ? recommendationContext.activities
        : ["cafe", "walk"],
      activity_preferences: recommendationContext?.activity_preferences ?? {},
      space_preference: recommendationContext?.space_preference ?? "any",
      transport_mode: recommendationContext?.transport_mode ?? "public_transit",
      start_location: recommendationContext?.start_location,
      departure_datetime:
        recommendationContext?.departure_datetime ?? new Date().toISOString(),
      end_location: recommendationContext?.end_location ?? null,
      available_time_minutes: Math.max(
        30,
        Number(recommendationContext?.available_time_minutes) || 180,
      ),
    }),
    [recommendationContext],
  );

  const ready = Boolean(area && context.start_location);
  const body = ready
    ? { area: areaPayload(area), recommendation_context: context }
    : null;

  const run = async (kind) => {
    if (!body) return;
    setLoading(kind);
    setError("");
    setResult(null);
    try {
      if (kind === "single")
        setResult({ kind, data: await requestAdventure(body) });
      if (kind === "course")
        setResult({ kind, data: await requestAdventureCourse(body) });
      if (kind === "blind")
        setResult({
          kind,
          data: await requestBlindAdventure(body),
          blind: true,
        });
      if (kind === "blind-course")
        setResult({
          kind,
          data: await requestBlindAdventureCourse(body),
          blind: true,
        });
      if (kind === "quest")
        setResult({
          kind,
          data: await requestRandomQuest(context.activities[0] ?? "walk"),
        });
      if (kind === "seoul") {
        const candidates = areas.filter(
          (item) => item?.latitude != null && item?.longitude != null,
        );
        const data = await requestSeoulGacha({
          target_area: null,
          current_area: candidates[0] ? seoulAreaPayload(candidates[0]) : null,
          other_areas: candidates.slice(1).map(seoulAreaPayload),
          extended_areas: [],
          recommendation_context: { ...context },
        });
        setResult({ kind, data });
      }
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setLoading("");
    }
  };

  useEffect(() => {
    if (!ready || !initialMode || initialModeHandled.current) return;
    initialModeHandled.current = true;
    setOpen(true);
    void run(initialMode);
  }, [ready, initialMode]);

  const reveal = async () => {
    setLoading("reveal");
    setError("");
    try {
      const data =
        result.kind === "blind-course"
          ? await revealBlindAdventureCourse(result.data.token)
          : await revealBlindAdventure(result.data.token);
      setResult({
        kind: result.kind === "blind-course" ? "course" : "single",
        data,
      });
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setLoading("");
    }
  };

  const places =
    result?.data?.places ?? (result?.data?.place ? [result.data.place] : []);
  const openAndRun = (kind) => {
    setOpen(true);
    void run(kind);
  };
  if (!ready) return null;
  return (
    <>
      <button className="adventure-launch" type="button" onClick={() => setOpen(true)}>
        🎲 다른 추천
      </button>
      {open && createPortal(
        <div
          className="adventure-backdrop"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) setOpen(false);
          }}
        >
          <section className="adventure-panel" role="dialog" aria-modal="true">
            <button
              className="adventure-close"
              type="button"
              onClick={() => setOpen(false)}
            >
              ×
            </button>
            <small>현재 지역 · {area.name}</small>
            <h2>평소와 다른 선택을 해볼까요?</h2>
            <p>현재 위치와 남은 시간을 지키는 후보만 확인해요.</p>
            <div className="adventure-actions">
              <button type="button" onClick={() => run("single")}>
                깜짝 장소
              </button>
              <button type="button" onClick={() => run("course")}>
                랜덤 코스
              </button>
              <button type="button" onClick={() => run("blind")}>
                목적지는 비밀
              </button>
              <button
                className="adventure-more-toggle"
                type="button"
                onClick={() => setMoreOpen((current) => !current)}
              >
                {moreOpen ? "간단히 보기" : "더 보기"}
              </button>
            </div>
            {moreOpen && (
              <div className="adventure-actions is-secondary">
                <button type="button" onClick={() => run("blind-course")}>
                  코스 전체를 비밀로
                </button>
                <button type="button" onClick={() => run("quest")}>
                  오늘의 퀘스트
                </button>
                <button type="button" onClick={() => run("seoul")}>
                  서울 어디든 떠나기
                </button>
              </div>
            )}
            {loading && (
              <div className="adventure-result">추천을 고르는 중…</div>
            )}
            {error && <div className="adventure-result is-error">{error}</div>}
            {result?.blind && (
              <div className="adventure-result">
                <b>{labels[result.data.category] ?? "랜덤"} 후보를 골랐어요</b>
                <span>10분 안에 공개할 수 있어요.</span>
                <button type="button" onClick={reveal}>
                  장소 공개하기
                </button>
              </div>
            )}
            {result?.kind === "quest" && (
              <div className="adventure-result">
                <b>오늘의 작은 퀘스트</b>
                <span>{result.data.quest}</span>
              </div>
            )}
            {result?.kind === "seoul" && (
              <div className="adventure-result">
                <b>{result.data.selected_area?.AREA_NM}</b>
                <span>오늘의 랜덤 추천 지역이에요.</span>
                <button
                  type="button"
                  onClick={() => {
                    onUseArea(result.data.selected_area);
                    setOpen(false);
                  }}
                >
                  이 지역 장소 보기
                </button>
              </div>
            )}
            {places.length > 0 && (
              <div className="adventure-result">
                <b>
                  {places
                    .map((place) => place.name ?? place.place_name)
                    .join(" → ")}
                </b>
                <span>
                  이동{" "}
                  {result.data.course_preview?.total_travel_time_minutes ?? 0}분
                  · 체류{" "}
                  {result.data.course_preview?.total_stay_time_minutes ?? 0}분
                </span>
                <button
                  type="button"
                  onClick={() => {
                    onUsePlaces(places);
                    setOpen(false);
                  }}
                >
                  이 장소로 코스 짜기
                </button>
              </div>
            )}
          </section>
        </div>,
        document.body,
      )}
    </>
  );
}
