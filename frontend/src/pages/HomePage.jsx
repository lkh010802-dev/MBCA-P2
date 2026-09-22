import { useEffect, useMemo, useRef, useState } from "react";
import { useCurrentLocation } from "../hooks/useCurrentLocation";
import koalaPeeking from "../assets/images/koala-peeking.webp";
import TimeWheel from "../components/common/TimeWheel";
import PromptHelpDialog from "../components/home/PromptHelpDialog";
import {
  addAppointmentTime,
  needsAppointmentTimeClarification,
  suggestedAppointmentHours,
} from "../utils/timeIntent";
import {
  deleteSavedCourse,
  getExcludedPlaces,
  getFavoritePlaces,
  getMe,
  getPersonalizationProfile,
  getPreferences,
  getSavedCourses,
  isMockAuthEnabled,
  login,
  recordInteraction,
  removeFavoritePlace,
  restoreExcludedPlace,
  signup,
  updatePreferences,
} from "../api/accountApi";

const COURSE_HOURS = [0, 1, 2, 3, 4, 5, 6, 7, 8];
const COURSE_MINUTES = [0, 10, 20, 30, 40, 50];

function HomePage({
  isOpen,
  onRecommend,
  onOpenSavedCourse,
  error,
  account,
  onAccountChange,
  accountRequestId = 0,
}) {
  const [message, setMessage] = useState("");
  const [accountOpen, setAccountOpen] = useState(false);
  const [accountMode, setAccountMode] = useState("login");
  const [accountError, setAccountError] = useState("");
  const [promptHelpOpen, setPromptHelpOpen] = useState(false);
  const [savedCourses, setSavedCourses] = useState([]);
  const [favoritePlaces, setFavoritePlaces] = useState([]);
  const [excludedPlaces, setExcludedPlaces] = useState([]);
  const [savedCourseNotice, setSavedCourseNotice] = useState("");
  const [pendingQuickCourse, setPendingQuickCourse] = useState(null);
  const [timePickerOpen, setTimePickerOpen] = useState(false);
  const [courseHours, setCourseHours] = useState(3);
  const [courseMinutes, setCourseMinutes] = useState(0);
  const [quickCourseError, setQuickCourseError] = useState("");
  const [pendingAdventureMode, setPendingAdventureMode] = useState(null);
  const [appointmentPromptOpen, setAppointmentPromptOpen] = useState(false);
  const [pendingAppointmentMessage, setPendingAppointmentMessage] = useState("");
  const quickCourseRequestRef = useRef(false);
  const messageInputRef = useRef(null);

  // 진입 버튼의 의미와 모달 첫 화면을 일치시킨다. 이전 회원가입 상태는 재사용하지 않는다.
  const openAccount = () => {
    setAccountMode("login");
    setAccountError("");
    setAccountOpen(true);
  };
  const closeAccount = () => {
    setAccountOpen(false);
    setAccountMode("login");
    setAccountError("");
  };

  const usePromptExample = (example) => {
    setMessage(example);
    setPromptHelpOpen(false);
    requestAnimationFrame(() => {
      messageInputRef.current?.focus();
      messageInputRef.current?.setSelectionRange(example.length, example.length);
    });
  };
  const {
    location,
    address,
    addressStatus,
    status,
    requestLocation,
    clearLocation,
  } = useCurrentLocation();

  const autoCourse = useMemo(() => {
    const preferences = account?.preferences?.activity_preferences ?? {};
    const favorite = Object.entries(preferences).sort(
      ([, left], [, right]) => Number(right) - Number(left),
    )[0]?.[0];
    const favoriteLabel = {
      food: "맛집",
      cafe: "카페",
      walk: "산책",
      culture: "문화",
      entertainment: "놀거리",
      shopping: "쇼핑",
      drink: "술집",
    }[favorite];
    return {
      id: "auto",
      prompt: favoriteLabel
        ? `현재 위치에서 ${favoriteLabel} 취향도 반영하고, 지금 운영 중인 장소를 이용해 서로 다른 분위기의 3시간 코스 후보를 추천해줘.`
        : "현재 위치에서 지금 운영 중인 장소를 이용해 서로 다른 분위기의 3시간 코스 후보를 추천해줘.",
    };
  }, [account?.preferences?.activity_preferences]);

  useEffect(() => {
    if (accountRequestId > 0) openAccount();
  }, [accountRequestId]);

  useEffect(() => {
    if (!account?.token) {
      setSavedCourses([]);
      setFavoritePlaces([]);
      setExcludedPlaces([]);
      return;
    }
    Promise.all([
      getSavedCourses(account.token),
      getFavoritePlaces(account.token),
      getExcludedPlaces(account.token),
    ])
      .then(([courses, favorites, excluded]) => {
        setSavedCourses(courses);
        setFavoritePlaces(favorites);
        setExcludedPlaces(excluded);
      })
      .catch((requestError) => setAccountError(requestError.message));
  }, [account?.token]);

  const removeSavedCourse = async (courseId) => {
    try {
      await deleteSavedCourse(account.token, courseId);
      setSavedCourses((current) =>
        current.filter((course) => course.id !== courseId),
      );
    } catch (requestError) {
      setAccountError(requestError.message);
    }
  };

  const openSavedCourse = (course) => {
    if (onOpenSavedCourse?.(course)) {
      void recordInteraction(account?.token, {
        event_type: "course_open",
        context_data: { area_name: course.area_name ?? null, course_id: course.id },
      }).catch(() => {});
      setAccountOpen(false);
      setSavedCourseNotice("");
      return;
    }
    setSavedCourseNotice(
      "이전 저장 형식이라 지도 복원이 어려워요. 새로 저장한 코스부터 다시 열 수 있어요.",
    );
  };

  const removeFavorite = async (placeKey) => {
    try {
      await removeFavoritePlace(account.token, placeKey);
      setFavoritePlaces((current) =>
        current.filter((place) => place.place_key !== placeKey),
      );
    } catch (requestError) {
      setAccountError(requestError.message);
    }
  };

  const restorePlace = async (placeKey) => {
    try {
      await restoreExcludedPlace(account.token, placeKey);
      setExcludedPlaces((current) =>
        current.filter((place) => place.place_key !== placeKey),
      );
    } catch (requestError) {
      setAccountError(requestError.message);
    }
  };

  useEffect(() => {
    if (!timePickerOpen) return undefined;
    const closeOnEscape = (event) => {
      if (event.key === "Escape") setTimePickerOpen(false);
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [timePickerOpen]);

  const submitQuickCourse = async (course, nextLocation) => {
    try {
      setQuickCourseError("");
      await onRecommend({
        message: course.prompt,
        location: nextLocation,
        preferences: account?.preferences,
        autoCourse: course.id === "auto",
        fastAutoCourse: Boolean(course.fast),
        autoCourseDurationMinutes: course.durationMinutes,
        adventureMode: course.adventureMode ?? null,
      });
    } finally {
      quickCourseRequestRef.current = false;
      setPendingQuickCourse(null);
    }
  };

  const startQuickCourse = (course) => {
    if (quickCourseRequestRef.current) return;
    setQuickCourseError("");
    quickCourseRequestRef.current = true;
    setPendingQuickCourse(course);
    if (!location) {
      requestLocation(
        (nextLocation) => {
          void submitQuickCourse(course, nextLocation);
        },
        (locationError) => {
          quickCourseRequestRef.current = false;
          setPendingQuickCourse(null);
          setQuickCourseError(
            locationError?.code === locationError?.PERMISSION_DENIED
              ? "자동 코스는 현재 위치가 필요해요. 브라우저의 위치 권한을 허용한 뒤 다시 눌러주세요."
              : "현재 위치를 확인하지 못했어요. 위치 버튼을 다시 누르거나 원하는 지역을 문장으로 입력해 주세요.",
          );
        },
      );
      return;
    }
    void submitQuickCourse(course, location);
  };

  const handleSubmit = (event) => {
    event.preventDefault();
    if (quickCourseRequestRef.current) return;
    if (!message.trim()) return;
    if (needsAppointmentTimeClarification(message)) {
      setPendingAppointmentMessage(message.trim());
      setAppointmentPromptOpen(true);
      return;
    }
    onRecommend({ message, location, preferences: account?.preferences });
  };

  const submitAppointmentTime = (hour) => {
    const clarifiedMessage = addAppointmentTime(pendingAppointmentMessage, hour);
    setMessage(clarifiedMessage);
    setAppointmentPromptOpen(false);
    onRecommend({
      message: clarifiedMessage,
      location,
      preferences: account?.preferences,
    });
  };

  const confirmAutoCourseTime = () => {
    const durationMinutes = Math.max(30, courseHours * 60 + courseMinutes);
    const durationText =
      courseHours > 0
        ? `${courseHours}시간${courseMinutes ? ` ${courseMinutes}분` : ""}`
        : `${courseMinutes}분`;
    // 자동 추천은 텍스트 입력과 독립된 흐름이다. 홈의 문장을 섞지 않고
    // 시간 선택값과 계정 선호만 구조화된 조건으로 전달한다.
    const adventurePrompt = {
      "blind-course": "목적지를 미리 공개하지 않는 블라인드 코스",
      course: "뜻밖의 랜덤 코스",
      quest: "오늘의 작은 퀘스트가 포함된 코스",
    }[pendingAdventureMode];
    const prompt = adventurePrompt
      ? `현재 위치에서 ${durationText} 동안 즐길 수 있는 ${adventurePrompt}를 추천해줘.`
      : `현재 위치에서 지금 운영 중인 장소를 이용해 ${durationText} 동안 즐길 수 있는 서로 다른 분위기의 코스 후보를 추천해줘.`;
    setTimePickerOpen(false);
    startQuickCourse({
      ...autoCourse,
      id: pendingAdventureMode ? `adventure-${pendingAdventureMode}` : "auto",
      prompt,
      fast: !pendingAdventureMode,
      durationMinutes,
      adventureMode: pendingAdventureMode,
    });
    setPendingAdventureMode(null);
  };

  const handleAccount = async (event) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setAccountError("");
    try {
      if (accountMode === "signup") {
        await signup({
          email: form.get("email"),
          password: form.get("password"),
          nickname: form.get("nickname"),
        });
      }
      const session = await login({
        email: form.get("email"),
        password: form.get("password"),
      });
      localStorage.setItem("koala-token", session.access_token);
      const [user, preferences, personalization] = await Promise.all([
        getMe(session.access_token),
        getPreferences(session.access_token),
        getPersonalizationProfile(session.access_token),
      ]);
      onAccountChange({ token: session.access_token, user, preferences, personalization });
      setAccountOpen(false);
    } catch (requestError) {
      setAccountError(requestError.message);
    }
  };

  const savePreferences = async (event) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    try {
      const preferences = await updatePreferences(account.token, {
        transport_mode: form.get("transport_mode") || null,
        space_preference: form.get("space_preference") || null,
        activity_preferences: Object.fromEntries(
          form.getAll("activities").map((code) => [code, 5]),
        ),
      });
      onAccountChange({ ...account, preferences });
      setAccountOpen(false);
    } catch (requestError) {
      setAccountError(requestError.message);
    }
  };

  const locationText =
    status === "success"
      ? "현재 위치를 사용하고 있어요"
      : status === "loading"
        ? "현재 위치를 확인하는 중이에요"
        : status === "denied"
          ? "지역을 입력하거나 위치 권한을 허용해 주세요"
          : status === "unavailable"
            ? "위치를 확인하지 못했어요. 다시 눌러주세요"
            : status === "unsupported"
              ? "이 기기에서는 위치를 지원하지 않아요"
              : "현재 위치를 알려주시면 더 정확해요";
  const selectedDurationMinutes = courseHours * 60 + courseMinutes;

  return (
    <main
      className={
        isOpen
          ? "home-page home-page--sheet is-open"
          : "home-page home-page--sheet"
      }
    >
      <img
        className="home-peeking-koala"
        src={koalaPeeking}
        alt=""
        decoding="async"
      />
      <header className="home-header">
        <p className="home-brand">코알라</p>
        <button
          className="account-button"
          type="button"
          onClick={openAccount}
        >
          {account?.user ? account.user.nickname : "로그인"}
        </button>
      </header>
      <section className="home-intro">
        <p className="home-eyebrow">오늘의 빈 시간을 채워볼까요?</p>
        <h1>
          오늘의 빈 시간을
          <br />
          채워볼까요?
        </h1>
        <p className="home-intro-copy">
          현재 위치와 남은 시간, 하고 싶은 일을 적으면 주변 지역과 실제 이동
          경로까지 추천해드려요.
        </p>
      </section>
      <button
        className={`location-card location-card--${status}`}
        type="button"
        onClick={() =>
          status === "success" ? clearLocation() : requestLocation()
        }
      >
        <span className="location-icon">⌖</span>
        <span>
          <strong>{locationText}</strong>
          <small>
            {status === "success"
              ? address?.road_address ||
                address?.jibun_address ||
                address?.display_name ||
                (addressStatus === "unavailable"
                  ? "주소를 확인하지 못했어요 · 좌표는 적용됐어요"
                  : "도로명 주소를 확인하고 있어요")
              : "눌러서 현재 위치 확인하기"}
          </small>
        </span>
        <span
          className="location-action"
          aria-label={
            status === "success"
              ? "한 번 더 누르면 현재 위치 사용 해제"
              : undefined
          }
        >
          {status === "loading" ? "…" : status === "success" ? "✓" : "›"}
        </span>
      </button>
      <form className="recommendation-form" onSubmit={handleSubmit}>
        <div className="recommendation-label-row">
          <label htmlFor="recommendation-message">
            어떤 시간을 보내고 싶으세요?
          </label>
          <button
            className="prompt-help-trigger"
            type="button"
            aria-label="자연어 질문 작성 도움말 열기"
            aria-expanded={promptHelpOpen}
            onClick={() => setPromptHelpOpen(true)}
          >
            <span>입력 도움말</span>
            <b aria-hidden="true">?</b>
          </button>
        </div>
        <p className="recommendation-hint">
          현재 위치·남은 시간·하고 싶은 일을 편하게 적어주세요.
        </p>
        <div className="message-compose">
          <textarea
            ref={messageInputRef}
            id="recommendation-message"
            value={message}
            onChange={(event) => setMessage(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                event.currentTarget.form?.requestSubmit();
              }
            }}
            spellCheck={false}
            placeholder={"예) 지금 신림역이고 카페에서 쉬다가 산책하고 싶어."}
          />
          <button
            className="koala-auto-button"
            type="button"
            onClick={() => setTimePickerOpen(true)}
            disabled={pendingQuickCourse !== null}
          >
            <span className="koala-auto-icon" aria-hidden="true">✨</span>
            <span className="koala-auto-copy">
              <b>
                {pendingQuickCourse
                  ? "코알라가 코스를 찾고 있어요"
                  : "자동 코스 추천"}
              </b>
              <small>하고 싶은 일이 없어도 시간만 정하면 코알라가 짜드려요</small>
            </span>
            <em>{pendingQuickCourse ? "추천 중" : "시간만 선택"} <i>→</i></em>
          </button>
          <section className="home-adventure-store" aria-label="색다른 추천">
            <div className="home-adventure-head">
              <span><b>색다른 추천</b><small>평소와 다른 하루를 골라보세요</small></span>
              <em>옆으로 보기 →</em>
            </div>
            <div className="home-adventure-cards">
              {[
                ["blind-course", "🎁", "블라인드 코스", "목적지는 나중에 공개"],
                ["course", "🎲", "랜덤 코스", "고민 없이 바로 출발"],
                ["quest", "✓", "오늘의 퀘스트", "작지만 새로운 도전"],
              ].map(([mode, icon, title, copy]) => (
                <button key={mode} type="button" onClick={() => { setPendingAdventureMode(mode); setTimePickerOpen(true); }}>
                  <i>{icon}</i><b>{title}</b><small>{copy}</small>
                </button>
              ))}
            </div>
          </section>
        </div>
        {(quickCourseError || error) && (
          <p className="recommendation-error">{quickCourseError || error}</p>
        )}
        <button
          className="recommendation-cta"
          type="submit"
          disabled={!message.trim() || pendingQuickCourse !== null}
        >
          추천받기 <span>→</span>
        </button>
      </form>
      {account?.user && savedCourses[0] && (
        <button
          className="home-recent-course"
          type="button"
          onClick={() => openSavedCourse(savedCourses[0])}
        >
          <span>
            <small>최근 코스 이어보기</small>
            <strong>{savedCourses[0].title}</strong>
          </span>
          <b>열기 →</b>
        </button>
      )}
      {timePickerOpen && (
        <div
          className="time-picker-backdrop"
          role="presentation"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) setTimePickerOpen(false);
          }}
        >
          <section
            className="time-picker-dialog"
            role="dialog"
            aria-modal="true"
            aria-labelledby="time-picker-title"
          >
            <div className="time-picker-head">
              <span aria-hidden="true">🐨</span>
              <div>
                <small>{pendingAdventureMode ? "코알라 모험 모드" : "코알라 자동 코스"}</small>
                <h2 id="time-picker-title">얼마나 여유가 있나요?</h2>
                <p>이 시간 안에서 이동과 방문을 모두 맞춰드려요.</p>
              </div>
            </div>
            <div className="auto-time-wheel-picker">
              <TimeWheel
                label="시간"
                values={COURSE_HOURS}
                value={courseHours}
                onChange={setCourseHours}
                suffix="시간"
              />
              <strong>:</strong>
              <TimeWheel
                label="분"
                values={COURSE_MINUTES}
                value={courseMinutes}
                onChange={setCourseMinutes}
                suffix="분"
              />
            </div>
            <div className="time-picker-summary">
              <span>선택한 시간</span>
              <b>
                {selectedDurationMinutes >= 30
                  ? `${selectedDurationMinutes}분`
                  : "최소 30분"}
              </b>
              <small>실제 코스는 약 10%의 이동 여유를 남겨요</small>
            </div>
            <div className="time-picker-actions">
              <button type="button" onClick={() => setTimePickerOpen(false)}>
                취소
              </button>
              <button
                type="button"
                className="is-primary"
                disabled={selectedDurationMinutes < 30}
                onClick={confirmAutoCourseTime}
              >
                이 시간으로 추천받기
              </button>
            </div>
          </section>
        </div>
      )}
      {appointmentPromptOpen && (
        <div
          className="time-picker-backdrop"
          role="presentation"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget)
              setAppointmentPromptOpen(false);
          }}
        >
          <section
            className="time-picker-dialog appointment-time-dialog"
            role="dialog"
            aria-modal="true"
            aria-labelledby="appointment-time-title"
          >
            <div className="time-picker-head">
              <span aria-hidden="true">🕒</span>
              <div>
                <small>다음 일정 시간 확인</small>
                <h2 id="appointment-time-title">약속이 몇 시인가요?</h2>
                <p>도착 시간에 늦지 않는 코스를 계산할게요.</p>
              </div>
            </div>
            <div className="appointment-time-options">
              {suggestedAppointmentHours(pendingAppointmentMessage).map(
                (hour) => (
                  <button
                    key={hour}
                    type="button"
                    onClick={() => submitAppointmentTime(hour)}
                  >
                    {hour < 12 ? "오전" : "오후"} {hour > 12 ? hour - 12 : hour}시
                  </button>
                ),
              )}
            </div>
            <button
              className="appointment-time-cancel"
              type="button"
              onClick={() => setAppointmentPromptOpen(false)}
            >
              문장 다시 입력하기
            </button>
          </section>
        </div>
      )}
      {accountOpen && (
        <div className="account-modal" role="dialog" aria-modal="true">
          <div className="account-panel">
            <button
              className="account-close"
              type="button"
              onClick={closeAccount}
            >
              ×
            </button>
            {account?.user ? (
              <form onSubmit={savePreferences}>
                <h2>{account.user.nickname}님의 선호</h2>
                <p className="personalization-summary">
                  {account.personalization?.interaction_count
                    ? `${account.personalization.interaction_count}개의 선택을 추천에 반영하고 있어요.`
                    : "장소를 저장하고 코스를 확정하면 취향을 학습해요."}
                </p>
                {isMockAuthEnabled() && (
                  <p className="mock-auth-notice">
                    개발용 임시 계정 · 이 기기에만 저장돼요
                  </p>
                )}
                <label>
                  이동수단
                  <select
                    name="transport_mode"
                    defaultValue={
                      account.preferences?.transport_mode ?? "public_transit"
                    }
                  >
                    <option value="public_transit">대중교통</option>
                    <option value="car">자동차</option>
                    <option value="walk">도보</option>
                    <option value="auto">자동 선택</option>
                  </select>
                </label>
                <label>
                  공간
                  <select
                    name="space_preference"
                    defaultValue={
                      account.preferences?.space_preference ?? "any"
                    }
                  >
                    <option value="any">상관없음</option>
                    <option value="indoor">실내</option>
                    <option value="outdoor">야외</option>
                  </select>
                </label>
                <fieldset className="preference-activities">
                  <legend>좋아하는 활동</legend>
                  {[
                    ["food", "맛집"],
                    ["cafe", "카페"],
                    ["walk", "산책"],
                    ["culture", "문화"],
                    ["entertainment", "놀거리"],
                    ["shopping", "쇼핑"],
                    ["drink", "술집"],
                  ].map(([code, label]) => (
                    <label key={code}>
                      <input
                        type="checkbox"
                        name="activities"
                        value={code}
                        defaultChecked={
                          (account.preferences?.activity_preferences?.[code] ??
                            0) >= 4
                        }
                      />
                      {label}
                    </label>
                  ))}
                </fieldset>
                <section className="saved-course-list">
                  <b>즐겨찾기 장소</b>
                  {favoritePlaces.length ? (
                    favoritePlaces.map((place) => (
                      <div key={place.place_key}>
                        <button
                          className="saved-course-open"
                          type="button"
                          onClick={() => {
                            setMessage(`${place.place_name}을 포함해서 지금 갈 코스를 추천해줘.`);
                            setAccountOpen(false);
                          }}
                        >
                          <strong>{place.place_name}</strong>
                          <small>{place.category ?? "저장한 장소"} · 코스에 넣기</small>
                        </button>
                        <button type="button" onClick={() => removeFavorite(place.place_key)}>
                          삭제
                        </button>
                      </div>
                    ))
                  ) : (
                    <small>즐겨찾기한 장소가 아직 없어요.</small>
                  )}
                </section>
                <section className="saved-course-list">
                  <b>숨긴 장소</b>
                  {excludedPlaces.length ? (
                    excludedPlaces.map((place) => (
                      <div key={place.place_key}>
                        <span className="saved-course-open">
                          <strong>{place.place_name}</strong>
                          <small>추천에서 제외 중</small>
                        </span>
                        <button type="button" onClick={() => restorePlace(place.place_key)}>
                          복원
                        </button>
                      </div>
                    ))
                  ) : (
                    <small>숨긴 장소가 없어요.</small>
                  )}
                </section>
                <section className="saved-course-list">
                  <b>저장한 코스</b>
                  {savedCourses.length ? (
                    savedCourses.map((course) => (
                      <div key={course.id}>
                        <button
                          className="saved-course-open"
                          type="button"
                          onClick={() => openSavedCourse(course)}
                        >
                          <strong>{course.title}</strong>
                          <small>
                            {new Date(course.created_at).toLocaleDateString(
                              "ko-KR",
                            )}
                            {" · 지도에서 다시 보기"}
                          </small>
                        </button>
                        <button
                          type="button"
                          onClick={() => removeSavedCourse(course.id)}
                        >
                          삭제
                        </button>
                      </div>
                    ))
                  ) : (
                    <small>저장한 코스가 아직 없어요.</small>
                  )}
                  {savedCourseNotice && <p>{savedCourseNotice}</p>}
                </section>
                {accountError && <p>{accountError}</p>}
                <button type="submit">선호 저장</button>
                <button
                  className="account-logout"
                  type="button"
                  onClick={() => {
                    localStorage.removeItem("koala-token");
                    onAccountChange({
                      token: null,
                      user: null,
                      preferences: null,
                      personalization: null,
                    });
                    setAccountOpen(false);
                  }}
                >
                  로그아웃
                </button>
              </form>
            ) : (
              <form onSubmit={handleAccount}>
                <h2>{accountMode === "login" ? "로그인" : "회원가입"}</h2>
                {isMockAuthEnabled() && (
                  <p className="mock-auth-notice">
                    개발용 임시 로그인 모드예요 · 실제 DB에는 저장되지 않아요
                  </p>
                )}
                {accountMode === "signup" && (
                  <input name="nickname" placeholder="닉네임" required />
                )}
                <input
                  name="email"
                  type="email"
                  placeholder="이메일"
                  required
                />
                <input
                  name="password"
                  type="password"
                  placeholder="비밀번호 8자 이상"
                  minLength="8"
                  required
                />
                {accountError && <p>{accountError}</p>}
                <button type="submit">
                  {accountMode === "login" ? "로그인" : "가입하고 로그인"}
                </button>
                <button
                  className="account-switch"
                  type="button"
                  onClick={() =>
                    setAccountMode(accountMode === "login" ? "signup" : "login")
                  }
                >
                  {accountMode === "login"
                    ? "처음이신가요? 회원가입"
                    : "이미 계정이 있어요"}
                </button>
              </form>
            )}
          </div>
        </div>
      )}
      <PromptHelpDialog
        open={promptHelpOpen}
        onClose={() => setPromptHelpOpen(false)}
        onSelectExample={usePromptExample}
      />
    </main>
  );
}

export default HomePage;
