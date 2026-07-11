import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { logChartZoom, markWheelEvent } from "./chartZoomDebug";

const MIN_VISIBLE_BARS = 3;
/** Log-scaling factor — larger deltaY → stronger zoom (TradingView-like). */
const WHEEL_ZOOM_SENSITIVITY = 0.0022;

export function useChartZoomPan(
  barCount: number,
  viewportW: number,
  padLeft: number,
  padRight: number,
  enableDragPan = true,
) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const [barPitch, setBarPitch] = useState(1);
  const [scrollLeft, setScrollLeft] = useState(0);
  const barPitchRef = useRef(barPitch);
  barPitchRef.current = barPitch;

  const plotInner = Math.max(viewportW - padLeft - padRight, 100);

  const minPitch = barCount > 0 ? plotInner / barCount : 1;
  const maxPitch = barCount > 0 ? plotInner / Math.min(MIN_VISIBLE_BARS, barCount) : 1;

  const contentWidth = padLeft + padRight + barCount * barPitch;

  const visibleRange = useMemo(() => {
    if (barCount === 0 || barPitch <= 0 || viewportW <= 0) {
      return { start: 0, end: 0, count: 0 };
    }
    const start = Math.max(0, Math.floor((scrollLeft - padLeft) / barPitch));
    const end = Math.min(
      barCount - 1,
      Math.ceil((scrollLeft + viewportW - padLeft) / barPitch) - 1,
    );
    const safeEnd = Math.max(start, end);
    return { start, end: safeEnd, count: safeEnd - start + 1 };
  }, [barCount, barPitch, scrollLeft, viewportW, padLeft]);

  const clampScroll = useCallback(
    (nextScroll: number, pitch: number) => {
      const el = scrollRef.current;
      const viewW = el?.clientWidth ?? viewportW;
      const cw = padLeft + padRight + barCount * pitch;
      return Math.max(0, Math.min(nextScroll, cw - viewW));
    },
    [barCount, padLeft, padRight, viewportW],
  );

  const applyScroll = useCallback(
    (nextScroll: number, pitch?: number) => {
      const el = scrollRef.current;
      if (!el) return;
      const usePitch = pitch ?? barPitchRef.current;
      const clamped = clampScroll(nextScroll, usePitch);
      el.scrollLeft = clamped;
      setScrollLeft(clamped);
    },
    [clampScroll],
  );

  const centerOnBar = useCallback(
    (barIndex: number, pitch?: number) => {
      const el = scrollRef.current;
      if (!el || barCount <= 0) return;
      const usePitch = pitch ?? barPitchRef.current;
      const viewW = el.clientWidth;
      const anchorContentX = padLeft + barIndex * usePitch + usePitch / 2;
      applyScroll(anchorContentX - viewW / 2, usePitch);
    },
    [barCount, padLeft, applyScroll],
  );

  const centerOnBarWithVisibleCount = useCallback(
    (barIndex: number, targetVisibleBars: number) => {
      if (barCount <= 0 || viewportW <= 0) return;
      const inner = Math.max(viewportW - padLeft - padRight, 100);
      const pitch = Math.min(maxPitch, Math.max(minPitch, inner / targetVisibleBars));
      logChartZoom("fit-visible-count", {
        barIndex,
        targetVisibleBars,
        pitch,
        viewportW,
        minPitch,
        maxPitch,
      });
      setBarPitch(pitch);
      requestAnimationFrame(() => centerOnBar(barIndex, pitch));
    },
    [barCount, viewportW, padLeft, padRight, minPitch, maxPitch, centerOnBar],
  );

  const zoomToFitAll = useCallback(() => {
    if (barCount <= 0) return;
    logChartZoom("fit-all", { minPitch, barCount });
    setBarPitch(minPitch);
    requestAnimationFrame(() => applyScroll(0, minPitch));
  }, [barCount, minPitch, applyScroll]);

  const onScroll = useCallback(() => {
    const el = scrollRef.current;
    if (el) setScrollLeft(el.scrollLeft);
  }, []);

  // Wheel zoom (TradingView-style: cursor-centered, smooth log scaling) + Shift+wheel horizontal pan
  useEffect(() => {
    const el = scrollRef.current;
    if (!el || barCount <= 0) return;

    const handleWheel = (e: WheelEvent) => {
      e.preventDefault();
      const seq = markWheelEvent();

      if (e.shiftKey) {
        logChartZoom("wheel-pan", {
          seq,
          deltaY: e.deltaY,
          deltaX: e.deltaX,
          scrollLeft: el.scrollLeft,
          scrollElClientH: el.clientHeight,
          scrollElScrollH: el.scrollHeight,
        });
        applyScroll(el.scrollLeft + e.deltaY);
        return;
      }

      const pitch = barPitchRef.current;
      const inner = Math.max(el.clientWidth - padLeft - padRight, 100);
      const minP = inner / barCount;
      const maxP = Math.max(minP, inner / Math.min(MIN_VISIBLE_BARS, barCount));

      const rect = el.getBoundingClientRect();
      const mouseViewportX = e.clientX - rect.left;
      const mouseContentX = el.scrollLeft + mouseViewportX;

      const plotWidth = barCount * pitch;
      const focusRatio =
        plotWidth > 0 ? Math.max(0, Math.min(1, (mouseContentX - padLeft) / plotWidth)) : 0;

      const scale = Math.exp(-e.deltaY * WHEEL_ZOOM_SENSITIVITY);
      const nextPitch = Math.min(maxP, Math.max(minP, pitch * scale));
      const nextContentWidth = padLeft + padRight + barCount * nextPitch;
      const visibleBefore = Math.ceil(inner / pitch);
      const visibleAfter = Math.ceil(inner / nextPitch);

      logChartZoom("wheel-zoom", {
        seq,
        deltaY: e.deltaY,
        deltaX: e.deltaX,
        deltaMode: e.deltaMode,
        pitchBefore: pitch,
        pitchAfter: nextPitch,
        scale,
        minPitch: minP,
        maxPitch: maxP,
        clamped: Math.abs(nextPitch - pitch) < 1e-6,
        contentWidthBefore: padLeft + padRight + barCount * pitch,
        contentWidthAfter: nextContentWidth,
        visibleBarsBefore: visibleBefore,
        visibleBarsAfter: visibleAfter,
        scrollLeft: el.scrollLeft,
        scrollElClientH: el.clientHeight,
        scrollElScrollH: el.scrollHeight,
        scrollElClientW: el.clientWidth,
        scrollElScrollW: el.scrollWidth,
      });

      if (Math.abs(nextPitch - pitch) < 1e-6) return;

      const nextPlotWidth = barCount * nextPitch;
      const anchorContentX = padLeft + focusRatio * nextPlotWidth;
      const nextScroll = anchorContentX - mouseViewportX;

      setBarPitch(nextPitch);
      applyScroll(nextScroll, nextPitch);
    };

    el.addEventListener("wheel", handleWheel, { passive: false });
    return () => el.removeEventListener("wheel", handleWheel);
  }, [barCount, padLeft, applyScroll]);

  // Click + drag to pan
  useEffect(() => {
    const el = scrollRef.current;
    if (!el || !enableDragPan) return;

    let dragging = false;
    let startX = 0;
    let startScroll = 0;

    const onMouseDown = (e: MouseEvent) => {
      if (e.button !== 0) return;
      dragging = true;
      startX = e.clientX;
      startScroll = el.scrollLeft;
      el.style.cursor = "grabbing";
      e.preventDefault();
    };

    const onMouseMove = (e: MouseEvent) => {
      if (!dragging) return;
      applyScroll(startScroll - (e.clientX - startX));
    };

    const onMouseUp = () => {
      dragging = false;
      el.style.cursor = "";
    };

    el.addEventListener("mousedown", onMouseDown);
    window.addEventListener("mousemove", onMouseMove);
    window.addEventListener("mouseup", onMouseUp);
    return () => {
      el.removeEventListener("mousedown", onMouseDown);
      window.removeEventListener("mousemove", onMouseMove);
      window.removeEventListener("mouseup", onMouseUp);
    };
  }, [applyScroll, enableDragPan]);

  return {
    scrollRef,
    barPitch,
    scrollLeft,
    contentWidth,
    visibleStart: visibleRange.start,
    visibleEnd: visibleRange.end,
    visibleCount: visibleRange.count,
    minPitch,
    maxPitch,
    onScroll,
    centerOnBar,
    centerOnBarWithVisibleCount,
    zoomToFitAll,
  };
}
