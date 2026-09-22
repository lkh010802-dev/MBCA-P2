import { useEffect, useRef } from "react";
import {
  PROMPT_EXAMPLES,
  RECOMMENDATION_GUIDES,
} from "../../utils/promptGuidance";

function PromptHelpDialog({ open, onClose, onSelectExample }) {
  const closeButtonRef = useRef(null);

  useEffect(() => {
    if (!open) return undefined;

    const closeOnEscape = (event) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", closeOnEscape);
    closeButtonRef.current?.focus();
    return () => document.removeEventListener("keydown", closeOnEscape);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div
      className="prompt-help-backdrop"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <section
        className="prompt-help-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="prompt-help-title"
        aria-describedby="prompt-help-description"
      >
        <header>
          <span aria-hidden="true">?</span>
          <div>
            <h2 id="prompt-help-title">질문 작성 안내</h2>
            <p id="prompt-help-description">
              아래 항목을 한 문장에 적으면 조건에 맞는 코스를 추천합니다.
            </p>
          </div>
          <button
            ref={closeButtonRef}
            className="prompt-help-close"
            type="button"
            aria-label="질문 도움말 닫기"
            onClick={onClose}
          >
            ×
          </button>
        </header>

        <div className="prompt-help-formula" aria-label="질문 구성 방법">
          <span><b>1</b> 어디에서</span>
          <i aria-hidden="true">+</i>
          <span><b>2</b> 얼마나</span>
          <i aria-hidden="true">+</i>
          <span><b>3</b> 무엇을</span>
        </div>

        <div className="prompt-help-spec">
          <strong>입력 항목</strong>
          <dl>
            <div>
              <dt><b>필수</b> 장소</dt>
              <dd>현재 위치 또는 추천받고 싶은 지역</dd>
            </div>
            <div>
              <dt><b>필수</b> 시간</dt>
              <dd>사용 가능한 시간 또는 다음 일정 시각</dd>
            </div>
            <div>
              <dt><b>권장</b> 활동</dt>
              <dd>식사, 카페, 전시, 산책처럼 하고 싶은 일</dd>
            </div>
            <div>
              <dt><b>선택</b> 추가 조건</dt>
              <dd>이동수단, 실내·실외, 동행인, 분위기</dd>
            </div>
          </dl>
        </div>

        <div className="prompt-help-rules">
          <strong>코알라는 이렇게 이해합니다</strong>
          <ul>
            <li><b>“신림역에서”</b>는 활동할 지역으로 인식합니다.</li>
            <li><b>“3시간 동안”</b>은 이동과 체류를 포함한 전체 시간입니다.</li>
            <li><b>“밥 먹고 카페”</b>처럼 적으면 작성한 순서를 우선합니다.</li>
            <li><b>“8시까지 잠실”</b>은 다음 일정의 시각과 목적지로 인식합니다.</li>
          </ul>
        </div>

        <div className="prompt-help-features">
          <div className="prompt-help-feature-heading">
            <strong>추천 기능 안내</strong>
            <small>상황에 맞는 방식을 선택하세요.</small>
          </div>
          <div className="prompt-help-feature-list">
            {RECOMMENDATION_GUIDES.map((guide) => (
              <article key={guide.id}>
                <i aria-hidden="true">{guide.icon}</i>
                <div>
                  <strong>{guide.title}</strong>
                  <b>{guide.summary}</b>
                  <p>{guide.description}</p>
                </div>
              </article>
            ))}
          </div>
        </div>

        <div className="prompt-help-examples">
          <div className="prompt-help-example-heading">
            <strong>질문 예시</strong>
            <small>문장을 선택하면 입력창에 반영됩니다.</small>
          </div>
          {PROMPT_EXAMPLES.map((example) => (
            <button
              key={example.id}
              type="button"
              onClick={() => onSelectExample(example.text)}
            >
              <small>{example.label}</small>
              <span>{example.text}</span>
              <i aria-hidden="true">→</i>
            </button>
          ))}
        </div>

        <p className="prompt-help-note">
          모든 항목을 적지 않아도 됩니다. 필요한 핵심 조건이 없으면 추천 전에
          코알라가 한 번 더 확인합니다.
        </p>
      </section>
    </div>
  );
}

export default PromptHelpDialog;
