import iconTransit from "../assets/images/icon-transit.png";
import iconCar from "../assets/images/icon-car.png";
import iconWalk from "../assets/images/icon-walk.png";
import placeFood from "../assets/images/place-food.png";
import placeCafe from "../assets/images/place-cafe.png";
import placeCulture from "../assets/images/place-culture.png";
import placeWalk from "../assets/images/place-walk.png";

// 추천 계산과 무관한 화면 표시 설정만 한곳에서 관리한다.
export const categoryLabels = {
  food: "식당",
  cafe: "카페",
  walk: "산책",
  culture: "문화",
  entertainment: "즐길거리",
  shopping: "쇼핑",
  drink: "술집",
};

export const stayMinutesByCategory = {
  food: 60,
  cafe: 45,
  walk: 45,
  culture: 90,
  entertainment: 90,
  shopping: 60,
  drink: 90,
};

export const categoryIcons = {
  food: "🍽",
  cafe: "☕",
  walk: "🌿",
  culture: "🖼",
  entertainment: "🎟",
  shopping: "🛍",
  drink: "🍷",
};

export const categoryFallbackImages = {
  food: placeFood,
  cafe: placeCafe,
  walk: placeWalk,
  culture: placeCulture,
};

export const courseStopColors = ["#ec7b22", "#159b63", "#dc3f78", "#9b59b6"];

export const transportOptions = [
  { id: "public_transit", label: "대중교통", icon: iconTransit },
  { id: "car", label: "자동차", icon: iconCar },
  { id: "walk", label: "도보", icon: iconWalk },
];

export const timeHourOptions = [0, 1, 2, 3, 4, 5, 6, 7, 8];
export const timeMinuteOptions = [0, 10, 20, 30, 40, 50];

