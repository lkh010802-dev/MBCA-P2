const APPOINTMENT_WORDS =
  /(약속|일정|만나|미팅|예약|도착(?:해야|하기)|가야\s*(?:해|하는데)|들어가야|출발해야)/;
const VAGUE_TIME_WORDS = /(아침|점심|오후|저녁|밤)/;
const RELATIVE_DEADLINE_WORDS =
  /(이따(?:가)?|그\s*때까지|그\s*전(?:에)?|가기\s*전(?:에)?|도착하기\s*전(?:에)?)/;
const EXPLICIT_CLOCK = /(오전|오후)?\s*\d{1,2}\s*(?:시|:\s*\d{2})/;

export function needsAppointmentTimeClarification(message) {
  const text = String(message ?? "").trim();
  return (
    APPOINTMENT_WORDS.test(text) &&
    (VAGUE_TIME_WORDS.test(text) || RELATIVE_DEADLINE_WORDS.test(text)) &&
    !EXPLICIT_CLOCK.test(text)
  );
}

export function suggestedAppointmentHours(message) {
  const text = String(message ?? "");
  if (/아침/.test(text)) return [8, 9, 10];
  if (/점심/.test(text)) return [12, 13, 14];
  if (/밤/.test(text)) return [20, 21, 22];
  if (/오후/.test(text) && !/저녁/.test(text)) return [15, 16, 17];
  return [18, 19, 20];
}

export function addAppointmentTime(message, hour) {
  const period = hour < 12 ? "오전" : "오후";
  const displayHour = hour > 12 ? hour - 12 : hour;
  return `${String(message).trim()} 약속 시간은 ${period} ${displayHour}시야.`;
}
