export type PolicyDemoIdentity = {
  generation: number;
  scenarioId: string;
  sessionId: string | null;
};

export type PolicyDemoAsyncState<Challenge, HistoryEvent> = PolicyDemoIdentity & {
  latestChallengeRequestId: number;
  latestHistoryRequestId: number;
  challengeStatus: "idle" | "loading" | "success" | "error";
  challenge: Challenge | null;
  challengeError: string;
  historyStatus: "idle" | "loading" | "ready" | "error";
  historyEvents: HistoryEvent[];
  historyError: string;
};

export type PolicyDemoAsyncAction<Challenge, HistoryEvent> =
  | { type: "scenarioChanged"; generation: number; scenarioId: string }
  | { type: "sessionCreated"; generation: number; scenarioId: string; sessionId: string }
  | { type: "sessionResetStarted"; previous: PolicyDemoIdentity; generation: number }
  | { type: "sessionResetSucceeded"; identity: PolicyDemoIdentity }
  | { type: "challengeStarted"; identity: PolicyDemoIdentity; requestId: number }
  | { type: "challengeSucceeded"; identity: PolicyDemoIdentity; requestId: number; result: Challenge }
  | { type: "challengeFailed"; identity: PolicyDemoIdentity; requestId: number; error: string }
  | { type: "historyStarted"; identity: PolicyDemoIdentity; requestId: number }
  | { type: "historySucceeded"; identity: PolicyDemoIdentity; requestId: number; events: HistoryEvent[] }
  | { type: "historyFailed"; identity: PolicyDemoIdentity; requestId: number; error: string }
  | { type: "historyAppended"; identity: PolicyDemoIdentity; event: HistoryEvent };

export function samePolicyDemoIdentity(current: PolicyDemoIdentity, expected: PolicyDemoIdentity): boolean {
  return current.generation === expected.generation &&
    current.scenarioId === expected.scenarioId &&
    current.sessionId === expected.sessionId;
}

export function policyDemoAsyncReducer<Challenge, HistoryEvent>(
  state: PolicyDemoAsyncState<Challenge, HistoryEvent>,
  action: PolicyDemoAsyncAction<Challenge, HistoryEvent>,
): PolicyDemoAsyncState<Challenge, HistoryEvent> {
  if (action.type === "scenarioChanged") {
    if (action.generation <= state.generation) return state;
    return {
      ...state,
      generation: action.generation,
      scenarioId: action.scenarioId,
      sessionId: null,
      challengeStatus: "idle",
      challenge: null,
      challengeError: "",
      historyStatus: "idle",
      historyEvents: [],
      historyError: "",
    };
  }

  if (action.type === "sessionCreated") {
    if (state.generation !== action.generation || state.scenarioId !== action.scenarioId) return state;
    return { ...state, sessionId: action.sessionId };
  }

  if (action.type === "sessionResetStarted") {
    if (!samePolicyDemoIdentity(state, action.previous) || action.generation <= state.generation) return state;
    return {
      ...state,
      generation: action.generation,
      challengeStatus: state.challengeStatus === "loading" ? "idle" : state.challengeStatus,
      challengeError: "",
      historyStatus: state.historyStatus === "loading" ? (state.historyEvents.length ? "ready" : "idle") : state.historyStatus,
      historyError: "",
    };
  }

  if (action.type === "sessionResetSucceeded") {
    if (!samePolicyDemoIdentity(state, action.identity)) return state;
    return {
      ...state,
      challengeStatus: "idle",
      challenge: null,
      challengeError: "",
      historyStatus: "idle",
      historyEvents: [],
      historyError: "",
    };
  }

  if (!samePolicyDemoIdentity(state, action.identity)) return state;

  if (action.type === "challengeStarted") {
    if (action.requestId < state.latestChallengeRequestId) return state;
    return { ...state, latestChallengeRequestId: action.requestId, challengeStatus: "loading", challengeError: "" };
  }
  if (action.type === "challengeSucceeded") {
    if (action.requestId !== state.latestChallengeRequestId) return state;
    return { ...state, challengeStatus: "success", challenge: action.result, challengeError: "" };
  }
  if (action.type === "challengeFailed") {
    if (action.requestId !== state.latestChallengeRequestId) return state;
    return { ...state, challengeStatus: "error", challengeError: action.error };
  }
  if (action.type === "historyStarted") {
    if (action.requestId < state.latestHistoryRequestId) return state;
    return { ...state, latestHistoryRequestId: action.requestId, historyStatus: "loading", historyEvents: [], historyError: "" };
  }
  if (action.type === "historySucceeded") {
    if (action.requestId !== state.latestHistoryRequestId) return state;
    return { ...state, historyStatus: "ready", historyEvents: action.events, historyError: "" };
  }
  if (action.type === "historyFailed") {
    if (action.requestId !== state.latestHistoryRequestId) return state;
    return { ...state, historyStatus: "error", historyEvents: [], historyError: action.error };
  }
  return { ...state, historyStatus: "ready", historyEvents: [...state.historyEvents, action.event], historyError: "" };
}

export const initialPolicyDemoAsyncState: PolicyDemoAsyncState<never, never> = {
  generation: 0,
  scenarioId: "scheduling",
  sessionId: null,
  latestChallengeRequestId: 0,
  latestHistoryRequestId: 0,
  challengeStatus: "idle",
  challenge: null,
  challengeError: "",
  historyStatus: "idle",
  historyEvents: [],
  historyError: "",
};

export async function loadScenarioMetadata<T>(options: {
  isCurrent: () => boolean;
  load: () => Promise<T>;
  onSuccess: (metadata: T) => void;
}): Promise<void> {
  try {
    const metadata = await options.load();
    if (options.isCurrent()) options.onSuccess(metadata);
  } catch {
    // Metadata is optional; the built-in selector list remains available on failure.
  }
}

export async function loadScenarioAndCreateSession<Scenario, Session>(options: {
  isCurrent: () => boolean;
  loadScenario: () => Promise<Scenario>;
  createSession: (scenario: Scenario) => Promise<Session>;
  onSuccess: (scenario: Scenario, session: Session) => void;
}): Promise<void> {
  const scenario = await options.loadScenario();
  if (!options.isCurrent()) return;
  const session = await options.createSession(scenario);
  if (options.isCurrent()) options.onSuccess(scenario, session);
}

/** Share an in-flight load across StrictMode effect replay without caching its result. */
export function loadOnceWhilePending<T>(
  inFlight: Map<string, Promise<T>>,
  key: string,
  load: () => Promise<T>,
): Promise<T> {
  const existing = inFlight.get(key);
  if (existing) return existing;

  const request = Promise.resolve().then(load);
  inFlight.set(key, request);
  const clear = () => {
    if (inFlight.get(key) === request) inFlight.delete(key);
  };
  void request.then(clear, clear);
  return request;
}
