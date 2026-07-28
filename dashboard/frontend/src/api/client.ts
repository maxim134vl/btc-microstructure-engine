import type { OpsSnapshot } from "../types/ops";

// Lazy URL helpers keep node test runners from evaluating Vite `import.meta.env`
// unless a real browser/Vite soft-fetch path is used.
async function opsSnapshotUrl(): Promise<string> {
  const { getApiBase } = await import("./baseUrl");
  return `${getApiBase()}/ops/snapshot`;
}

async function opsWsUrl(): Promise<string> {
  const { getWsUrl } = await import("./baseUrl");
  return getWsUrl();
}

/**
 * Soft-fetch timeout.
 *
 * Evidence (VIS1D/OPS2A): `build_runtime_truth_snapshot()` locally observed up to ~1.86s;
 * warm HTTP snapshots are usually ~10–50ms, but cold/full builds (incl. MODEL-9 research
 * pipeline) were observed ~9s and exceeded the legacy 5000ms abort, latching the UI offline.
 * 15000ms covers observed cold builds with margin without unbounded waits.
 */
export const DEFAULT_SOFT_FETCH_TIMEOUT_MS = 15000;

/** Normal poll while reconnecting / offline. */
export const OPS_RECONNECT_POLL_MS = 4000;

/** Max backoff between reconnect polls. */
export const OPS_RECONNECT_MAX_BACKOFF_MS = 15_000;

/** Failures before RECONNECTING → OFFLINE (banner semantics). */
export const OPS_OFFLINE_AFTER_FAILURES = 2;

export type OpsLivePhase = "LIVE" | "RECONNECTING" | "OFFLINE";

export type SoftFetchFailureReason = "timeout" | "http" | "network" | "aborted";

export type SoftFetchOutcome =
  | { ok: true; snapshot: OpsSnapshot; requestId: number; elapsedMs: number }
  | { ok: false; reason: SoftFetchFailureReason; requestId: number; elapsedMs: number };

export type SoftFetchDeps = {
  fetchImpl?: typeof fetch;
  now?: () => number;
  setTimeoutFn?: typeof setTimeout;
  clearTimeoutFn?: typeof clearTimeout;
};

export async function fetchOpsSnapshot(): Promise<OpsSnapshot> {
  const response = await fetch(await opsSnapshotUrl());
  if (!response.ok) throw new Error(`ops snapshot ${response.status}`);
  return response.json();
}

function isAbortError(err: unknown): boolean {
  return Boolean(
    err &&
      typeof err === "object" &&
      "name" in err &&
      (err as { name?: string }).name === "AbortError",
  );
}

/**
 * Soft live fetch — never throws.
 * One request → one AbortController → timeout cleared in finally → controller never reused.
 */
export async function softFetchOpsSnapshotDetailed(
  timeoutMs: number = DEFAULT_SOFT_FETCH_TIMEOUT_MS,
  opts?: SoftFetchDeps & { requestId?: number; externalSignal?: AbortSignal },
): Promise<SoftFetchOutcome> {
  const requestId = opts?.requestId ?? 0;
  const fetchImpl = opts?.fetchImpl ?? fetch;
  const now = opts?.now ?? (() => Date.now());
  const setTimeoutFn = opts?.setTimeoutFn ?? setTimeout;
  const clearTimeoutFn = opts?.clearTimeoutFn ?? clearTimeout;
  const controller = new AbortController();
  const started = now();

  const onExternalAbort = () => controller.abort();
  if (opts?.externalSignal) {
    if (opts.externalSignal.aborted) {
      return { ok: false, reason: "aborted", requestId, elapsedMs: 0 };
    }
    opts.externalSignal.addEventListener("abort", onExternalAbort, { once: true });
  }

  const timer = setTimeoutFn(() => controller.abort(), timeoutMs);
  try {
    // When a custom fetchImpl is injected (tests), avoid resolving Vite env URLs.
    const url = opts?.fetchImpl
      ? "http://ops.test/api/v1/ops/snapshot"
      : await opsSnapshotUrl();
    const response = await fetchImpl(url, {
      signal: controller.signal,
      cache: "no-store",
    });
    if (!response.ok) {
      return { ok: false, reason: "http", requestId, elapsedMs: now() - started };
    }
    const snapshot = (await response.json()) as OpsSnapshot;
    return { ok: true, snapshot, requestId, elapsedMs: now() - started };
  } catch (err) {
    const elapsedMs = now() - started;
    if (opts?.externalSignal?.aborted) {
      return { ok: false, reason: "aborted", requestId, elapsedMs };
    }
    if (isAbortError(err) || controller.signal.aborted) {
      return { ok: false, reason: "timeout", requestId, elapsedMs };
    }
    return { ok: false, reason: "network", requestId, elapsedMs };
  } finally {
    clearTimeoutFn(timer as unknown as number);
    opts?.externalSignal?.removeEventListener("abort", onExternalAbort);
  }
}

/** Soft live fetch — never throws; returns null when API is unavailable. */
export async function softFetchOpsSnapshot(
  timeoutMs: number = DEFAULT_SOFT_FETCH_TIMEOUT_MS,
  opts?: SoftFetchDeps,
): Promise<OpsSnapshot | null> {
  const outcome = await softFetchOpsSnapshotDetailed(timeoutMs, opts);
  return outcome.ok ? outcome.snapshot : null;
}

export async function fetchDebugSnapshot(): Promise<unknown> {
  const { getApiBase } = await import("./baseUrl");
  const response = await fetch(`${getApiBase()}/debug/snapshot`);
  const payload = await response.json().catch(() => null);
  if (!response.ok) {
    const reason =
      payload && typeof payload === "object" && "error" in payload
        ? String((payload as { error?: unknown }).error)
        : `HTTP ${response.status}`;
    return {
      ok: false,
      status: "degraded",
      error: `Debug snapshot unavailable: ${reason}`,
      snapshot: {},
      warnings: [{ section: "debug_snapshot", reason }],
    };
  }
  return payload;
}

export type OpsSocketHandle = {
  close: () => void;
};

/**
 * Soft WebSocket to live ops hub.
 * Reconnects with backoff while open; never throws; safe when API is down.
 *
 * LIVE connected status is driven by successful snapshot frames only — not onopen —
 * so a bare socket open cannot latch "online" without data or stop HTTP reconnect polls.
 */
export function connectOps(
  onSnapshot: (data: OpsSnapshot) => void,
  onStatus: (ok: boolean) => void,
): OpsSocketHandle {
  let closed = false;
  let socket: WebSocket | null = null;
  let reconnectTimer: number | null = null;
  let attempt = 0;

  const clearReconnect = () => {
    if (reconnectTimer != null) {
      window.clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }
  };

  const scheduleReconnect = () => {
    if (closed) return;
    clearReconnect();
    const delay = Math.min(30_000, 1_000 * 2 ** Math.min(attempt, 5));
    attempt += 1;
    reconnectTimer = window.setTimeout(open, delay);
  };

  const open = () => {
    if (closed) return;
    clearReconnect();
    void opsWsUrl()
      .then((wsUrl) => {
        if (closed) return;
        try {
          socket = new WebSocket(wsUrl);
        } catch {
          onStatus(false);
          scheduleReconnect();
          return;
        }

        socket.onopen = () => {
          attempt = 0;
          // Do not mark connected here — wait for a snapshot payload.
        };
        socket.onclose = () => {
          onStatus(false);
          socket = null;
          scheduleReconnect();
        };
        socket.onerror = () => {
          onStatus(false);
          try {
            socket?.close();
          } catch {
            /* ignore */
          }
        };
        socket.onmessage = (event) => {
          try {
            const payload = JSON.parse(event.data);
            if (payload.type === "snapshot" && payload.data) {
              onSnapshot(payload.data);
              onStatus(true);
            }
          } catch {
            /* ignore malformed frames */
          }
        };
      })
      .catch(() => {
        onStatus(false);
        scheduleReconnect();
      });
  };

  open();

  return {
    close: () => {
      closed = true;
      clearReconnect();
      onStatus(false);
      try {
        socket?.close();
      } catch {
        /* ignore */
      }
      socket = null;
    },
  };
}

export type OpsLiveSessionHandlers = {
  onSnapshot: (snapshot: OpsSnapshot) => void;
  onConnected: (connected: boolean) => void;
  onPhase?: (phase: OpsLivePhase) => void;
};

export type OpsLiveSessionOptions = OpsLiveSessionHandlers &
  SoftFetchDeps & {
    softFetch?: typeof softFetchOpsSnapshotDetailed;
    connectSocket?: typeof connectOps;
    timeoutMs?: number;
    pollIntervalMs?: number;
    maxBackoffMs?: number;
    offlineAfterFailures?: number;
  };

export type OpsLiveSessionHandle = {
  stop: () => void;
  getPhase: () => OpsLivePhase;
  getStats: () => {
    requestCount: number;
    failureCount: number;
    successCount: number;
    timeoutCount: number;
    latestRequestId: number;
    phase: OpsLivePhase;
  };
};

/**
 * HTTP reconnect loop + optional WS upgrade.
 *
 * State machine:
 *   LIVE → transient failure → RECONNECTING → success → LIVE
 *   LIVE → repeated failures → OFFLINE → success → LIVE
 *
 * Guarantees:
 * - polling continues after errors (single timer)
 * - fresh AbortController per request
 * - offline/error cleared on first success
 * - stale/late failures cannot overwrite a newer success (request generation)
 */
export function startOpsLiveSession(options: OpsLiveSessionOptions): OpsLiveSessionHandle {
  const softFetch = options.softFetch ?? softFetchOpsSnapshotDetailed;
  const connectSocket = options.connectSocket ?? connectOps;
  const timeoutMs = options.timeoutMs ?? DEFAULT_SOFT_FETCH_TIMEOUT_MS;
  const basePollMs = options.pollIntervalMs ?? OPS_RECONNECT_POLL_MS;
  const maxBackoffMs = options.maxBackoffMs ?? OPS_RECONNECT_MAX_BACKOFF_MS;
  const offlineAfterFailures = options.offlineAfterFailures ?? OPS_OFFLINE_AFTER_FAILURES;
  const setTimeoutFn = options.setTimeoutFn ?? setTimeout;
  const clearTimeoutFn = options.clearTimeoutFn ?? clearTimeout;

  let stopped = false;
  let phase: OpsLivePhase = "RECONNECTING";
  let consecutiveFailures = 0;
  let requestCount = 0;
  let failureCount = 0;
  let successCount = 0;
  let timeoutCount = 0;
  let latestRequestId = 0;
  let inFlight = false;
  let pollTimer: ReturnType<typeof setTimeout> | null = null;
  let socket: OpsSocketHandle | null = null;
  let backoffAttempt = 0;
  let activeExternalAbort: AbortController | null = null;

  const setPhase = (next: OpsLivePhase) => {
    if (phase === next) return;
    phase = next;
    options.onPhase?.(next);
  };

  const clearPoll = () => {
    if (pollTimer != null) {
      clearTimeoutFn(pollTimer as unknown as number);
      pollTimer = null;
    }
  };

  const schedulePoll = (delayMs: number) => {
    if (stopped) return;
    clearPoll();
    pollTimer = setTimeoutFn(() => {
      pollTimer = null;
      void tick();
    }, delayMs);
  };

  const attachSocket = () => {
    if (stopped || socket) return;
    socket = connectSocket(
      (live) => {
        if (stopped) return;
        // WS snapshots advance the generation so they win over in-flight HTTP.
        requestCount += 1;
        latestRequestId = requestCount;
        consecutiveFailures = 0;
        backoffAttempt = 0;
        successCount += 1;
        options.onSnapshot(live);
        options.onConnected(true);
        setPhase("LIVE");
        // Keep a slow heartbeat poll even while LIVE so HTTP recovery remains possible
        // if WS stalls without closing.
        schedulePoll(basePollMs * 2);
      },
      (ok) => {
        if (stopped) return;
        if (!ok) {
          options.onConnected(false);
          if (phase === "LIVE") setPhase("RECONNECTING");
          schedulePoll(0);
        }
      },
    );
  };

  const tick = async () => {
    if (stopped) return;
    // Single logical poller: if a request is still in flight, abort it and start a
    // fresh generation so hung/timed-out work cannot latch offline forever.
    if (inFlight && activeExternalAbort) {
      activeExternalAbort.abort();
    }
    inFlight = true;
    requestCount += 1;
    const requestId = requestCount;
    latestRequestId = requestId;
    const externalAbort = new AbortController();
    activeExternalAbort = externalAbort;

    const outcome = await softFetch(timeoutMs, {
      requestId,
      fetchImpl: options.fetchImpl,
      now: options.now,
      setTimeoutFn,
      clearTimeoutFn,
      externalSignal: externalAbort.signal,
    });

    if (activeExternalAbort === externalAbort) {
      activeExternalAbort = null;
    }
    inFlight = false;
    if (stopped) return;

    // Late responses from older generations must not mutate state.
    if (requestId !== latestRequestId) {
      schedulePoll(basePollMs);
      return;
    }

    if (outcome.ok) {
      consecutiveFailures = 0;
      backoffAttempt = 0;
      successCount += 1;
      options.onSnapshot(outcome.snapshot);
      options.onConnected(true);
      setPhase("LIVE");
      attachSocket();
      schedulePoll(basePollMs * 2);
      return;
    }

    // Aborted because a newer poll superseded this request — not a real failure.
    if (outcome.reason === "aborted") {
      schedulePoll(basePollMs);
      return;
    }

    failureCount += 1;
    consecutiveFailures += 1;
    if (outcome.reason === "timeout") timeoutCount += 1;
    options.onConnected(false);
    setPhase(consecutiveFailures >= offlineAfterFailures ? "OFFLINE" : "RECONNECTING");
    backoffAttempt += 1;
    const delay = Math.min(maxBackoffMs, basePollMs * 2 ** Math.min(backoffAttempt - 1, 3));
    schedulePoll(delay);
  };

  setPhase("RECONNECTING");
  void tick();

  return {
    stop: () => {
      stopped = true;
      clearPoll();
      activeExternalAbort?.abort();
      activeExternalAbort = null;
      socket?.close();
      socket = null;
      options.onConnected(false);
    },
    getPhase: () => phase,
    getStats: () => ({
      requestCount,
      failureCount,
      successCount,
      timeoutCount,
      latestRequestId,
      phase,
    }),
  };
}
