export type HistoryLoadState<T> = {
  investigationId: string | null;
  requestId: number;
  status: "idle" | "loading" | "ready" | "error";
  entries: T[];
  error: string;
};

export type HistoryLoadAction<T> =
  | { type: "invalidate"; requestId: number }
  | { type: "begin"; investigationId: string; requestId: number }
  | { type: "success"; investigationId: string; requestId: number; entries: T[] }
  | { type: "failure"; investigationId: string; requestId: number; error: string };

export function historyLoadReducer<T>(state: HistoryLoadState<T>, action: HistoryLoadAction<T>): HistoryLoadState<T> {
  if (action.type === "invalidate") {
    if (action.requestId < state.requestId) return state;
    return { investigationId: null, requestId: action.requestId, status: "idle", entries: [], error: "" };
  }
  if (action.type === "begin") {
    if (action.requestId < state.requestId) return state;
    return { investigationId: action.investigationId, requestId: action.requestId, status: "loading", entries: [], error: "" };
  }
  if (action.requestId !== state.requestId || action.investigationId !== state.investigationId) return state;
  if (action.type === "success") return { ...state, status: "ready", entries: action.entries, error: "" };
  return { ...state, status: "error", entries: [], error: action.error };
}

export const initialHistoryLoadState: HistoryLoadState<never> = {
  investigationId: null, requestId: 0, status: "idle", entries: [], error: "",
};

export type AppLifecycleIdentity = { mounted: boolean; epoch: number };

export function activateAppLifecycle(identity: AppLifecycleIdentity): number {
  identity.epoch += 1;
  identity.mounted = true;
  return identity.epoch;
}

export function invalidateAppLifecycle(identity: AppLifecycleIdentity, epoch: number): void {
  if (identity.epoch !== epoch) return;
  identity.mounted = false;
  identity.epoch += 1;
}

export function isAppLifecycleCurrent(identity: AppLifecycleIdentity, epoch: number): boolean {
  return identity.mounted && identity.epoch === epoch;
}

export type LifecycleRequestOptions<T> = {
  isCurrent: () => boolean;
  request: () => Promise<T>;
  onSuccess: (result: T) => void;
  onFailure: (error: unknown) => void;
  onSettled?: () => void;
};

/** Publishes async outcomes only while the owning lifecycle and request remain current. */
export async function runLifecycleRequest<T>(options: LifecycleRequestOptions<T>): Promise<void> {
  try {
    let result: T;
    try {
      result = await options.request();
    } catch (error) {
      if (options.isCurrent()) options.onFailure(error);
      return;
    }
    if (options.isCurrent()) options.onSuccess(result);
  } finally {
    if (options.isCurrent()) options.onSettled?.();
  }
}

export type InvestigationCreationOptions<T> = {
  isCurrent: () => boolean;
  create: () => Promise<T>;
  onSuccess: (result: T) => void;
  onFailure: (error: unknown) => void;
  onSettled: () => void;
};

/** The latest creation request alone may publish a result, error, or settled state. */
export async function runInvestigationCreation<T>(options: InvestigationCreationOptions<T>): Promise<void> {
  try {
    let result: T;
    try {
      result = await options.create();
    } catch (error) {
      if (options.isCurrent()) options.onFailure(error);
      return;
    }
    if (options.isCurrent()) options.onSuccess(result);
  } finally {
    if (options.isCurrent()) options.onSettled();
  }
}
