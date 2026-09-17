export function resolveCourseArea({
  pinnedArea,
  autoCourseMode,
  targetArea,
  currentArea,
  rankingAreas,
  selectedIndex,
}) {
  if (pinnedArea) return pinnedArea;
  if (autoCourseMode) return targetArea ?? currentArea ?? null;
  return rankingAreas?.[selectedIndex] ?? currentArea ?? null;
}
