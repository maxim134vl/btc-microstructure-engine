import type { AnchorLabelRu } from "../../types/manualAnnotations";
import type { Stage1EventClass } from "../../types/eventReview";

const EVENT_CLASS_TO_ANCHOR_LABEL: Record<string, AnchorLabelRu> = {
  BUYING_CLIMAX: "Кульминация покупок",
  SELLING_CLIMAX: "Кульминация продаж",
  STOPPING_VOLUME: "Останавливающий объем",
  HIGH_AVERAGE_VOLUME: "Источник объема",
};

export function anchorLabelForEventClass(eventClass: string): AnchorLabelRu {
  return EVENT_CLASS_TO_ANCHOR_LABEL[eventClass] ?? "Другое";
}

export function isSupportedEventClass(eventClass: string): eventClass is Stage1EventClass {
  return eventClass in EVENT_CLASS_TO_ANCHOR_LABEL || eventClass.length > 0;
}
