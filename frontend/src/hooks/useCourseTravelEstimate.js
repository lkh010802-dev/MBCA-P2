import { useEffect, useRef, useState } from "react";
import { requestRoutePreview } from "../api/placesApi";
import {
  buildCourseSegments,
  courseSegmentCacheKey,
  estimateFallbackRoute,
  routeDurationMinutes,
} from "../utils/courseTravelEstimate";

// 같은 구간을 다시 선택할 때 외부 경로 API를 반복 호출하지 않는다.
const segmentCache = new Map();

async function loadSegment(segment, transportMode) {
  const key = courseSegmentCacheKey(segment, transportMode);
  if (!segmentCache.has(key)) {
    const request = requestRoutePreview({
      startLatitude: segment.from.latitude,
      startLongitude: segment.from.longitude,
      endLatitude: segment.to.latitude,
      endLongitude: segment.to.longitude,
      transportMode,
    })
      .then((route) => {
        const durationMinutes = routeDurationMinutes(route);
        if (durationMinutes == null) throw new Error("경로 시간 정보가 없어요.");
        return { route, durationMinutes };
      })
      .catch((error) => {
        segmentCache.delete(key);
        throw error;
      });
    segmentCache.set(key, request);
  }
  return segmentCache.get(key);
}

export function useCourseTravelEstimate({
  startLocation,
  selectedPlaces,
  endLocation,
  transportMode,
  debounceMs = 300,
}) {
  const generationRef = useRef(0);
  const [estimate, setEstimate] = useState({
    status: "idle",
    travelMinutes: null,
    segments: [],
    failedSegments: [],
  });

  useEffect(() => {
    const generation = ++generationRef.current;
    if (!selectedPlaces.length) {
      return undefined;
    }

    const segments = buildCourseSegments(
      startLocation,
      selectedPlaces,
      endLocation,
    );
    if (!segments) {
      const unavailableTimer = window.setTimeout(() => {
        if (generation === generationRef.current) {
          setEstimate({
            status: "unavailable",
            travelMinutes: null,
            segments: [],
            failedSegments: [],
          });
        }
      }, 0);
      return () => window.clearTimeout(unavailableTimer);
    }

    const loadingTimer = window.setTimeout(() => {
      if (generation === generationRef.current) {
        setEstimate((current) => ({ ...current, status: "loading" }));
      }
    }, 0);
    const timer = window.setTimeout(async () => {
      const results = await Promise.allSettled(
        segments.map((segment) => loadSegment(segment, transportMode)),
      );
      if (generation !== generationRef.current) return;

      const failedSegments = results
        .map((result, index) => (result.status === "rejected" ? index : null))
        .filter((index) => index != null);
      const resolvedSegments = results.map((result, index) => {
        if (result.status === "fulfilled") {
          return {
            ...result.value,
            status:
              result.value.route?.calculation_status === "estimated"
                ? "estimated"
                : "exact",
          };
        }
        return estimateFallbackRoute(segments[index], transportMode);
      });
      if (resolvedSegments.some((segment) => segment == null)) {
        setEstimate({
          status: "unavailable",
          travelMinutes: null,
          segments: resolvedSegments,
          failedSegments,
        });
        return;
      }
      setEstimate({
        status: resolvedSegments.some((segment) => segment.status === "estimated")
          ? "estimated"
          : "ready",
        travelMinutes: resolvedSegments.reduce(
          (sum, result) => sum + result.durationMinutes,
          0,
        ),
        segments: resolvedSegments,
        failedSegments,
      });
    }, debounceMs);

    return () => {
      window.clearTimeout(loadingTimer);
      window.clearTimeout(timer);
    };
  }, [
    startLocation,
    selectedPlaces,
    endLocation,
    transportMode,
    debounceMs,
  ]);

  return selectedPlaces.length
    ? estimate
    : {
        status: "idle",
        travelMinutes: null,
        segments: [],
        failedSegments: [],
      };
}
