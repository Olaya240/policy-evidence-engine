export type ChallengeRequestIdentity = {
  investigationId: string;
  requestId: number;
};

export function isChallengeRequestCurrent(
  identity: ChallengeRequestIdentity,
  activeInvestigationId: string | null,
  latestRequestId: number,
): boolean {
  return identity.investigationId === activeInvestigationId && identity.requestId === latestRequestId;
}

export type ChallengeWorkflowOptions<ChallengeResponse, RefreshedInvestigation> = {
  identity: ChallengeRequestIdentity;
  isCurrent: () => boolean;
  submit: () => Promise<ChallengeResponse>;
  refresh: () => Promise<RefreshedInvestigation>;
  onSuccess: (response: ChallengeResponse, investigation: RefreshedInvestigation) => void;
  onFailure: (error: unknown) => void;
  onSettled: () => void;
};

/** Runs the same guarded submission/refresh/completion sequence used by App. */
export async function runChallengeWorkflow<ChallengeResponse, RefreshedInvestigation>(
  options: ChallengeWorkflowOptions<ChallengeResponse, RefreshedInvestigation>,
): Promise<void> {
  try {
    let response: ChallengeResponse;
    try {
      response = await options.submit();
    } catch (error) {
      if (options.isCurrent()) options.onFailure(error);
      return;
    }

    if (!options.isCurrent()) return;
    const investigation = await options.refresh();
    if (!options.isCurrent()) return;
    options.onSuccess(response, investigation);
  } finally {
    if (options.isCurrent()) options.onSettled();
  }
}

export type ChallengeRefreshOptions<Investigation, History> = {
  isCurrent: () => boolean;
  loadInvestigation: () => Promise<Investigation>;
  loadHistory: () => Promise<History>;
  onInvestigation: (investigation: Investigation) => void;
  onInvestigationError: (error: unknown) => void;
  onHistoryStart: () => void;
  onHistory: (history: History) => void;
  onHistoryError: (error: unknown) => void;
};

/** Keeps detail and history refresh outcomes independent and guards every write. */
export async function refreshAfterChallenge<Investigation, History>(
  options: ChallengeRefreshOptions<Investigation, History>,
): Promise<Investigation | null> {
  if (!options.isCurrent()) return null;

  let investigation: Investigation | null = null;
  try {
    investigation = await options.loadInvestigation();
  } catch (error) {
    if (options.isCurrent()) options.onInvestigationError(error);
  }

  if (!options.isCurrent()) return investigation;
  if (investigation !== null) options.onInvestigation(investigation);

  if (!options.isCurrent()) return investigation;
  options.onHistoryStart();
  try {
    const history = await options.loadHistory();
    if (options.isCurrent()) options.onHistory(history);
  } catch (error) {
    if (options.isCurrent()) options.onHistoryError(error);
  }
  return investigation;
}
