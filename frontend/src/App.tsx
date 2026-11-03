import { useCallback, useEffect, useMemo, useReducer, useRef, useState, type FormEvent } from "react";
import PolicyDemoPage from "./PolicyDemoPage";
import { apiRequest, ApiError } from "./api";
import type { RecordItem } from "./contracts";
import {
  activateAppLifecycle,
  historyLoadReducer,
  initialHistoryLoadState,
  invalidateAppLifecycle,
  isAppLifecycleCurrent,
  runInvestigationCreation,
  runLifecycleRequest,
} from "./historyState";
import {
  isChallengeRequestCurrent,
  refreshAfterChallenge,
  runChallengeWorkflow,
  type ChallengeRequestIdentity,
} from "./challengeWorkflow";
import { claimPresentation, evidencePresentation, recordAvailability } from "./presentation";
import {
  type Claim,
  type Investigation,
  type History,
  parseAdvisoryCoverageCategories,
  parseEvidenceDispositions,
  getEvidenceMarginMagnitude,
  formatEvidenceMarginMagnitude,
  parseUnreadableRows,
  dispositionTone,
  formatProposedStance,
  unreadableRowsWarning,
} from "./auditParsers";

type ChallengeResponsePayload = {
  version?: number;
  before?: Record<string, Claim> | Claim;
  after?: Record<string, Claim> | Claim;
  recomputed_claim_ids?: string[];
  reason?: string;
};

const HYPOTHESES: Record<string, string> = {
  CHECKLIST_UNAVAILABLE: "Checklist unavailable",
  TRAINING_GAP: "Training gap",
  STAFFING_CONSTRAINTS: "Staffing constraints",
  PMS_SYSTEM_ISSUE: "PMS system issue",
  TIME_PRESSURE: "Time pressure",
};

// Starting question prompts (Priority 1: clearly presented as question prompts; backend evaluates all 5 hypotheses)
const QUESTION_PROMPTS = [
  {
    key: "handover_omissions",
    label: "Recurring handover omissions",
    question: "Did time pressure contribute to recurring handover omissions?",
    context: "Investigates shift handover omissions across all five candidate operational hypotheses.",
  },
  {
    key: "checklist_access",
    label: "Checklist access",
    question: "Did checklist availability contribute to missing handover information?",
    context: "Focuses inquiry prompt on checklist access while backend evaluates all five hypotheses.",
  },
  {
    key: "desk_coverage",
    label: "Desk coverage",
    question: "Did staffing constraints affect how guest requests were handed over?",
    context: "Focuses inquiry prompt on desk coverage while backend evaluates all five hypotheses.",
  },
  {
    key: "property_system",
    label: "Property system",
    question: "Did property system interruptions affect handover note completion?",
    context: "Focuses inquiry prompt on PMS interruptions while backend evaluates all five hypotheses.",
  },
];

function TracePill({
  text,
  tone = "green",
}: {
  text: string;
  tone?: "green" | "orange" | "red" | "muted" | "gold" | "navy";
}) {
  const bg: Record<string, string> = {
    green: "#e4efe9",
    orange: "#f6eadf",
    red: "#f7e4e1",
    muted: "#edede8",
    gold: "#f5eed6",
    navy: "#e6ebf2",
  };
  const fg: Record<string, string> = {
    green: "#215742",
    orange: "#9a5223",
    red: "#9e3328",
    muted: "#5c6460",
    gold: "#856514",
    navy: "#1c2b3d",
  };
  return (
    <span
      style={{
        fontFamily: "var(--mono)",
        fontSize: 9.5,
        letterSpacing: "0.06em",
        padding: "4px 8px",
        background: bg[tone],
        color: fg[tone],
        borderRadius: 4,
        fontWeight: 600,
        display: "inline-block",
      }}
    >
      {text}
    </span>
  );
}

async function api<T>(
  path: string,
  operationLabel: string,
  init?: RequestInit,
  onResponse?: (response: Response) => void
): Promise<T> {
  try {
    return await apiRequest<T>(path, init, onResponse);
  } catch (err) {
    if (err instanceof ApiError) {
      throw new Error(`${operationLabel} failed: ${err.message}`);
    }
    throw new Error(
      `${operationLabel} failed: Cannot reach backend at 127.0.0.1:8081 (/api${path}). Please verify the FastAPI backend is running on port 8081. (${
        err instanceof Error ? err.message : String(err)
      })`
    );
  }
}

function extractClaimFromSnapshot(
  snapshot: Record<string, Claim> | Claim | undefined,
  claimId: string,
  hypothesisId: string
): Claim | null {
  if (!snapshot) return null;
  if ("id" in snapshot && typeof snapshot.id === "string") return snapshot as Claim;
  const map = snapshot as Record<string, Claim>;
  return map[claimId] ?? map[hypothesisId] ?? Object.values(map)[0] ?? null;
}



function App() {
  const [showDemo, setShowDemo] = useState(window.location.hash === "#/demo");

  // Priority 2: Distinct loading, empty, and error states for initial record fetch
  const [records, setRecords] = useState<RecordItem[]>([]);
  const [recordsLoading, setRecordsLoading] = useState<boolean>(true);
  const [recordsError, setRecordsError] = useState<string>("");
  const [unreadableRows, setUnreadableRows] = useState<{ count: number; ids: string[] }>({ count: 0, ids: [] });

  const [investigation, setInvestigation] = useState<Investigation | null>(null);
  const [historyState, dispatchHistory] = useReducer(historyLoadReducer<History>, initialHistoryLoadState);
  const historyRequestId = useRef(0);
  const challengeRequestId = useRef(0);
  const activeInvestigationId = useRef<string | null>(null);
  const investigationCreationRequestId = useRef(0);
  const appLifecycle = useRef({ mounted: false, epoch: 0 });
  const history = historyState.investigationId === investigation?.id ? historyState.entries : [];
  const historyLoading = historyState.investigationId === investigation?.id && historyState.status === "loading";
  const [selectedId, setSelectedId] = useState("");
  const [selectedPromptIndex, setSelectedPromptIndex] = useState(0);
  const [sourceId, setSourceId] = useState("");
  const [quote, setQuote] = useState("");
  const [reason, setReason] = useState("");

  // Priority 2: Operation-specific loading & error feedback
  const [creatingInvestigation, setCreatingInvestigation] = useState(false);
  const [investigationError, setInvestigationError] = useState("");
  const [submittingChallenge, setSubmittingChallenge] = useState(false);
  const [challengeError, setChallengeError] = useState("");
  const [investigationRefreshError, setInvestigationRefreshError] = useState("");
  const historyError = historyState.investigationId === investigation?.id ? historyState.error : "";
  const [actionBanner, setActionBanner] = useState("");

  const [change, setChange] = useState<{
    before: Claim;
    after: Claim;
    beforeVersion: number;
    afterVersion: number;
    recomputedIds: string[];
    reason: string;
    disputedIds: string[];
  } | null>(null);

  const [inspectedHistoryVersion, setInspectedHistoryVersion] = useState<number | null>(null);
  const [expandedEvidenceKey, setExpandedEvidenceKey] = useState<string | null>(null);

  // Evidence Library search & filters
  const [libraryQuery, setLibraryQuery] = useState("");
  const [libraryDeptFilter, setLibraryDeptFilter] = useState("ALL");
  const [libraryGroupFilter, setLibraryGroupFilter] = useState("ALL");

  useEffect(() => {
    const epoch = activateAppLifecycle(appLifecycle.current);
    return () => invalidateAppLifecycle(appLifecycle.current, epoch);
  }, []);

  useEffect(() => {
    const handler = () => setShowDemo(window.location.hash === "#/demo");
    window.addEventListener("hashchange", handler);
    return () => window.removeEventListener("hashchange", handler);
  }, []);

  const loadRecordsFromBackend = useCallback(async (lifecycleEpoch: number) => {
    const isCurrent = () => isAppLifecycleCurrent(appLifecycle.current, lifecycleEpoch);
    if (!isCurrent()) return;
    setRecordsLoading(true);
    setRecordsError("");
    await runLifecycleRequest({
      isCurrent,
      request: () => api<RecordItem[]>("/records", "Initial records fetch (GET /api/records)", undefined, (response) => {
        if (isCurrent()) setUnreadableRows(parseUnreadableRows(response.headers));
      }),
      onSuccess: setRecords,
      onFailure: (error) => {
        setRecords([]);
        setRecordsError((error as Error).message);
      },
      onSettled: () => setRecordsLoading(false),
    });
  }, []);

  useEffect(() => {
    if (!showDemo) {
      void loadRecordsFromBackend(appLifecycle.current.epoch);
    }
  }, [loadRecordsFromBackend, showDemo]);

  const invalidateHistory = useCallback(() => {
    const requestId = ++historyRequestId.current;
    dispatchHistory({ type: "invalidate", requestId });
  }, []);

  const loadHistory = useCallback(async (id: string) => {
    const lifecycleEpoch = appLifecycle.current.epoch;
    const isCurrent = () => isAppLifecycleCurrent(appLifecycle.current, lifecycleEpoch);
    if (!isCurrent()) return;
    const requestId = ++historyRequestId.current;
    dispatchHistory({ type: "begin", investigationId: id, requestId });
    await runLifecycleRequest({
      isCurrent: () => isCurrent() && requestId === historyRequestId.current,
      request: () => api<History[]>(`/investigations/${id}/history`, `History retrieval (${id})`),
      onSuccess: (events) => dispatchHistory({ type: "success", investigationId: id, requestId, entries: events }),
      onFailure: (error) => dispatchHistory({ type: "failure", investigationId: id, requestId, error: (error as Error).message }),
    });
  }, []);

  const refreshInvestigationAndHistory = useCallback(async (identity: ChallengeRequestIdentity, lifecycleEpoch: number) => {
    const isCurrent = () =>
      isAppLifecycleCurrent(appLifecycle.current, lifecycleEpoch) &&
      isChallengeRequestCurrent(identity, activeInvestigationId.current, challengeRequestId.current);
    let historyRequestIdForRefresh = 0;
    return refreshAfterChallenge<Investigation, History[]>({
      isCurrent,
      loadInvestigation: () => api<Investigation>(
        `/investigations/${identity.investigationId}`,
        `Fetch investigation (${identity.investigationId})`,
      ),
      loadHistory: () => api<History[]>(
        `/investigations/${identity.investigationId}/history`,
        `History retrieval (${identity.investigationId})`,
      ),
      onInvestigation: (next) => {
        setInvestigation(next);
        setSelectedId((current) => current || next.claims[0]?.id || "");
        setInvestigationRefreshError("");
      },
      onInvestigationError: (error) => setInvestigationRefreshError((error as Error).message),
      onHistoryStart: () => {
        historyRequestIdForRefresh = ++historyRequestId.current;
        dispatchHistory({ type: "begin", investigationId: identity.investigationId, requestId: historyRequestIdForRefresh });
      },
      onHistory: (events) => dispatchHistory({
        type: "success",
        investigationId: identity.investigationId,
        requestId: historyRequestIdForRefresh,
        entries: events,
      }),
      onHistoryError: (error) => dispatchHistory({
        type: "failure",
        investigationId: identity.investigationId,
        requestId: historyRequestIdForRefresh,
        error: (error as Error).message,
      }),
    });
  }, []);

  const selected = useMemo(
    () => investigation?.claims.find((claim) => claim.id === selectedId) ?? null,
    [investigation, selectedId]
  );
  const chosenRecord = useMemo(() => records.find((record) => record.id === sourceId), [records, sourceId]);

  const inspectedHistoryEntry = useMemo(
    () => history.find((h) => h.version === inspectedHistoryVersion) ?? null,
    [history, inspectedHistoryVersion]
  );

  const statusCounts = useMemo(() => {
    if (!investigation) {
      return { supported: 0, partial: 0, contradicted: 0, insufficient: 0, disputed: 0 };
    }
    return {
      supported: investigation.claims.filter((c) => c.status === "SUPPORTED").length,
      partial: investigation.claims.filter((c) => c.status === "PARTIAL").length,
      contradicted: investigation.claims.filter((c) => c.status === "CONTRADICTED").length,
      insufficient: investigation.claims.filter((c) => c.status === "INSUFFICIENT").length,
      disputed: investigation.claims.reduce((acc, c) => acc + c.evidence.filter((e) => e.disputed).length, 0),
    };
  }, [investigation]);

  const availableDepartments = useMemo(
    () => Array.from(new Set(records.map((r) => r.department))).sort(),
    [records]
  );
  const availableSourceGroups = useMemo(
    () => Array.from(new Set(records.map((r) => r.source_group).filter(Boolean) as string[])).sort(),
    [records]
  );
  const filteredLibraryRecords = useMemo(() => {
    return records.filter((rec) => {
      if (libraryDeptFilter !== "ALL" && rec.department !== libraryDeptFilter) return false;
      if (libraryGroupFilter !== "ALL" && (rec.source_group ?? "") !== libraryGroupFilter) return false;
      if (libraryQuery.trim()) {
        const q = libraryQuery.trim().toLowerCase();
        const matchId = rec.id.toLowerCase().includes(q);
        const matchText = rec.text.toLowerCase().includes(q);
        const matchTags = (rec.tags ?? []).some((t) => t.toLowerCase().includes(q));
        if (!matchId && !matchText && !matchTags) return false;
      }
      return true;
    });
  }, [records, libraryDeptFilter, libraryGroupFilter, libraryQuery]);

  async function startInvestigation() {
    const lifecycleEpoch = appLifecycle.current.epoch;
    if (!isAppLifecycleCurrent(appLifecycle.current, lifecycleEpoch)) return;
    setCreatingInvestigation(true);
    setInvestigationError("");
    setChallengeError("");
    const requestId = ++investigationCreationRequestId.current;
    const isCurrent = () =>
      isAppLifecycleCurrent(appLifecycle.current, lifecycleEpoch) &&
      requestId === investigationCreationRequestId.current;
    setActionBanner("");
    setChange(null);
    setInspectedHistoryVersion(null);
    const chosen = QUESTION_PROMPTS[selectedPromptIndex];

    await runInvestigationCreation<Investigation>({
      isCurrent,
      // Priority 1: Keep existing API contract intact (`{ question }`) without claiming preset_id scopes backend analysis
      create: () => api<Investigation>("/investigations", "Investigation creation (POST /api/investigations)", {
        method: "POST",
        body: JSON.stringify({ question: chosen.question }),
      }),
      onSuccess: (result) => {
        challengeRequestId.current += 1;
        invalidateHistory();
        activeInvestigationId.current = result.id;
        setSubmittingChallenge(false);
        setChallengeError("");
        setInvestigationRefreshError("");
        setChange(null);
        setInspectedHistoryVersion(null);
        setInvestigation(result);
        const firstClaim = result.claims[0];
        setSelectedId(firstClaim?.id ?? "");
        if (firstClaim?.dependencies[0]) {
          setSourceId(firstClaim.dependencies[0]);
          const rec = records.find((r) => r.id === firstClaim.dependencies[0]);
          setQuote(rec?.text ?? "");
        } else {
          setSourceId("");
          setQuote("");
        }
        void loadHistory(result.id);
        setActionBanner(
          `Investigation ${result.id} created at Revision v${String(result.version).padStart(2, "0")} (${result.claims.length} hypotheses evaluated).`
        );
      },
      onFailure: (error) => setInvestigationError((error as Error).message),
      onSettled: () => {
        setCreatingInvestigation(false);
      },
    });
  }

  async function challengeClaim(event: FormEvent) {
    event.preventDefault();
    const lifecycleEpoch = appLifecycle.current.epoch;
    if (!isAppLifecycleCurrent(appLifecycle.current, lifecycleEpoch)) return;
    if (!investigation || !selected) return;
    setSubmittingChallenge(true);
    setChallengeError("");
    setInvestigationRefreshError("");
    setActionBanner("");
    const beforeFallback = selected;
    const prevInvVersion = investigation.version;
    const investigationId = investigation.id;
    const identity: ChallengeRequestIdentity = {
      investigationId,
      requestId: ++challengeRequestId.current,
    };
    const isCurrent = () =>
      isAppLifecycleCurrent(appLifecycle.current, lifecycleEpoch) &&
      isChallengeRequestCurrent(identity, activeInvestigationId.current, challengeRequestId.current);

    await runChallengeWorkflow<ChallengeResponsePayload, Investigation | null>({
      identity,
      isCurrent,
      submit: () => api<ChallengeResponsePayload>(
        `/investigations/${investigationId}/claims/${selected.id}/challenge`,
        `Challenge submission (POST /api/investigations/${investigationId}/claims/${selected.id}/challenge)`,
        {
          method: "POST",
          body: JSON.stringify({
            reason: reason.trim(),
            source_record_id: sourceId,
            quote: quote.trim(),
          }),
        },
      ),
      refresh: () => refreshInvestigationAndHistory(identity, lifecycleEpoch),
      onSuccess: (challengeRes, updatedInv) => {
        const currentInvestigation = updatedInv ?? investigation;
        const afterFromInv = currentInvestigation.claims.find((claim) => claim.id === selected.id);
        const beforeSnap =
          extractClaimFromSnapshot(challengeRes.before, selected.id, selected.hypothesis_id) ?? beforeFallback;
        const afterSnap =
          extractClaimFromSnapshot(challengeRes.after, selected.id, selected.hypothesis_id) ?? afterFromInv;

        if (afterSnap) {
          const disputedIds = afterSnap.evidence.filter((e) => e.disputed).map((e) => e.source_record_id);
          const revNum = challengeRes.version ?? updatedInv?.version ?? prevInvVersion;
          setChange({
            before: beforeSnap,
            after: afterSnap,
            beforeVersion: prevInvVersion,
            afterVersion: revNum,
            recomputedIds: challengeRes.recomputed_claim_ids ?? [selected.hypothesis_id],
            reason: challengeRes.reason ?? reason.trim(),
            disputedIds,
          });
          setInspectedHistoryVersion(revNum);
          setActionBanner(
            `Challenge succeeded: Revision updated v${String(prevInvVersion).padStart(2, "0")} → v${String(
              revNum
            ).padStart(2, "0")}. Source ${sourceId} marked DISPUTED.`
          );
        }
        setReason("");
      },
      onFailure: (error) => setChallengeError((error as Error).message),
      onSettled: () => setSubmittingChallenge(false),
    });
  }

  function chooseSource(id: string) {
    setSourceId(id);
    const record = records.find((item) => item.id === id);
    setQuote(record?.text ?? "");
  }

  if (showDemo) return <PolicyDemoPage />;

  const hasBackendExplanationTrace = Boolean(
    selected?.explanation_trace &&
      (selected.explanation_trace.status_rule_id ||
        selected.explanation_trace.confidence_rule_id ||
        selected.explanation_trace.confidence_kind ||
        selected.explanation_trace.evidence_dispositions ||
        selected.explanation_trace.advisory_coverage ||
        selected.explanation_trace.semantic_guard)
  );
  const parsedDispositions = parseEvidenceDispositions(selected?.explanation_trace?.evidence_dispositions);
  const parsedCoverageCategories = parseAdvisoryCoverageCategories(selected?.explanation_trace?.advisory_coverage);
  const selectedPresentation = selected ? claimPresentation(selected) : null;
  const recordsState = recordAvailability(recordsLoading, records.length);

  return (
    <div className="shell">
      {/* ── Top Navigation Bar (Inspired by story-client-swart.vercel.app) ── */}
      <header className="topbar">
        <a className="brand" href="#top" aria-label="Story Connect home">
          <span className="brand-mark">S</span>
          <div className="brand-text">
            <strong>storyconnect</strong>
            <span>HOSPITALITY · EVIDENCE REVIEW</span>
          </div>
        </a>

        <nav className="top-links" aria-label="Workspace jump links">
          <a href="#setup">Investigation Setup</a>
          {investigation && <a href="#findings">Hypotheses &amp; Evidence</a>}
          {investigation && <a href="#history">Revision History ({history.length})</a>}
          <a href="#library">Evidence Library ({records.length})</a>
        </nav>

        <details className="mobile-nav">
          <summary aria-label="Open workspace navigation"><span aria-hidden="true">☰</span><span>Menu</span></summary>
          <nav aria-label="Workspace navigation">
            <a href="#setup">Investigation setup</a>
            {investigation && <a href="#findings">Claims and evidence</a>}
            {investigation && <a href="#history">Revision history ({history.length})</a>}
            <a href="#library">Evidence library ({records.length})</a>
            <a href="#/demo">Policy Demo Studio</a>
          </nav>
        </details>

        <div className="nav-actions">
          <span className="env-pill">
            <span className={`pulse ${recordsError ? "is-error" : recordsState === "loading" ? "is-loading" : "is-ready"}`} />
            {recordsState === "loading" ? "CONNECTING TO EVIDENCE API" : recordsError ? "EVIDENCE API ERROR" : "EVIDENCE API READY"}
          </span>
          <a href="#/demo" className="gold-cta-link">
            Policy Demo Studio ↗
          </a>
        </div>
      </header>

      <main id="top">
        {/* ── Hero Section (Matching Story Connect Vercel Typography & Gold Accent) ── */}
        <section className="overview-hero" aria-label="Investigation overview">
          <div className="overview-copy">
        <div className="eyebrow">
          <span className="gold-dot" aria-hidden="true" />
          <span>LUXURY HOSPITALITY · EVIDENCE REVIEW</span>
        </div>

        <section className="intro">
          <div>
            <h1>
              Evidence review for <em>luxury hospitality.</em>
            </h1>
            <p>
              Review shift handover claims against their source records. Investigate candidate contributing factors,
              inspect backend decision rules when provided, challenge a cited quote, and keep a clear audit trail of
              every revision.
            </p>
          </div>
          <div className="intro-stamp">
            <span>
              HUMAN
              <br />
              REVIEW
            </span>
            <span className="stamp-star" aria-hidden="true">✓</span>
          </div>
        </section>

          </div>
          <div className="overview-panel">
            <div className="overview-panel-head">
              <strong>Investigation overview</strong>
              <span>Claims, evidence and revisions</span>
            </div>
        {/* ── Live Backend Status & Summary Cards ── */}
        <section className="kpi-ribbon" aria-label="Live workspace metrics">
          <div className="kpi-tile">
            <span className="kpi-label">SOURCE RECORD STORE</span>
            <strong>{recordsLoading ? "Loading…" : `${records.length} Returned Records`}</strong>
            <small>
              {recordsLoading
                ? "Fetching GET /api/records…"
                : recordsError
                ? "Connection error (see below)"
                : unreadableRows.count > 0
                ? `Connected · ${unreadableRows.count} unreadable row(s)`
                : "Connected to 127.0.0.1:8081"}
            </small>
          </div>
          <div className="kpi-tile">
            <span className="kpi-label">ACTIVE INVESTIGATION</span>
            <strong>{investigation ? `Rev v${String(investigation.version).padStart(2, "0")}` : "None"}</strong>
            <small>{investigation ? `${investigation.claims.length} hypotheses evaluated` : "Select a question below"}</small>
          </div>
          <div className="kpi-tile">
            <span className="kpi-label">CLAIM STATUS DISTRIBUTION</span>
            <strong>
              {investigation ? `${statusCounts.supported} Supported · ${statusCounts.partial} Partial` : "—"}
            </strong>
            <small>
              {investigation
                ? `${statusCounts.contradicted} Contradicted · ${statusCounts.insufficient} Insufficient`
                : "Awaiting investigation run"}
            </small>
          </div>
          <div className="kpi-tile">
            <span className="kpi-label">DISPUTED EVIDENCE &amp; REVISIONS</span>
            <strong>{investigation ? `${statusCounts.disputed} Disputed` : "0 Disputed"}</strong>
            <small>{history.length} total revision event(s) in history</small>
          </div>
        </section>
          </div>
        </section>

        <aside className="synthetic-banner">
          <span className="banner-icon">✳</span>
          <div>
            <strong>Synthetic case · human review required · evidence margin is not probability</strong>
            <span>
              All records are fictional. Evidence can inform inquiry; it cannot prove causation or support employee
              ranking, blame, or employment decisions. The backend confidence field is an evidence-margin magnitude,
              not a calibrated probability; its direction is reported separately when available.
            </span>
          </div>
          <span className="banner-tag">PORT 8081</span>
        </aside>

        {/* ── Priority 2: Distinct Initial Records Loading, Error, and Empty States ── */}
        {recordsLoading && (
          <div className="state-banner loading" role="status" aria-live="polite">
            <span className="spinner-dot" />
            <div>
              <strong>Loading source records from backend (127.0.0.1:8081)…</strong>
              <span>Fetching admissible shift handover records via GET /api/records.</span>
            </div>
          </div>
        )}

        {!recordsLoading && recordsError && (
          <div className="error" role="alert">
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 12 }}>
              <div>
                <strong>Failed to load source records:</strong> {recordsError}
              </div>
              <button type="button" className="quick-fill-btn" onClick={() => void loadRecordsFromBackend(appLifecycle.current.epoch)}>
                ↻ Retry GET /api/records (Port 8081)
              </button>
            </div>
          </div>
        )}

        {!recordsLoading && !recordsError && unreadableRows.count > 0 && (
          <div className="state-banner unreadable-warning" role="alert" aria-live="polite">
            <div>
              <strong>Corpus availability warning</strong>
              <span>{unreadableRowsWarning(unreadableRows, records.length)}</span>
            </div>
          </div>
        )}

        {!recordsLoading && !recordsError && records.length === 0 && (
          <div className="state-banner empty" role="status">
            <div>
              <strong>{unreadableRows.count > 0 ? "No readable source records returned" : "No source records returned (Empty Store)"}</strong>
              <span>{unreadableRows.count > 0
                ? "The backend reported unreadable rows; this response contains no records available to display."
                : <>The backend at 127.0.0.1:8081 responded with 0 records. Initialize the SQLite store (<code>PYTHONPATH=backend python -m app.store init</code>) and click Retry.</>}
              </span>
            </div>
            <button type="button" className="quick-fill-btn" onClick={() => void loadRecordsFromBackend(appLifecycle.current.epoch)}>
              ↻ Reload Records
            </button>
          </div>
        )}

        {actionBanner && (
          <div className="state-banner success" role="status" aria-live="polite">
            <div>
              <strong>Action succeeded:</strong> {actionBanner}
            </div>
            <button
              type="button"
              className="quick-fill-btn"
              style={{ padding: "4px 8px" }}
              onClick={() => setActionBanner("")}
            >
              Dismiss
            </button>
          </div>
        )}

        {investigationRefreshError && (
          <div className="error" role="alert" style={{ marginBottom: 14 }}>
            <strong>Investigation Refresh Failed:</strong> {investigationRefreshError}
          </div>
        )}

        {/* ── Section 01: Investigation Setup (Priority 1: Accurate Question Prompt Contract) ── */}
        <section id="setup" className="workspace">
          <div className="workspace-heading">
            <div>
              <span className="section-kicker">01 — INVESTIGATION SETUP</span>
              <h2>Choose an inquiry question</h2>
            </div>
            <span className="record-count">
              {recordsLoading ? "LOADING RECORDS…" : `${records.length} AVAILABLE RECORDS`}
            </span>
          </div>

          <div className="prompt-grid">
            {QUESTION_PROMPTS.map((item, i) => {
              const isSelected = selectedPromptIndex === i;
              return (
                <div
                  key={item.key}
                  className={`prompt-card ${isSelected ? "active" : ""}`}
                  role="button"
                  tabIndex={0}
                  onClick={() => setSelectedPromptIndex(i)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      setSelectedPromptIndex(i);
                    }
                  }}
                >
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                    <span className="prompt-card-badge">PROMPT 0{i + 1}</span>
                    {isSelected && <span style={{ color: "var(--gold)", fontWeight: 700, fontSize: 13 }}>✓</span>}
                  </div>
                  <strong className="prompt-card-title">{item.label}</strong>
                  <span className="prompt-card-context">{item.context}</span>
                </div>
              );
            })}
          </div>

          <div className="investigation-row">
            <label className="select-wrap">
              <span>STARTING QUESTION PROMPT</span>
              <select
                value={selectedPromptIndex}
                onChange={(e) => setSelectedPromptIndex(Number(e.target.value))}
              >
                {QUESTION_PROMPTS.map((item, i) => (
                  <option value={i} key={item.key}>
                    {item.label}
                  </option>
                ))}
              </select>
            </label>
            <div className="question-preview">
              <span>INVESTIGATION QUESTION SENT TO POST /api/investigations</span>
              <p>{QUESTION_PROMPTS[selectedPromptIndex].question}</p>
              <small style={{ color: "#6a716b", fontSize: 11 }}>
                Note: Selecting a prompt sets the inquiry question recorded on the investigation. The backend evaluates
                all five candidate hypotheses against the shared record store.
              </small>
            </div>
            <button
              className="primary"
              onClick={startInvestigation}
              disabled={creatingInvestigation || recordsLoading}
            >
              {creatingInvestigation
                ? "Running…"
                : investigation
                ? "Run Investigation Again"
                : "Run Investigation"}
              <span>→</span>
            </button>
          </div>

          {investigationError && (
            <div className="error" role="alert" style={{ marginTop: 12 }}>
              <strong>Investigation Creation Failed:</strong> {investigationError}
            </div>
          )}
        </section>

        {/* ── Priority 2: Immediate Post-Challenge Reassessment Banner ── */}
        {change && (
          <section className="change-card" role="status" aria-live="polite">
            <div className="change-mark">↻</div>
            <div style={{ flex: 1 }}>
              <div style={{ display: "flex", justifyContent: "space-between", flexWrap: "wrap", gap: 8 }}>
                <span className="section-kicker">
                  CHALLENGE RECOMPUTATION COMPLETE · REVISION v{String(change.beforeVersion).padStart(2, "0")} → v
                  {String(change.afterVersion).padStart(2, "0")}
                </span>
                <a
                  href="#history"
                  style={{ fontFamily: "var(--mono)", fontSize: 10, color: "#215742", fontWeight: 600 }}
                >
                  Jump to Revision History ↓
                </a>
              </div>
              <h3>{HYPOTHESES[change.after.hypothesis_id] ?? change.after.hypothesis_id}</h3>

              <div className="challenge-snapshot-grid">
                <div className="snapshot-box">
                  <span className="kpi-label">BEFORE CHALLENGE (CLAIM v{change.before.version})</span>
                  <strong>
                    {change.before.status} · Evidence-margin magnitude: {formatEvidenceMarginMagnitude(getEvidenceMarginMagnitude(change.before))}
                  </strong>
                  <small>{change.before.uncertainty}</small>
                </div>
                <div className="snapshot-box after">
                  <span className="kpi-label">AFTER CHALLENGE (CLAIM v{change.after.version})</span>
                  <strong>
                    {change.after.status} · Evidence-margin magnitude: {formatEvidenceMarginMagnitude(getEvidenceMarginMagnitude(change.after))}
                  </strong>
                  <small>{change.after.uncertainty}</small>
                </div>
              </div>

              <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 10 }}>
                <TracePill
                  text={`RECOMPUTED CLAIMS: ${change.recomputedIds.map((id) => HYPOTHESES[id] ?? id).join(", ")}`}
                  tone="green"
                />
                <TracePill
                  text={`DISPUTED EVIDENCE: ${
                    change.disputedIds.length > 0 ? change.disputedIds.join(", ") : "MARKED ON SOURCE"
                  }`}
                  tone="red"
                />
                <TracePill text={`CHALLENGE REASON: "${change.reason}"`} tone="muted" />
              </div>
            </div>
          </section>
        )}

        {/* ── Section 02: Hypothesis Results & Scannable Evidence Explorer ── */}
        {investigation && (
          <>
            <section id="findings" className="findings">
              <div className="workspace-heading">
                <div>
                  <span className="section-kicker">02 — EVIDENCE REVIEW &amp; CHALLENGE WORKFLOW</span>
                  <h2>Five candidate contributors</h2>
                </div>
                <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                  <span className="version-pill">SUPPORTED: {statusCounts.supported}</span>
                  <span className="version-pill">PARTIAL: {statusCounts.partial}</span>
                  <span className="version-pill">CONTRADICTED: {statusCounts.contradicted}</span>
                  <span className="version-pill">INSUFFICIENT: {statusCounts.insufficient}</span>
                  <span className="version-pill active-rev">
                    REVISION {String(investigation.version).padStart(2, "0")}
                  </span>
                </div>
              </div>

              <div className="finding-grid">
                <div className="claim-list" role="tablist" aria-label="Hypothesis claims">
                  {investigation.claims.map((claim, index) => {
                    const decConf = getEvidenceMarginMagnitude(claim);
                    const pct = decConf !== null ? Math.round(decConf * 100) : 0;
                    const disputedCount = claim.evidence.filter((e) => e.disputed).length;
                    return (
                      <button
                        className={`claim-tab ${selectedId === claim.id ? "active" : ""}`}
                        role="tab"
                        aria-selected={selectedId === claim.id}
                        key={claim.id}
                        onClick={() => {
                          setSelectedId(claim.id);
                          setChallengeError("");
                          if (claim.dependencies[0]) {
                            setSourceId(claim.dependencies[0]);
                            const defaultRec = records.find((r) => r.id === claim.dependencies[0]);
                            setQuote(defaultRec?.text ?? "");
                          } else {
                            setSourceId("");
                            setQuote("");
                          }
                        }}
                      >
                        <span className="claim-number">0{index + 1}</span>
                        <div className="claim-tab-body">
                          <span className="claim-title">
                            {HYPOTHESES[claim.hypothesis_id] ?? claim.hypothesis_id}
                          </span>
                          <span className={`status-text ${claim.status.toLowerCase()}`}>
                            {claim.status} · {decConf !== null ? `${pct}% margin magnitude` : "Margin unavailable"}
                            {" "}· {claim.evidence_direction ?? claim.explanation_trace?.evidence_direction ?? "Direction unavailable"}
                            {" "}· v{claim.version}
                            {disputedCount > 0 ? ` · ${disputedCount} DISPUTED` : ""}
                          </span>
                          <div className="conf-meter-track" aria-hidden="true">
                            <div
                              className={`conf-meter-fill ${claim.status.toLowerCase()}`}
                              style={{ width: `${pct}%` }}
                            />
                          </div>
                        </div>
                        <span className={`status-dot ${claim.status.toLowerCase()}`} />
                        <span className="chevron">›</span>
                      </button>
                    );
                  })}
                </div>

                {selected && (
                  <article className="claim-detail" role="tabpanel">
                    <div className="detail-header">
                      <div>
                        <span className="section-kicker">
                          HYPOTHESIS / {selected.hypothesis_id} · DEPENDENCIES:{" "}
                          {selected.dependencies.join(", ") || "NONE"}
                        </span>
                        <h3>{HYPOTHESES[selected.hypothesis_id] ?? selected.hypothesis_id}</h3>
                      </div>
                      <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                        <span className="status-badge">CLAIM REV v{selected.version}</span>
                        <span className={`status-badge ${selected.status.toLowerCase()}`}>{selected.status}</span>
                      </div>
                    </div>

                    <p className="claim-summary">
                      {selected.summary}
                      <span>
                        {getEvidenceMarginMagnitude(selected) !== null
                          ? `Evidence-margin magnitude ${formatEvidenceMarginMagnitude(getEvidenceMarginMagnitude(selected))} · not a probability`
                          : "Evidence-margin magnitude unavailable"}
                      </span>
                    </p>

                    {/* The API confidence field is the magnitude of an evidence margin; its sign is separate. */}
                    <div className="confidence-metrics-grid">
                      <div className="dual-conf-tile">
                        <div className="dual-conf-header">
                          <span className="kpi-label" style={{ fontWeight: 700 }}>
                            EVIDENCE-MARGIN MAGNITUDE
                          </span>
                          <TracePill text="NOT PROBABILITY" tone="navy" />
                        </div>
                        <div className="dual-conf-num">
                          {getEvidenceMarginMagnitude(selected) !== null
                            ? formatEvidenceMarginMagnitude(getEvidenceMarginMagnitude(selected))
                            : "Unavailable"}
                        </div>
                        <p className="dual-conf-desc">
                          Magnitude only. Direction comes from the backend evidence score and is displayed separately.
                        </p>
                      </div>

                      <div className="dual-conf-tile">
                        <div className="dual-conf-header">
                          <span className="kpi-label" style={{ fontWeight: 700 }}>
                            EVIDENCE DIRECTION
                          </span>
                          <TracePill text="SIGNED SCORE" tone="navy" />
                        </div>
                        <div className="dual-conf-num">{selectedPresentation?.evidenceDirection ?? selected.explanation_trace?.evidence_direction ?? "Unavailable"}</div>
                        <p className="dual-conf-desc">
                          {typeof selectedPresentation?.evidenceScore === "number"
                            ? `Backend evidence score: ${selectedPresentation.evidenceScore.toFixed(3)}. FOR, AGAINST, or NONE is supplied by the backend.`
                            : "Signed evidence score is unavailable in this response; no direction is inferred in the UI."}
                        </p>
                      </div>
                    </div>

                    {/* ── Priority 1: Explainability Panel (Strictly Backend-Provided Data Only) ── */}
                    {hasBackendExplanationTrace && selected.explanation_trace && (
                      <div className="explanation-trace-box">
                        <div
                          style={{
                            display: "flex",
                            justifyContent: "space-between",
                            alignItems: "center",
                            flexWrap: "wrap",
                            gap: 8,
                          }}
                        >
                          <span className="section-kicker" style={{ marginBottom: 0 }}>
                            BACKEND EXPLANATION TRACE (explanation_trace)
                          </span>
                          <TracePill text="PROVIDED BY BACKEND ENGINE" tone="navy" />
                        </div>

                        {(selected.explanation_trace.status_rule_id ||
                          selected.explanation_trace.confidence_rule_id ||
                          selected.explanation_trace.confidence_kind ||
                          selected.explanation_trace.semantic_guard ||
                          selected.explanation_trace.source_group_analysis) && (
                          <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 8 }}>
                            {selected.explanation_trace.status_rule_id && (
                              <TracePill
                                text={`STATUS RULE: ${selected.explanation_trace.status_rule_id}`}
                                tone="green"
                              />
                            )}
                            {selected.explanation_trace.confidence_rule_id && (
                              <TracePill
                                text={`CONFIDENCE RULE: ${selected.explanation_trace.confidence_rule_id}`}
                                tone="muted"
                              />
                            )}
                            {selected.explanation_trace.confidence_kind && (
                              <TracePill
                                text={`CONFIDENCE KIND: ${selected.explanation_trace.confidence_kind}`}
                                tone="navy"
                              />
                            )}
                            {selected.explanation_trace.semantic_guard && (
                              <TracePill
                                text={`SEMANTIC GUARD: ${selected.explanation_trace.semantic_guard.rule_set_version ?? "VERSION UNAVAILABLE"} (${typeof selected.explanation_trace.semantic_guard.enabled === "boolean" ? (selected.explanation_trace.semantic_guard.enabled ? "ACTIVE" : "DISABLED") : "STATE UNAVAILABLE"})`}
                                tone={selected.explanation_trace.semantic_guard.enabled === true ? "green" : selected.explanation_trace.semantic_guard.enabled === false ? "orange" : "muted"}
                              />
                            )}
                            {typeof selected.explanation_trace.source_group_analysis?.independent_support_group_count === "number" && (
                              <TracePill
                                text={`INDEPENDENT GROUPS: ${selected.explanation_trace.source_group_analysis.independent_support_group_count}`}
                                tone="gold"
                              />
                            )}
                          </div>
                        )}

                        {parsedDispositions.length > 0 && (
                          <div style={{ marginTop: 12 }}>
                            <span className="kpi-label">EVIDENCE DISPOSITIONS (codes: string[])</span>
                            <div style={{ display: "grid", gap: 6, marginTop: 6 }}>
                              {parsedDispositions.map((item) => (
                                <div
                                  key={item.recordKey}
                                  style={{
                                    display: "flex",
                                    alignItems: "center",
                                    flexWrap: "wrap",
                                    gap: 6,
                                    padding: "6px 8px",
                                    background: "#ffffff",
                                    border: "1px solid #e1e0d8",
                                    borderRadius: 4,
                                  }}
                                >
                                  <span
                                    style={{
                                      fontFamily: "var(--mono)",
                                      fontSize: 10,
                                      fontWeight: 700,
                                      color: "#151e28",
                                      marginRight: 4,
                                    }}
                                  >
                                    {item.recordKey}:
                                  </span>
                                  {item.codes.map((code) => (
                                    <TracePill
                                      key={`${item.recordKey}-${code}`}
                                      text={code}
                                      tone={dispositionTone(code)}
                                    />
                                  ))}
                                  {item.note && (
                                    <span style={{ fontSize: 10, color: "#69756b" }}>({item.note})</span>
                                  )}
                                </div>
                              ))}
                            </div>
                          </div>
                        )}

                        {(selected.explanation_trace.semantic_guard?.decisions?.length ?? 0) > 0 && (
                          <div className="semantic-decisions" aria-label="Backend semantic guard decisions">
                            <span className="kpi-label">SEMANTIC GUARD DECISIONS (BACKEND TRACE)</span>
                            {selected.explanation_trace.semantic_guard!.decisions!.map((decision, index) => (
                              <div className="semantic-decision" key={`${decision.source_record_id ?? "decision"}-${index}`}>
                                <strong>{decision.source_record_id ?? `Decision ${index + 1}`}</strong>
                                {decision.review_state && <span>Review: {decision.review_state}</span>}
                                {decision.proposed_stance && <span>Proposed stance: {decision.proposed_stance}</span>}
                                {decision.semantic_relation && <span>Semantic relation: {decision.semantic_relation}</span>}
                                {decision.reason_code && <span>Reason: {decision.reason_code}</span>}
                                {decision.decision_source && <span>Decision source: {decision.decision_source}</span>}
                                {typeof decision.guard_enabled === "boolean" && <span>Guard: {decision.guard_enabled ? "enabled" : "disabled"}</span>}
                                {decision.cue_ids?.length ? <span>Cues: {decision.cue_ids.join(", ")}</span> : null}
                              </div>
                            ))}
                          </div>
                        )}

                        {parsedCoverageCategories.length > 0 && (
                          <div
                            style={{
                              marginTop: 12,
                              padding: "10px 12px",
                              background: "#ffffff",
                              border: "1px solid #d8dacf",
                              borderRadius: 4,
                            }}
                          >
                            <div
                              style={{
                                display: "flex",
                                justifyContent: "space-between",
                                alignItems: "center",
                                flexWrap: "wrap",
                                gap: 6,
                                marginBottom: 8,
                              }}
                            >
                              <span className="kpi-label">
                                ADVISORY EVIDENCE COVERAGE (explanation_trace.advisory_coverage.categories)
                              </span>
                              <TracePill
                                text="ADVISORY INFORMATION ONLY · NOT PROOF OR CONFIDENCE SCORE"
                                tone="gold"
                              />
                            </div>
                            <div style={{ display: "grid", gap: 8 }}>
                              {parsedCoverageCategories.map((cat) => {
                                const isCovered = cat.state === "COVERED";
                                return (
                                  <div
                                    key={cat.name}
                                    style={{
                                      padding: "8px 10px",
                                      background: isCovered ? "#eef5f1" : "#f9f1eb",
                                      borderLeft: `3px solid ${isCovered ? "#215742" : "#b45c37"}`,
                                      display: "grid",
                                      gap: 4,
                                    }}
                                  >
                                    <div
                                      style={{
                                        display: "flex",
                                        justifyContent: "space-between",
                                        alignItems: "center",
                                        flexWrap: "wrap",
                                        gap: 8,
                                      }}
                                    >
                                      <span
                                        style={{
                                          fontFamily: "var(--mono)",
                                          fontSize: 10,
                                          fontWeight: 700,
                                          color: "#151e28",
                                        }}
                                      >
                                        {cat.name}
                                      </span>
                                      <TracePill text={cat.state} tone={isCovered ? "green" : "orange"} />
                                    </div>
                                    {(cat.matchingIds.length > 0 ||
                                      cat.freshSupportIds.length > 0 ||
                                      cat.freshContradictionIds.length > 0 ||
                                      cat.neutralEvidenceIds.length > 0 ||
                                      cat.unclassifiedEvidenceIds.length > 0 ||
                                      cat.independentGroups.length > 0 ||
                                      typeof cat.freshAcceptedCount === "number" ||
                                      typeof cat.totalEvidenceCount === "number") && (
                                      <div
                                        style={{
                                          display: "flex",
                                          flexWrap: "wrap",
                                          gap: 10,
                                          fontSize: 9.5,
                                          fontFamily: "var(--mono)",
                                          color: "#57645b",
                                        }}
                                      >
                                        {cat.matchingIds.length > 0 && (
                                          <span>Matching: {cat.matchingIds.join(", ")}</span>
                                        )}
                                        {cat.freshSupportIds.length > 0 && (
                                          <span>Fresh Support: {cat.freshSupportIds.join(", ")}</span>
                                        )}
                                        {cat.freshContradictionIds.length > 0 && (
                                          <span>Fresh Contradiction: {cat.freshContradictionIds.join(", ")}</span>
                                        )}
                                        {cat.neutralEvidenceIds.length > 0 && (
                                          <span>Neutral: {cat.neutralEvidenceIds.join(", ")}</span>
                                        )}
                                        {cat.unclassifiedEvidenceIds.length > 0 && (
                                          <span>Unclassified: {cat.unclassifiedEvidenceIds.join(", ")}</span>
                                        )}
                                        {cat.independentGroups.length > 0 && (
                                          <span>Groups: {cat.independentGroups.join(", ")}</span>
                                        )}
                                        {typeof cat.freshAcceptedCount === "number" && (
                                          <span>Fresh Count: {cat.freshAcceptedCount}</span>
                                        )}
                                        {typeof cat.totalEvidenceCount === "number" && (
                                          <span>Total Count: {cat.totalEvidenceCount}</span>
                                        )}
                                      </div>
                                    )}
                                  </div>
                                );
                              })}
                            </div>
                          </div>
                        )}
                      </div>
                    )}

                    <div className="uncertainty">
                      <span>!</span>
                      <div>
                        <b>What remains uncertain</b>
                        <p>{selected.uncertainty}</p>
                      </div>
                    </div>

                    {selected.conflicts.map((item) => (
                      <div className="conflict" key={item}>
                        <b>Conflicting evidence</b>
                        <p>{item}</p>
                      </div>
                    ))}

                    {selected.missing_evidence.map((item) => (
                      <div className="missing" key={item}>
                        <span>＋</span>
                        <p>
                          <b>Evidence gap</b>
                          <br />
                          {item}
                        </p>
                      </div>
                    ))}

                    {/* ── Priority 3: Scannable Evidence Cards with Distinct Visual States ── */}
                    <div className="evidence-heading">
                      <div>
                        <span className="section-kicker">SOURCE RECORDS</span>
                        <h4>
                          Evidence considered <span>{selected.evidence.length}</span>
                        </h4>
                      </div>
                      <div className="evidence-legend" aria-label="Evidence badge legend">
                        <span className="legend-chip supports">SUPPORTS</span>
                        <span className="legend-chip contradicts">CONTRADICTS</span>
                        <span className="legend-chip unverified">UNVERIFIED</span>
                        <span className="legend-chip stale">STALE</span>
                        <span className="legend-chip disputed">DISPUTED</span>
                      </div>
                    </div>

                    {selected.evidence.length === 0 && (
                      <p className="empty">No admissible evidence was found for this hypothesis.</p>
                    )}

                    <div className="evidence-list">
                      {selected.evidence.map((item, i) => {
                        const evKey = `${item.source_record_id}-${i}`;
                        const isExpanded = expandedEvidenceKey === evKey;
                        const fullRecord = records.find((r) => r.id === item.source_record_id);
                        const evidenceView = evidencePresentation(item);
                        const stanceClass =
                          evidenceView.disposition === "UNVERIFIED" ? "unverified" : item.stance.toLowerCase();

                        return (
                          <div
                            className={`evidence-card stance-border-${stanceClass} ${
                              item.stale ? "is-stale" : ""
                            } ${item.disputed ? "is-disputed" : ""}`}
                            key={evKey}
                          >
                            <div className="evidence-meta">
                              <span className="source-id">{item.source_record_id}</span>
                              <span className="dept-tag">{item.department}</span>
                              {(item.source_group || fullRecord?.source_group) && (
                                <span className="group-tag">
                                  GROUP: {item.source_group ?? fullRecord?.source_group}
                                </span>
                              )}
                              <time>{new Date(item.timestamp).toLocaleString()}</time>

                              <span className={`stance-pill ${stanceClass}`}>
                                {evidenceView.disposition === "UNVERIFIED" ? `UNVERIFIED · ACTUAL ${evidenceView.stance}` : evidenceView.stance}
                              </span>
                              {evidenceView.disposition === "UNVERIFIED" && (
                                <span className="proposed-stance">PROPOSED: {formatProposedStance(evidenceView.proposedStance)}</span>
                              )}
                              {evidenceView.semanticRelation && <span className="semantic-relation">RELATION: {evidenceView.semanticRelation}</span>}
                            </div>

                            <blockquote>“{item.quote}”</blockquote>
                            <p>{item.rationale}</p>

                            <div
                              style={{
                                display: "flex",
                                justifyContent: "space-between",
                                alignItems: "center",
                                flexWrap: "wrap",
                                gap: 8,
                                marginTop: 10,
                              }}
                            >
                              <div className="evidence-flags" style={{ marginTop: 0 }}>
                                {!item.stale && <span className="flag-fresh">FRESH SOURCE</span>}
                                {item.stale && <span className="flag-stale">⏰ STALE SOURCE</span>}
                                {item.disputed && (
                                  <span className="flag-disputed">⚑ DISPUTED · CHALLENGED FOR HUMAN REVIEW</span>
                                )}
                                {evidenceView.disposition === "UNVERIFIED" && (
                                  <span className="flag-unverified">
                                    ⚠ UNVERIFIED · NOT COUNTED AS CLAIM EVIDENCE
                                  </span>
                                )}
                              </div>

                              <div style={{ display: "flex", gap: 6 }}>
                                <button
                                  type="button"
                                  className="quick-fill-btn"
                                  style={{ padding: "4px 8px", fontSize: 9 }}
                                  onClick={() => {
                                    setSourceId(item.source_record_id);
                                    setQuote(item.quote);
                                  }}
                                >
                                  Use in Challenge ↓
                                </button>
                                {fullRecord && (
                                  <button
                                    type="button"
                                    className="quick-fill-btn"
                                    style={{ padding: "4px 8px", fontSize: 9 }}
                                    onClick={() => setExpandedEvidenceKey((curr) => (curr === evKey ? null : evKey))}
                                  >
                                    {isExpanded ? "▲ Hide Source" : "▼ Full Record"}
                                  </button>
                                )}
                              </div>
                            </div>

                            {isExpanded && fullRecord && (
                              <div
                                style={{
                                  marginTop: 10,
                                  padding: "10px 12px",
                                  background: "#f3f1ea",
                                  border: "1px solid #d8dacf",
                                  borderRadius: 4,
                                  fontSize: 11,
                                  color: "#151e28",
                                }}
                              >
                                <div style={{ fontFamily: "var(--mono)", fontSize: 9.5, color: "#57645b" }}>
                                  RECORD {fullRecord.id} · DEPT: {fullRecord.department} · TAGS:{" "}
                                  {(fullRecord.tags ?? []).join(", ") || "none"}
                                </div>
                                <p style={{ margin: "6px 0 0", lineHeight: 1.55 }}>{fullRecord.text}</p>
                              </div>
                            )}
                          </div>
                        );
                      })}
                    </div>

                    {/* ── Challenge Submission Box with Scoped Error Feedback ── */}
                    <details className="challenge-box" open>
                      <summary>
                        Challenge this conclusion{" "}
                        <span>Keep the evidence visible and mark a cited source quote for human review</span>
                      </summary>

                      {challengeError && (
                        <div className="error" role="alert" style={{ marginTop: 10 }}>
                          <strong>Challenge Submission Failed:</strong> {challengeError}
                        </div>
                      )}

                      <form onSubmit={challengeClaim}>
                        <label>
                          SOURCE RECORD CITED BY THIS CLAIM
                          <select required value={sourceId} onChange={(e) => chooseSource(e.target.value)}>
                            <option value="">Choose a source cited by this claim…</option>
                            {selected.dependencies.map((id) => {
                              const r = records.find((record) => record.id === id);
                              return (
                                r && (
                                  <option key={id} value={id}>
                                    {id} · {r.department}
                                  </option>
                                )
                              );
                            })}
                          </select>
                        </label>

                        <label>
                          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                            <span>EXACT QUOTE FROM RECORD</span>
                            {chosenRecord && quote && (
                              <span
                                style={{
                                  fontFamily: "var(--mono)",
                                  fontSize: "9.5px",
                                  color: chosenRecord.text.includes(quote.trim()) ? "#1b4d3e" : "#a3372c",
                                  fontWeight: 700,
                                }}
                              >
                                {chosenRecord.text.includes(quote.trim())
                                  ? "✓ EXACT SOURCE SUBSTRING VERIFIED"
                                  : "⚠ QUOTE MUST MATCH SOURCE EXACTLY"}
                              </span>
                            )}
                          </div>
                          <textarea
                            required
                            minLength={3}
                            maxLength={1000}
                            value={quote}
                            onChange={(e) => setQuote(e.target.value)}
                            placeholder="Select a source above or click 'Use in Challenge' on an evidence card to load its text"
                          />
                        </label>

                        <label>
                          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                            <span>WHY SHOULD THIS BE REVIEWED?</span>
                            <span
                              style={{
                                fontFamily: "var(--mono)",
                                fontSize: "9.5px",
                                color: reason.trim().length >= 8 ? "#1b4d3e" : "#8c5e15",
                                fontWeight: 700,
                              }}
                            >
                              {reason.trim().length} / 8 min characters (max 1000)
                            </span>
                          </div>
                          <textarea
                            required
                            minLength={8}
                            maxLength={1000}
                            value={reason}
                            onChange={(e) => setReason(e.target.value)}
                            placeholder="Describe the concern with this source or interpretation (minimum 8 characters)…"
                          />
                        </label>

                        {chosenRecord && (
                          <div style={{ padding: "8px 12px", background: "var(--ivory)", borderRadius: 6, border: "1px solid var(--line)" }}>
                            <span style={{ font: "700 9px var(--mono)", color: "var(--ink-tertiary)", display: "block", marginBottom: 2 }}>
                              FULL SOURCE RECORD ({chosenRecord.id} · {chosenRecord.department})
                            </span>
                            <small style={{ color: "var(--ink-secondary)", fontSize: "11px", lineHeight: 1.45 }}>“{chosenRecord.text}”</small>
                          </div>
                        )}

                        <div style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "center", marginTop: 4 }}>
                          <button
                            type="submit"
                            className="secondary"
                            disabled={
                              submittingChallenge || !sourceId || reason.trim().length < 8 || quote.trim().length < 3
                            }
                          >
                            {submittingChallenge ? "Recomputing…" : "Submit Challenge & Recompute"}
                            <span>→</span>
                          </button>
                          <button
                            type="button"
                            className="quick-fill-btn"
                            onClick={() => {
                              const firstDep = selected.dependencies[0];
                              if (firstDep) {
                                chooseSource(firstDep);
                                setReason(
                                  "Supervisor confirmed manual paper fallback checklist was active at Desk B during the shift transition."
                                );
                              }
                            }}
                          >
                            ⚡ Fill Sample Challenge Reason
                          </button>
                        </div>
                        <small style={{ color: "var(--ink-tertiary)", fontSize: "10.5px" }}>
                          Only claims depending on this record are reevaluated. The challenge is stored in history; it
                          does not erase source material.
                        </small>
                      </form>
                    </details>
                  </article>
                )}
              </div>
            </section>

            {/* ── Section 03: Interactive Read-Only Revision History ── */}
            <section id="history" className="history-section">
              <div className="workspace-heading">
                <div>
                  <span className="section-kicker">03 — AUDIT TRAIL (CLICK A REVISION TO INSPECT SNAPSHOT)</span>
                  <h2>Investigation history</h2>
                </div>
              <span className="record-count">{historyLoading ? "LOADING HISTORY · " : ""}{history.length} VERSIONS · READ-ONLY SNAPSHOT VIEWER</span>
              </div>

              {historyError && (
                <div className="error" role="alert" style={{ marginBottom: 14 }}>
                  <strong>History Retrieval Failed:</strong> {historyError}
                </div>
              )}

              {inspectedHistoryEntry && (
                <div
                  role="region"
                  aria-label={`Read-only snapshot inspector for revision ${inspectedHistoryEntry.version}`}
                  style={{
                    marginBottom: 18,
                    padding: "16px 18px",
                    background: "#ffffff",
                    border: "1px solid #c5d9cc",
                    borderLeft: "4px solid #215742",
                    borderRadius: 6,
                  }}
                >
                  <div
                    style={{
                      display: "flex",
                      justifyContent: "space-between",
                      alignItems: "center",
                      flexWrap: "wrap",
                      gap: 8,
                      marginBottom: 10,
                    }}
                  >
                    <div>
                      <span className="section-kicker" style={{ marginBottom: 2 }}>
                        STORED REVISION SNAPSHOT · REVISION {String(inspectedHistoryEntry.version).padStart(2, "0")}
                      </span>
                      <b style={{ fontSize: 13 }}>
                        {inspectedHistoryEntry.event === "CREATED"
                          ? "Investigation started"
                          : "Claim challenged · evidence rechecked"}{" "}
                        · {new Date(inspectedHistoryEntry.created_at).toLocaleString()}
                      </b>
                    </div>
                    <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                      <TracePill text="READ-ONLY · DOES NOT MUTATE STATE" tone="muted" />
                      <button
                        type="button"
                        className="quick-fill-btn"
                        style={{ padding: "5px 9px" }}
                        onClick={() => setInspectedHistoryVersion(null)}
                      >
                        ✕ Close
                      </button>
                    </div>
                  </div>

                  {inspectedHistoryEntry.reason && (
                    <p style={{ fontSize: 12, fontStyle: "italic", margin: "4px 0 10px", color: "#37443c" }}>
                      Challenge reason: “{inspectedHistoryEntry.reason}”
                    </p>
                  )}

                  {inspectedHistoryEntry.before && inspectedHistoryEntry.after ? (
                    <div style={{ display: "grid", gap: 10 }}>
                      {Object.keys(inspectedHistoryEntry.after).map((claimKey) => {
                        const beforeClaim = inspectedHistoryEntry.before?.[claimKey];
                        const afterClaim = inspectedHistoryEntry.after?.[claimKey];
                        if (!afterClaim) return null;
                        return (
                          <div key={claimKey} className="challenge-snapshot-grid">
                            <div className="snapshot-box">
                              <span className="kpi-label">
                                BEFORE ({HYPOTHESES[afterClaim.hypothesis_id] ?? claimKey})
                              </span>
                              {beforeClaim ? (
                                <>
                                  <strong>
                                    {beforeClaim.status} · Evidence-margin magnitude: {formatEvidenceMarginMagnitude(getEvidenceMarginMagnitude(beforeClaim))} (v
                                    {beforeClaim.version})
                                  </strong>
                                  <small>{beforeClaim.uncertainty}</small>
                                </>
                              ) : (
                                <small>No prior snapshot stored.</small>
                              )}
                            </div>
                            <div className="snapshot-box after">
                              <span className="kpi-label">
                                AFTER ({HYPOTHESES[afterClaim.hypothesis_id] ?? claimKey})
                              </span>
                              <strong>
                                {afterClaim.status} · Evidence-margin magnitude: {formatEvidenceMarginMagnitude(getEvidenceMarginMagnitude(afterClaim))} (v
                                {afterClaim.version})
                              </strong>
                              <small>{afterClaim.uncertainty}</small>
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  ) : (
                    <p style={{ fontSize: 11, color: "#57645b", margin: 0 }}>
                      Initial baseline revision. Recomputed claims:{" "}
                      {inspectedHistoryEntry.recomputed_claim_ids.map((id) => HYPOTHESES[id] ?? id).join(", ") ||
                        "All initial claims"}
                      .
                    </p>
                  )}
                </div>
              )}

              <ol className="timeline">
                {history
                  .slice()
                  .reverse()
                  .map((entry) => {
                    const isSelected = inspectedHistoryVersion === entry.version;
                    return (
                      <li key={entry.version}>
                        <span className={`timeline-node ${entry.event.toLowerCase()}`} />
                        <div
                          className="timeline-entry"
                          role="button"
                          tabIndex={0}
                          onClick={() =>
                            setInspectedHistoryVersion((curr) => (curr === entry.version ? null : entry.version))
                          }
                          onKeyDown={(e) => {
                            if (e.key === "Enter" || e.key === " ") {
                              e.preventDefault();
                              setInspectedHistoryVersion((curr) => (curr === entry.version ? null : entry.version));
                            }
                          }}
                          style={{
                            cursor: "pointer",
                            padding: "12px 14px",
                            background: isSelected ? "#eef5f1" : "#ffffff",
                            border: `1px solid ${isSelected ? "#215742" : "#e2e0d8"}`,
                            borderRadius: 6,
                          }}
                        >
                          <div>
                            <b>
                              {entry.event === "CREATED"
                                ? "Investigation started"
                                : "Claim challenged · evidence rechecked"}
                            </b>
                            <time>{new Date(entry.created_at).toLocaleString()}</time>
                          </div>
                          {entry.reason && <p>“{entry.reason}”</p>}
                          {entry.recomputed_claim_ids.length > 0 && (
                            <span>
                              Recomputed:{" "}
                              {entry.recomputed_claim_ids.map((id) => HYPOTHESES[id] ?? id).join(", ")}
                            </span>
                          )}
                          <div
                            style={{
                              display: "flex",
                              justifyContent: "space-between",
                              alignItems: "center",
                              marginTop: 6,
                            }}
                          >
                            <small>Revision {String(entry.version).padStart(2, "0")}</small>
                            <span
                              style={{
                                fontFamily: "var(--mono)",
                                fontSize: 9,
                                color: "#215742",
                                fontWeight: 600,
                              }}
                            >
                              {isSelected ? "▼ HIDE SNAPSHOT" : "▶ INSPECT BEFORE/AFTER SNAPSHOT"}
                            </span>
                          </div>
                        </div>
                      </li>
                    );
                  })}
              </ol>
            </section>
          </>
        )}

        {/* ── Section 04: Searchable Evidence Library ── */}
        <section id="library" className="history-section">
          <div className="workspace-heading">
            <div>
              <span className="section-kicker">04 — EVIDENCE LIBRARY (GET /api/records)</span>
              <h2>Source records corpus</h2>
            </div>
            <span className="record-count">
              SHOWING {filteredLibraryRecords.length} OF {records.length} RECORDS
            </span>
          </div>

          <div className="library-filter-bar">
            <label className="select-wrap">
              <span>SEARCH BY ID, TEXT, OR TAG</span>
              <input
                type="search"
                value={libraryQuery}
                onChange={(e) => setLibraryQuery(e.target.value)}
                placeholder="Filter records by keyword or ID…"
                className="search-input"
              />
            </label>
            <label className="select-wrap">
              <span>DEPARTMENT</span>
              <select value={libraryDeptFilter} onChange={(e) => setLibraryDeptFilter(e.target.value)}>
                <option value="ALL">All Departments</option>
                {availableDepartments.map((d) => (
                  <option key={d} value={d}>
                    {d}
                  </option>
                ))}
              </select>
            </label>
            <label className="select-wrap">
              <span>SOURCE GROUP</span>
              <select value={libraryGroupFilter} onChange={(e) => setLibraryGroupFilter(e.target.value)}>
                <option value="ALL">All Source Groups</option>
                {availableSourceGroups.map((g) => (
                  <option key={g} value={g}>
                    {g}
                  </option>
                ))}
              </select>
            </label>
          </div>

          {!recordsLoading && filteredLibraryRecords.length === 0 && (
            <p className="empty">No source records match the current filter.</p>
          )}

          <div className="evidence-list">
            {filteredLibraryRecords.map((rec) => (
              <div key={rec.id} className="evidence-card" style={{ background: "#ffffff" }}>
                <div className="evidence-meta">
                  <span className="source-id">{rec.id}</span>
                  <span className="dept-tag">{rec.department}</span>
                  {rec.source_group && <span className="group-tag">GROUP: {rec.source_group}</span>}
                  <time>{new Date(rec.timestamp).toLocaleString()}</time>
                </div>
                <p style={{ fontSize: 13, color: "#151e28", margin: "8px 0 6px", lineHeight: 1.55 }}>{rec.text}</p>
                <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                  {(rec.tags ?? []).map((t) => (
                    <TracePill key={t} text={`#${t}`} tone="muted" />
                  ))}
                </div>
              </div>
            ))}
          </div>
        </section>

        {/* ── Dark Slate Architecture Strip (Inspired by story-client-swart.vercel.app) ── */}
        <section className="arch-showcase" aria-label="Story Connect architecture">
          <div>
            <span className="arch-eyebrow">SECURITY &amp; VERIFICATION ARCHITECTURE</span>
            <h2>
              Built with evidence control
              <br />
              <span>at its core.</span>
            </h2>
            <p>
              Story Connect separates candidate AI proposals from deterministic verification logic. Exact-substring
              provenance, review-state gates, and append-only revision history ensure human reviewers stay in control.
            </p>
          </div>
          <div className="arch-cards">
            <div className="arch-card">
              <span className="arch-dot">01</span>
              <strong>Web Application</strong>
              <small>React 19 · TypeScript · Vite (:5174)</small>
            </div>
            <div className="arch-card">
              <span className="arch-dot">02</span>
              <strong>Verification Engine API</strong>
              <small>FastAPI · Deterministic Rules (:8081)</small>
            </div>
            <div className="arch-card">
              <span className="arch-dot">03</span>
              <strong>Audit &amp; Evidence Store</strong>
              <small>SQLite · Append-Only Revision Log</small>
            </div>
          </div>
        </section>
      </main>

      <footer>
        <span>
          STORY CONNECT <i>·</i> LUXURY HOSPITALITY EMPLOYEE EXPERIENCE &amp; EVIDENCE REVIEW
        </span>
        <span>
          PROTOTYPE 0.1 <i>·</i> SYNTHETIC DATA ONLY
        </span>
      </footer>
    </div>
  );
}

export default App;
