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
import {
  adventureSignature,
  rememberAdventure,
} from "../../utils/adventureDiversity";

const labels = {
  food: "맛집",
  cafe: "카페",
  walk: "산책",
  culture: "문화",
  entertainment: "놀거리",
  shopping: "쇼핑",
  drink: "술집",
};

const modeCopy = {
  "blind-course": {
    eyebrow: "블라인드 코스",
    title: "어디로 갈지는 출발 직전에 알려드릴게요",
    description: "이동 시간과 활동 종류만 먼저 확인하고, 마음에 들면 목적지를 공개하세요.",
  },
  course: {
    eyebrow: "랜덤 코스",
    title: "고민 없이 코스 하나를 바로 골랐어요",
    description: "현재 위치와 남은 시간에 맞춘 두 장소예요. 마음에 들지 않으면 한 번 더 뽑을 수 있어요.",
  },
  quest: {
    eyebrow: "오늘의 퀘스트",
    title: "오늘 할 작은 도전 하나",
    description: "장소를 고르는 기능이 아니라, 오늘의 외출에 재미를 더하는 간단한 미션이에요.",
  },
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
  const [questDone, setQuestDone] = useState(false);
  const initialModeHandled = useRef(false);
  const recentSignatures = useRef(
    (() => {
      try {
        return JSON.parse(
          window.sessionStorage.getItem("koala-adventure-history") ?? "[]",
        );
      } catch {
        return [];
      }
    })(),
  );
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
      available_time_minutes: Number(recommendationContext?.available_time_minutes),
    }),
    [recommendationContext],
  );

  const ready = Boolean(area && context.start_location && Number.isFinite(context.available_time_minutes) && context.available_time_minutes > 0);
  const body = ready
    ? { area: areaPayload(area), recommendation_context: context }
    : null;
  const focusedMode = initialMode && modeCopy[initialMode] ? initialMode : null;

  const run = async (kind) => {
    if (!body || loading) return;
    setLoading(kind);
    setError("");
    if (kind === "quest") setQuestDone(false);
    try {
      if (kind === "single" || kind === "course") {
        const request =
          kind === "single" ? requestAdventure : requestAdventureCourse;
        let data = null;
        for (let attempt = 0; attempt < 3; attempt += 1) {
          data = await request(body);
          const signature = adventureSignature(data);
          if (!recentSignatures.current.includes(signature) || attempt === 2)
            break;
        }
        const signature = adventureSignature(data);
        recentSignatures.current = rememberAdventure(
          recentSignatures.current,
          signature,
        );
        window.sessionStorage.setItem(
          "koala-adventure-history",
          JSON.stringify(recentSignatures.current),
        );
        if (focusedMode === "course" && kind === "course") {
          await onUsePlaces?.(data.places ?? [], {
            mode: "course",
            autoConfirm: true,
          });
          return;
        }
        setResult({ kind, data });
      }
      if (kind === "blind")
        setResult({
          kind,
          data: await requestBlindAdventure(body),
          blind: true,
        });
      if (kind === "blind-course") {
        const blindData = await requestBlindAdventureCourse(body);
        if (focusedMode === "blind-course") {
          const revealed = await revealBlindAdventureCourse(blindData.token);
          await onUsePlaces?.(revealed.places ?? [], {
            mode: "blind-course",
            autoConfirm: true,
            startGuidance: true,
          });
          return;
        }
        setResult({ kind, data: blindData, blind: true });
      }
      if (kind === "quest") {
        const quest = await requestRandomQuest(context.activities[0] ?? "walk");
        if (focusedMode === "quest") {
          const course = await requestAdventureCourse(body);
          await onUsePlaces?.(course.places ?? [], {
            mode: "quest",
            autoConfirm: true,
            quest: quest.quest,
          });
          return;
        }
        setResult({ kind, data: quest });
      }
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
  const preview = result?.data?.course_preview;
  const panelCopy = focusedMode
    ? modeCopy[focusedMode]
    : {
        eyebrow: "색다른 추천",
        title: "평소와 다른 선택을 해볼까요?",
        description: "원하는 방식 하나를 골라보세요. 선택하기 전까지 기존 코스는 유지돼요.",
      };
  const canUsePlaces = preview?.status === "FEASIBLE" &&
    [preview.total_travel_time_minutes, preview.total_stay_time_minutes, preview.total_required_minutes]
      .every((value) => typeof value === "number" && Number.isFinite(value) && value >= 0) &&
    preview.total_required_minutes <= context.available_time_minutes;
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
          <section className="adventure-panel" role="dialog" aria-modal="true" aria-label="뜻밖의 추천">
            <button
              className="adventure-close"
              type="button"
              aria-label="뜻밖의 추천 닫기"
              onClick={() => setOpen(false)}
            >
              ×
            </button>
            <small>{panelCopy.eyebrow} · {area.name} · 여유 {context.available_time_minutes}분</small>
            <h2>{panelCopy.title}</h2>
            <p>{panelCopy.description}</p>
            {!focusedMode && <fieldset className="adventure-actions" disabled={Boolean(loading)} style={{ border: 0, padding: 0, margin: 0 }}>
              <button type="button" onClick={() => run("single")}>
                깜짝 장소 · 한 곳 발견
              </button>
              <button type="button" onClick={() => run("course")}>
                랜덤 코스 · 두 곳 함께
              </button>
              <button type="button" onClick={() => run("blind")}>
                목적지는 비밀 · 공개 후 선택
              </button>
              <button
                className="adventure-more-toggle"
                type="button"
                onClick={() => setMoreOpen((current) => !current)}
              >
                {moreOpen ? "간단히 보기" : "더 보기"}
              </button>
            </fieldset>}
            {!focusedMode && moreOpen && (
              <fieldset className="adventure-actions is-secondary" disabled={Boolean(loading)} style={{ border: 0, padding: 0 }}>
                <button type="button" onClick={() => run("blind-course")}>
                  코스 전체를 비밀로
                </button>
                <button type="button" onClick={() => run("quest")}>
                  오늘의 퀘스트
                </button>
                <button type="button" onClick={() => run("seoul")}>
                  서울 어디든 떠나기
                </button>
              </fieldset>
            )}
            {loading && (
              <div className="adventure-result">추천을 고르는 중…</div>
            )}
            {error && <div className="adventure-result is-error">{error}</div>}
            {result?.blind && (
              <div className="adventure-result">
                <b>{labels[result.data.category] ?? "랜덤"} 후보를 골랐어요</b>
                <span>10분 안에 공개할 수 있어요.</span>
                <button type="button" onClick={reveal} disabled={Boolean(loading)}>
                  장소 공개하기
                </button>
              </div>
            )}
            {result?.kind === "quest" && (
              <div className={`adventure-result adventure-quest${questDone ? " is-complete" : ""}`}>
                <b>{questDone ? "퀘스트 완료!" : "오늘의 작은 퀘스트"}</b>
                <span>{result.data.quest}</span>
                <div className="adventure-result-actions">
                  <button type="button" onClick={() => setQuestDone((current) => !current)}>
                    {questDone ? "완료 취소" : "완료했어요 ✓"}
                  </button>
                  <button type="button" className="is-secondary" onClick={() => run("quest")} disabled={Boolean(loading)}>
                    다른 퀘스트
                  </button>
                </div>
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
                  {canUsePlaces
                    ? `총 ${preview.total_required_minutes}분 · 이동 ${preview.total_travel_time_minutes}분 · 체류 ${preview.total_stay_time_minutes}분`
                    : "현재 시간 안에 가능한 경로인지 확인하지 못했어요. 다시 추천받아 주세요."}
                </span>
                <button
                  type="button"
                  disabled={Boolean(loading) || !canUsePlaces}
                  onClick={() => {
                    onUsePlaces(places);
                    setOpen(false);
                  }}
                >
                  이 장소로 코스 짜기
                </button>
                {focusedMode === "course" && (
                  <button
                    className="is-secondary"
                    type="button"
                    disabled={Boolean(loading)}
                    onClick={() => run("course")}
                  >
                    한 번 더 뽑기
                  </button>
                )}
              </div>
            )}
          </section>
        </div>,
        document.body,
      )}
    </>
  );
}
