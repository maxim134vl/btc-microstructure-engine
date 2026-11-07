import type { ReviewCandleBar, VolumeLocationMarker, WindowOverlayEvent } from "../../types/eventReview";
import { reviewKey } from "../../types/eventReview";
import type { CognitiveEventClass, CognitiveReviewContext, CognitiveReviewEvent } from "../../types/cognitiveReview";

function toNumber(value: unknown): number | null {
  if (value === null || value === undefined || value === "") return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function markersFromEvent(event: CognitiveReviewEvent, bar?: ReviewCandleBar): VolumeLocationMarker[] {
  const low = toNumber(event.low) ?? bar?.low ?? null;
  const high = toNumber(event.high) ?? bar?.high ?? null;
  const close = toNumber(event.close) ?? bar?.close ?? null;

  if (low != null && high != null) {
    return [
      {
        price: close ?? (low + high) / 2,
        zone_low: low,
        zone_high: high,
        event_class: event.event_class,
      },
    ];
  }

  if (close != null) {
    return [{ price: close, event_class: event.event_class }];
  }

  return [];
}

export function buildCognitiveWindowOverlayEvents(params: {
  allEvents: CognitiveReviewEvent[];
  context: CognitiveReviewContext;
  classSelection: Record<CognitiveEventClass, boolean>;
  currentEvent: CognitiveReviewEvent;
  apiWindowEvents?: WindowOverlayEvent[];
}): WindowOverlayEvent[] {
  const { allEvents, context, classSelection, currentEvent, apiWindowEvents = [] } = params;
  const { window_start, window_end, bars } = context;

  const markerByKey = new Map<string, VolumeLocationMarker[]>();
  for (const event of apiWindowEvents) {
    if (event.volume_location_markers.length > 0) {
      markerByKey.set(reviewKey(event.timestamp, event.event_class), event.volume_location_markers);
    }
  }

  const barByIndex = new Map<number, ReviewCandleBar>();
  for (const bar of bars) {
    barByIndex.set(bar.index, bar);
  }

  return allEvents
    .filter(
      (event) =>
        event.bar_index != null &&
        event.bar_index >= window_start &&
        event.bar_index <= window_end &&
        classSelection[event.event_class],
    )
    .map((event) => {
      const barIndexInWindow = event.bar_index! - window_start;
      const overlayClass = event.event_class === "MISSED_EVENT" ? "MISSED_EVENT" : event.event_class;
      const key = reviewKey(event.timestamp, overlayClass);
      const bar = barByIndex.get(barIndexInWindow);
      const markers = markerByKey.get(key) ?? markersFromEvent(event, bar);

      return {
        timestamp: event.timestamp,
        event_class: overlayClass as WindowOverlayEvent["event_class"],
        bar_index_in_window: barIndexInWindow,
        volume_location_markers: markers,
        is_primary:
          event.annotation_id === currentEvent.annotation_id ||
          (event.timestamp === currentEvent.timestamp && event.event_class === currentEvent.event_class),
      };
    })
    .filter((event) => event.volume_location_markers.length > 0)
    .sort((a, b) => a.timestamp.localeCompare(b.timestamp));
}
