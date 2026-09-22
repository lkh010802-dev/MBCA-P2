export const PROMPT_EXAMPLES = [
  {
    id: "available-time",
    label: "여유시간 중심",
    text: "지금 신림역인데 3시간 동안 어디 갈까?",
  },
  {
    id: "activity-combination",
    label: "하고 싶은 일 중심",
    text: "현재 위치에서 카페에 갔다가 산책하고 싶어",
  },
  {
    id: "next-appointment",
    label: "다음 일정 중심",
    text: "8시까지 잠실에 가기 전에 전시를 보고 싶어",
  },
];

// 홈 화면의 추천 기능이 서로 어떻게 다른지 도움말에서 한눈에 보여준다.
export const RECOMMENDATION_GUIDES = [
  {
    id: "auto-course",
    icon: "✨",
    title: "자동 코스 추천",
    summary: "하고 싶은 일이 정해지지 않았을 때",
    description:
      "사용 가능한 시간만 선택하면 현재 위치와 이동시간을 고려해 방문 순서까지 자동으로 구성합니다.",
  },
  {
    id: "blind-course",
    icon: "🎁",
    title: "블라인드 코스",
    summary: "목적지를 미리 알고 싶지 않을 때",
    description:
      "코스는 먼저 준비하되 장소는 진행 과정에서 공개해, 선택의 고민 없이 새로운 곳을 경험하게 합니다.",
  },
  {
    id: "random-course",
    icon: "🎲",
    title: "랜덤 코스",
    summary: "평소와 다른 선택이 필요할 때",
    description:
      "현재 지역과 시간 안에서 가능한 후보를 바탕으로 평소와 다른 코스 하나를 골라 제안합니다.",
  },
  {
    id: "daily-quest",
    icon: "✓",
    title: "오늘의 퀘스트",
    summary: "부담 없는 작은 도전을 원할 때",
    description:
      "짧게 실행할 수 있는 활동을 과제처럼 제안해 평범한 일정에 새로운 경험을 더합니다.",
  },
];
