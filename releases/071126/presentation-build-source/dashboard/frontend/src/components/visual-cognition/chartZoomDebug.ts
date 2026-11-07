/** Temporary instrumentation for wheel / resize feedback-loop investigation. */
export const CHART_ZOOM_DEBUG = import.meta.env.DEV;

let lastWheelAt = 0;
let wheelSeq = 0;

export function markWheelEvent(): number {
  lastWheelAt = performance.now();
  wheelSeq += 1;
  return wheelSeq;
}

export function msSinceLastWheel(): number {
  return lastWheelAt > 0 ? performance.now() - lastWheelAt : -1;
}

export function logChartZoom(source: string, payload: Record<string, unknown>): void {
  if (!CHART_ZOOM_DEBUG) return;
  console.log(`[chart-zoom] ${source}`, {
    t: performance.now().toFixed(1),
    msSinceWheel: msSinceLastWheel(),
    wheelSeq,
    ...payload,
  });
}

export function logChartLayoutDiagnostics(payload: {
  chartHeight: number;
  containerHeight: number;
  navigatorHeight: number;
  pageHeight: number;
}): void {
  if (!CHART_ZOOM_DEBUG) return;
  console.log(payload);
}
