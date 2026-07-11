import { useEffect, useRef, useState } from "react";
import { logChartZoom } from "./chartZoomDebug";

const DEFAULT_SIZE = { width: 960, height: 280 };

export function useElementSize<T extends HTMLElement>(debugLabel?: string) {
  const ref = useRef<T>(null);
  const [size, setSize] = useState(DEFAULT_SIZE);
  const sizeRef = useRef(size);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;

    const update = () => {
      const rect = el.getBoundingClientRect();
      const next = {
        width: Math.max(Math.floor(rect.width), 320),
        height: Math.max(0, Math.floor(rect.height)),
      };
      const prev = sizeRef.current;
      if (next.width === prev.width && next.height === prev.height) return;

      if (debugLabel) {
        logChartZoom("resize-observer", {
          label: debugLabel,
          widthBefore: prev.width,
          widthAfter: next.width,
          heightBefore: prev.height,
          heightAfter: next.height,
          rectW: rect.width,
          rectH: rect.height,
          clientW: el.clientWidth,
          clientH: el.clientHeight,
        });
      }

      sizeRef.current = next;
      setSize(next);
    };

    update();
    const observer = new ResizeObserver(update);
    observer.observe(el);
    return () => observer.disconnect();
  }, [debugLabel]);

  return { ref, width: size.width, height: size.height };
}
