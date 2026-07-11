export interface UndoEntry {
  label: string;
  undo: () => Promise<void>;
}

export type AnnotationUndoSnapshot = {
  canUndo: boolean;
  lastActionLabel: string | null;
  stackSize: number;
  version: number;
};

const MAX_UNDO = 50;

let stack: UndoEntry[] = [];
let busy = false;
let version = 0;
const listeners = new Set<() => void>();

let cachedSnapshot: AnnotationUndoSnapshot = {
  canUndo: false,
  lastActionLabel: null,
  stackSize: 0,
  version: 0,
};

function refreshSnapshot(): void {
  cachedSnapshot = {
    canUndo: stack.length > 0,
    lastActionLabel: stack.at(-1)?.label ?? null,
    stackSize: stack.length,
    version,
  };
}

function emit(): void {
  version += 1;
  refreshSnapshot();
  listeners.forEach((listener) => listener());
}

export function subscribeAnnotationUndo(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function getAnnotationUndoSnapshot(): AnnotationUndoSnapshot {
  return cachedSnapshot;
}

export function pushAnnotationUndo(label: string, undo: () => Promise<void>): void {
  stack = [...stack.slice(-(MAX_UNDO - 1)), { label, undo }];
  emit();
}

export async function undoAnnotationLast(syncAfterUndo?: () => Promise<void>): Promise<string | null> {
  if (busy) return null;
  const entry = stack.at(-1);
  if (!entry) return null;

  busy = true;
  try {
    await entry.undo();
    stack = stack.slice(0, -1);
    emit();
    if (syncAfterUndo) await syncAfterUndo();
    return entry.label;
  } finally {
    busy = false;
  }
}

export function clearAnnotationUndo(): void {
  stack = [];
  emit();
}
