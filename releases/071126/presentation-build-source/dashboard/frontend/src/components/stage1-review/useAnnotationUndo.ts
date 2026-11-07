import { useCallback, useSyncExternalStore } from "react";
import {
  getAnnotationUndoSnapshot,
  pushAnnotationUndo,
  subscribeAnnotationUndo,
  undoAnnotationLast,
  clearAnnotationUndo,
} from "./annotationUndoStore";

export type { UndoEntry } from "./annotationUndoStore";

export function useAnnotationUndo(syncAfterUndo?: () => Promise<void>) {
  const snapshot = useSyncExternalStore(
    subscribeAnnotationUndo,
    getAnnotationUndoSnapshot,
    getAnnotationUndoSnapshot,
  );

  const pushUndo = useCallback((label: string, undo: () => Promise<void>) => {
    pushAnnotationUndo(label, undo);
  }, []);

  const undoLast = useCallback(async () => {
    return undoAnnotationLast(syncAfterUndo);
  }, [syncAfterUndo]);

  const clearUndo = useCallback(() => {
    clearAnnotationUndo();
  }, []);

  return {
    pushUndo,
    undoLast,
    canUndo: snapshot.canUndo,
    lastActionLabel: snapshot.lastActionLabel,
    stackSize: snapshot.stackSize,
    clearUndo,
  };
}
