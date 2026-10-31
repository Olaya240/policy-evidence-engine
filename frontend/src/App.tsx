import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import PolicyDemoPage from "./PolicyDemoPage";

type Status = "SUPPORTED" | "PARTIAL" | "CONTRADICTED" | "INSUFFICIENT";
type Stance = "SUPPORTS" | "CONTRADICTS" | "NEUTRAL";

type Evidence = {
  source_record_id: string;
  timestamp: string;
  quote: string;
  stance: Stance;
  review_state?: "ACCEPTED" | "UNVERIFIED";
  proposed_stance?: Stance | null;
  semantic_relation?: string;
  source_group?: string;
  rationale: string;
  stale: boolean;
  disputed: boolean;
  department: string;
};

type Claim = {
  id: string;
  hypothesis_id: string;
  status: Status;
  confidence: number;
  uncertainty: string;
  summary: string;
  evidence: Evidence[];
  conflicts: string[];
  missing_evidence: string[];
  dependencies: string[];
  version: number;
};

type Investigation = {
  id: string;
  question: string;
  created_at: string;
  version: number;
  claims: Claim[];
};

type History = {
  version: number;
  created_at: string;
  event: string;
  claim_id?: string;
  reason?: string;
  before?: Record<string, Claim>;
  after?: Record<string, Claim>;
  evidence_changes: string[];
  recomputed_claim_ids: string[];
};

type RecordItem = {
  id: string;
  timestamp: string;
  department: string;
  text: string;
  tags: string[];
  restricted?: boolean;
  source_group?: string;
};

const HYPOTHESES: Record<string, string> = {
  CHECKLIST_UNAVAILABLE: "Checklist unavailable",
  TRAINING_GAP: "Training gap",
  STAFFING_CONSTRAINTS: "Staffing constraints",
  PMS_SYSTEM_ISSUE: "PMS system issue",
  TIME_PRESSURE: "Time pressure",
};

const CASES = [
  { label: "Recurring handover omissions", question: "Why do handover notes keep missing open guest requests?" },
  { label: "Checklist access", question: "Did checklist availability contribute to missing handover information?" },
  { label: "Desk coverage", question: "Did staffing constraints affect how guest requests were handed over?" },
  { label: "Property system", question: "Did property system interruptions affect handover note completion?" },
];

const FALLBACK_RECORDS: RecordItem[] = [
  {
    id: "REC-101",
    timestamp: "2026-10-29T14:20:00Z",
    department: "FRONT_OFFICE",
    text: "Shift handover checklist template was locked in read-only mode during the 14:00 desk transition.",
    tags: ["handover", "checklist"],
    source_group: "shift_logs",
  },
  {
    id: "REC-102",
    timestamp: "2026-10-29T16:05:00Z",
    department: "HR_TRAINING",
    text: "Three newly onboarded relief associates completed PMS orientation but have not yet completed the revised handover escalation module.",
    tags: ["training", "onboarding"],
    source_group: "training_records",
  },
  {
    id: "REC-104",
    timestamp: "2026-10-29T22:10:00Z",
    department: "HOUSEKEEPING",
    text: "Two late checkout guest requests were logged verbally because only one agent covered the evening desk.",
    tags: ["staffing", "guest_requests"],
    source_group: "shift_logs",
  },
  {
    id: "REC-108",
    timestamp: "2026-10-30T06:45:00Z",
    department: "IT_OPS",
    text: "PMS terminal sync experienced a 12-minute latency spike during morning audit.",
    tags: ["pms", "system"],
    source_group: "telemetry",
  },
  {
    id: "REC-112",
    timestamp: "2026-10-30T14:55:00Z",
    department: "FRONT_OFFICE",
    text: "Group tour bus arrival overlapped with the 15:00 shift changeover, compressing handover briefing to under four minutes.",
    tags: ["time_pressure", "arrivals"],
    source_group: "shift_logs",
  },
];

const FALLBACK_INVESTIGATION: Investigation = {
  id: "inv-syn-01",
  question: CASES[0].question,
  created_at: new Date().toISOString(),
  version: 1,
  claims: [
    {
      id: "clm-1",
      hypothesis_id: "CHECKLIST_UNAVAILABLE",
      status: "SUPPORTED",
      confidence: 0.78,
      uncertainty: "Template lock occurred on two shifts, but manual fallback forms were present at Desk B.",
      summary: "Read-only template locks coincided with omitted guest request entries during afternoon handover.",
      dependencies: ["REC-101"],
      conflicts: [],
      missing_evidence: ["Desk B paper log confirmation for Oct 29"],
      version: 1,
      evidence: [
        {
          source_record_id: "REC-101",
          timestamp: "2026-10-29T14:20:00Z",
          quote: "Shift handover checklist template was locked in read-only mode during the 14:00 desk transition.",
          stance: "SUPPORTS",
          review_state: "ACCEPTED",
          source_group: "shift_logs",
          rationale: "Direct source match linking checklist access state to the afternoon handover window.",
          stale: false,
          disputed: false,
          department: "FRONT_OFFICE",
        },
      ],
    },
    {
      id: "clm-2",
      hypothesis_id: "TRAINING_GAP",
      status: "PARTIAL",
      confidence: 0.58,
      uncertainty: "Relief staff lacked the escalation module, though a senior supervisor was on call.",
      summary: "Relief associates on the afternoon rotation had not completed the updated handover escalation module.",
      dependencies: ["REC-102"],
      conflicts: ["Senior supervisor signed off on the shift summary header."],
      missing_evidence: ["Individual shift pairing assignment sheet"],
      version: 1,
      evidence: [
        {
          source_record_id: "REC-102",
          timestamp: "2026-10-29T16:05:00Z",
          quote: "Three newly onboarded relief associates completed PMS orientation but have not yet completed the revised handover escalation module.",
          stance: "SUPPORTS",
          review_state: "ACCEPTED",
          source_group: "training_records",
          rationale: "Verifies incomplete escalation training among active relief staff.",
          stale: false,
          disputed: false,
          department: "HR_TRAINING",
        },
      ],
    },
    {
      id: "clm-3",
      hypothesis_id: "STAFFING_CONSTRAINTS",
      status: "PARTIAL",
      confidence: 0.64,
      uncertainty: "Single-agent coverage is documented, but causal link to omitted notes requires human review.",
      summary: "Evening desk operated with a single agent during peak checkout requests, prompting verbal handoffs.",
      dependencies: ["REC-104"],
      conflicts: ["Morning shift had full staffing yet still missed one VIP amenity note."],
      missing_evidence: ["Duty manager floor roster"],
      version: 1,
      evidence: [
        {
          source_record_id: "REC-104",
          timestamp: "2026-10-29T22:10:00Z",
          quote: "Two late checkout guest requests were logged verbally because only one agent covered the evening desk.",
          stance: "SUPPORTS",
          review_state: "ACCEPTED",
          source_group: "shift_logs",
          rationale: "Indicates verbal fallback during solo desk coverage.",
          stale: false,
          disputed: false,
          department: "HOUSEKEEPING",
        },
      ],
    },
    {
      id: "clm-4",
      hypothesis_id: "PMS_SYSTEM_ISSUE",
      status: "INSUFFICIENT",
      confidence: 0.34,
      uncertainty: "Latency spike occurred during morning audit, outside the primary afternoon handover window.",
      summary: "PMS sync delay recorded during morning audit; insufficient overlap with afternoon omissions.",
      dependencies: ["REC-108"],
      conflicts: [],
      missing_evidence: ["Afternoon PMS terminal telemetry"],
      version: 1,
      evidence: [
        {
          source_record_id: "REC-108",
          timestamp: "2026-10-30T06:45:00Z",
          quote: "PMS terminal sync experienced a 12-minute latency spike during morning audit.",
          stance: "NEUTRAL",
          review_state: "UNVERIFIED",
          proposed_stance: "SUPPORTS",
          source_group: "telemetry",
          rationale: "Phrase-cue regression guard downgraded stance to NEUTRAL; correlation is not causation.",
          stale: false,
          disputed: false,
          department: "IT_OPS",
        },
      ],
    },
    {
      id: "clm-5",
      hypothesis_id: "TIME_PRESSURE",
      status: "SUPPORTED",
      confidence: 0.72,
      uncertainty: "Tour arrival compressed briefing time, though digital notes could still be appended post-briefing.",
      summary: "Unscheduled group check-in overlapped directly with the 15:00 shift transition window.",
      dependencies: ["REC-112"],
      conflicts: [],
      missing_evidence: ["Lobby queue timestamp log"],
      version: 1,
      evidence: [
        {
          source_record_id: "REC-112",
          timestamp: "2026-10-30T14:55:00Z",
          quote: "Group tour bus arrival overlapped with the 15:00 shift changeover, compressing handover briefing to under four minutes.",
          stance: "SUPPORTS",
          review_state: "ACCEPTED",
          source_group: "shift_logs",
          rationale: "Documents acute time compression during the handover window.",
          stale: false,
          disputed: false,
          department: "FRONT_OFFICE",
        },
      ],
    },
  ],
};

function normalizeError(body: unknown, status: number): string {
  if (body && typeof body === "object" && "detail" in body) {
    const detail = (body as { detail: unknown }).detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
      return detail.map((d) => (typeof d === "object" && d && "msg" in d ? String(d.msg) : JSON.stringify(d))).join("; ");
    }
    if (detail && typeof detail === "object") {
      return "message" in detail ? String((detail as { message: unknown }).message) : JSON.stringify(detail);
    }
  }
  return `Request failed (${status})`;
}

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(normalizeError(body, response.status));
  }
  return response.json() as Promise<T>;
}

function App() {
  const [showDemo, setShowDemo] = useState(window.location.hash === "#/demo");
  const [records, setRecords] = useState<RecordItem[]>([]);
  const [investigation, setInvestigation] = useState<Investigation | null>(null);
  const [history, setHistory] = useState<History[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [selectedCase, setSelectedCase] = useState(0);
  const [sourceId, setSourceId] = useState("");
  const [quote, setQuote] = useState("");
  const [reason, setReason] = useState("");
  const [change, setChange] = useState<{ before: Claim; after: Claim } | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [offlineMode, setOfflineMode] = useState(false);

  useEffect(() => {
    const handler = () => setShowDemo(window.location.hash === "#/demo");
    window.addEventListener("hashchange", handler);
    return () => window.removeEventListener("hashchange", handler);
  }, []);

  const refresh = useCallback(async (id: string) => {
    const [next, events] = await Promise.all([
      api<Investigation>(`/investigations/${id}`),
      api<History[]>(`/investigations/${id}/history`),
    ]);
    setInvestigation(next);
    setHistory(events);
    setSelectedId((current) => current || next.claims[0]?.id || "");
  }, []);

  useEffect(() => {
    api<RecordItem[]>("/records")
      .then((data) => {
        setRecords(data);
        setOfflineMode(false);
      })
      .catch(() => {
        setRecords(FALLBACK_RECORDS);
        setOfflineMode(true);
      });
  }, []);

  const selected = useMemo(
    () => investigation?.claims.find((claim) => claim.id === selectedId) ?? null,
    [investigation, selectedId]
  );
  const chosenRecord = useMemo(() => records.find((record) => record.id === sourceId), [records, sourceId]);

  const statusCounts = useMemo(() => {
    if (!investigation) return { supported: 0, partial: 0, insufficient: 0, disputed: 0 };
    return {
      supported: investigation.claims.filter((c) => c.status === "SUPPORTED").length,
      partial: investigation.claims.filter((c) => c.status === "PARTIAL").length,
      insufficient: investigation.claims.filter((c) => c.status === "INSUFFICIENT" || c.status === "CONTRADICTED").length,
      disputed: investigation.claims.reduce((acc, c) => acc + c.evidence.filter((e) => e.disputed).length, 0),
    };
  }, [investigation]);

  async function startInvestigation() {
    setBusy(true);
    setError("");
    setChange(null);
    try {
      const result = await api<Investigation>("/investigations", {
        method: "POST",
        body: JSON.stringify({ question: CASES[selectedCase].question }),
      });
      setInvestigation(result);
      setSelectedId(result.claims[0]?.id ?? "");
      setHistory(await api<History[]>(`/investigations/${result.id}/history`));
      setOfflineMode(false);
    } catch {
      const mockInv: Investigation = {
        ...FALLBACK_INVESTIGATION,
        question: CASES[selectedCase].question,
        created_at: new Date().toISOString(),
      };
      setInvestigation(mockInv);
      setSelectedId(mockInv.claims[0].id);
      setHistory([
        {
          version: 1,
          created_at: new Date().toISOString(),
          event: "CREATED",
          evidence_changes: [],
          recomputed_claim_ids: mockInv.claims.map((c) => c.hypothesis_id),
        },
      ]);
      setOfflineMode(true);
    } finally {
      setBusy(false);
    }
  }

  async function challengeClaim(event: FormEvent) {
    event.preventDefault();
    if (!investigation || !selected) return;
    setBusy(true);
    setError("");
    setChange(null);
    const before = selected;
    try {
      await api(`/investigations/${investigation.id}/claims/${selected.id}/challenge`, {
        method: "POST",
        body: JSON.stringify({ reason: reason.trim(), source_record_id: sourceId, quote: quote.trim() }),
      });
      await refresh(investigation.id);
      const updatedInv = await api<Investigation>(`/investigations/${investigation.id}`);
      const after = updatedInv.claims.find((claim) => claim.id === selected.id);
      if (after) setChange({ before, after });
      setReason("");
    } catch (e) {
      if (offlineMode) {
        const nextVersion = investigation.version + 1;
        const afterClaim: Claim = {
          ...selected,
          status: "PARTIAL",
          confidence: Math.max(0.28, selected.confidence - 0.24),
          version: nextVersion,
          uncertainty: `Human review flagged source ${sourceId}: "${reason.trim()}". Downstream conclusion downgraded pending audit.`,
          evidence: selected.evidence.map((ev) =>
            ev.source_record_id === sourceId ? { ...ev, disputed: true } : ev
          ),
        };
        setInvestigation({
          ...investigation,
          version: nextVersion,
          claims: investigation.claims.map((c) => (c.id === selected.id ? afterClaim : c)),
        });
        setChange({ before, after: afterClaim });
        setHistory((prev) => [
          ...prev,
          {
            version: nextVersion,
            created_at: new Date().toISOString(),
            event: "CHALLENGED",
            claim_id: selected.id,
            reason: reason.trim(),
            evidence_changes: [sourceId],
            recomputed_claim_ids: [selected.hypothesis_id],
          },
        ]);
        setReason("");
      } else {
        setError((e as Error).message);
      }
    } finally {
      setBusy(false);
    }
  }

  function chooseSource(id: string) {
    setSourceId(id);
    const record = records.find((item) => item.id === id);
    setQuote(record?.text ?? "");
  }

  if (showDemo) return <PolicyDemoPage />;

  return (
    <div className="shell">
      <header className="topbar">
        <a className="brand" href="#top" aria-label="Story Connect home">
          <span className="brand-mark">S</span>
          <span>
            STORY <i>CONNECT</i>
          </span>
        </a>
        <div className="top-context">
          <span className="pulse" /> {offlineMode ? "OFFLINE SYNTHETIC ENGINE" : "LIVE SQLITE ENGINE"}{" "}
          <span className="divider">/</span> HANDOVER INVESTIGATION STUDIO (PORT 8081)
        </div>
        <div className="nav-actions">
          <div className="mode-switcher" role="navigation" aria-label="Workspace mode">
            <a href="#top" className="mode-pill active">
              01 · Handover Investigator
            </a>
            <a href="#/demo" className="mode-pill">
              02 · Policy & SAM 3.1 Studio ↗
            </a>
          </div>
          <div className="profile">
            <span className="profile-icon">OM</span>
            <span>
              Operations
              <br />
              <b>Manager</b>
            </span>
          </div>
        </div>
      </header>

      <main id="top">
        <div className="eyebrow">
          <span>FIELD NOTE 01</span>
          <span className="line" />
          <span>SHIFT HANDOVER EVIDENCE & ATOMIC RECOMPUTATION STUDIO</span>
        </div>

        <section className="intro">
          <div>
            <h1>
              Find what gets
              <br />
              <em>left behind.</em>
            </h1>
            <p>
              Investigate recurring shift handover omissions with deterministic exact-substring provenance, phrase-cue
              regression guards, and atomic dependency recomputation when source quotes are challenged.
            </p>
          </div>
          <div className="intro-stamp">
            <span>
              HUMAN
              <br />
              REVIEW
            </span>
            <span className="stamp-star">✳</span>
          </div>
        </section>

        {/* ── Executive Telemetry Strip ── */}
        <section className="kpi-ribbon" aria-label="Engine governance telemetry">
          <div className="kpi-tile">
            <span className="kpi-label">EVIDENCE CORPUS</span>
            <strong>{records.length} Source Logs</strong>
            <small>Canary-filtered · Local SQLite</small>
          </div>
          <div className="kpi-tile">
            <span className="kpi-label">PROVENANCE ENGINE</span>
            <strong>Exact Substring</strong>
            <small>Quote match ≠ semantic proof</small>
          </div>
          <div className="kpi-tile">
            <span className="kpi-label">PHRASE-CUE GUARD</span>
            <strong>Active (5 Hypotheses)</strong>
            <small>Downgrades unverified to NEUTRAL</small>
          </div>
          <div className="kpi-tile">
            <span className="kpi-label">GOVERNANCE GATE</span>
            <strong>Human Review Mandatory</strong>
            <small>Append-only revision history</small>
          </div>
        </section>

        <aside className="synthetic-banner">
          <span className="banner-icon">✳</span>
          <div>
            <strong>Synthetic case · decision support only · human review required</strong>
            <span>
              All records are fictional. Quote presence establishes exact-substring provenance only — not semantic
              proof or causation. Never use for employee ranking, blame, or disciplinary decisions.
            </span>
          </div>
          <span className="banner-tag">{offlineMode ? "SYNTHETIC FALLBACK" : "LOCAL SQLITE"}</span>
        </aside>

        {error && (
          <div className="error" role="alert">
            {error}
          </div>
        )}

        <section className="workspace">
          <div className="workspace-heading">
            <div>
              <span className="section-kicker">01 — INVESTIGATION LAUNCHPAD</span>
              <h2>Select an operational inquiry</h2>
            </div>
            <span className="record-count">{records.length} ADMISSIBLE SOURCE RECORDS</span>
          </div>
          <div className="investigation-row">
            <label className="select-wrap">
              <span>HYPOTHESIS SCENARIO</span>
              <select value={selectedCase} onChange={(e) => setSelectedCase(Number(e.target.value))}>
                {CASES.map((item, i) => (
                  <option value={i} key={item.label}>
                    {item.label}
                  </option>
                ))}
              </select>
            </label>
            <div className="question-preview">
              <span>INVESTIGATION QUESTION</span>
              <p>{CASES[selectedCase].question}</p>
            </div>
            <button className="primary" onClick={startInvestigation} disabled={busy}>
              {busy ? "Computing…" : investigation ? "Re-run Investigation" : "Run Investigation"}
              <span>↗</span>
            </button>
          </div>
        </section>

        {investigation && (
          <>
            <section className="findings">
              <div className="workspace-heading">
                <div>
                  <span className="section-kicker">02 — HYPOTHESIS & EVIDENCE MATRIX</span>
                  <h2>Five candidate contributors</h2>
                </div>
                <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                  <span className="version-pill">SUPPORTED: {statusCounts.supported}</span>
                  <span className="version-pill">PARTIAL: {statusCounts.partial}</span>
                  <span className="version-pill">DISPUTED QUOTES: {statusCounts.disputed}</span>
                  <span className="version-pill" style={{ background: "#e3ede7", color: "#285f4d", fontWeight: 600 }}>
                    REVISION {String(investigation.version).padStart(2, "0")}
                  </span>
                </div>
              </div>

              <div className="finding-grid">
                <div className="claim-list" role="tablist" aria-label="Hypothesis claims">
                  {investigation.claims.map((claim, index) => {
                    const pct = Math.round(claim.confidence * 100);
                    return (
                      <button
                        className={`claim-tab ${selectedId === claim.id ? "active" : ""}`}
                        role="tab"
                        aria-selected={selectedId === claim.id}
                        key={claim.id}
                        onClick={() => {
                          setSelectedId(claim.id);
                          setSourceId(claim.dependencies[0] ?? "");
                          const defaultRec = records.find((r) => r.id === claim.dependencies[0]);
                          setQuote(defaultRec?.text ?? "");
                          setChange(null);
                        }}
                      >
                        <span className="claim-number">0{index + 1}</span>
                        <div className="claim-tab-body">
                          <span className="claim-title">{HYPOTHESES[claim.hypothesis_id] ?? claim.hypothesis_id}</span>
                          <span className={`status-text ${claim.status.toLowerCase()}`}>
                            {claim.status} · {pct}% review est.
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
                        {Math.round(selected.confidence * 100)}% review estimate (non-calibrated heuristic · human
                        verification required)
                      </span>
                    </p>

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

                    <div className="evidence-heading">
                      <div>
                        <span className="section-kicker">EXACT-SUBSTRING PROVENANCE</span>
                        <h4>
                          Evidence considered <span>{selected.evidence.length}</span>
                        </h4>
                      </div>
                      <span>QUOTE MATCH ≠ SEMANTIC PROOF</span>
                    </div>

                    {selected.evidence.length === 0 && (
                      <p className="empty">No admissible evidence was found for this hypothesis.</p>
                    )}

                    <div className="evidence-list">
                      {selected.evidence.map((item, i) => (
                        <div
                          className={`evidence-card ${item.stale ? "is-stale" : ""} ${
                            item.disputed ? "is-disputed" : ""
                          }`}
                          key={`${item.source_record_id}-${i}`}
                        >
                          <div className="evidence-meta">
                            <span className="source-id">{item.source_record_id}</span>
                            <span>{item.department}</span>
                            {item.source_group && <span>GROUP: {item.source_group}</span>}
                            <time>{new Date(item.timestamp).toLocaleString()}</time>
                            <span
                              className={`stance ${
                                item.review_state === "UNVERIFIED" ? "unverified" : item.stance.toLowerCase()
                              }`}
                            >
                              {item.review_state === "UNVERIFIED"
                                ? `UNVERIFIED · PROPOSED ${item.proposed_stance ?? item.stance}`
                                : item.stance}
                            </span>
                          </div>
                          <blockquote>“{item.quote}”</blockquote>
                          <p>{item.rationale}</p>
                          {(item.stale || item.disputed || item.review_state === "UNVERIFIED") && (
                            <div className="evidence-flags">
                              {item.stale && <span>STALE SOURCE</span>}
                              {item.disputed && <span>CHALLENGED · RETAINED FOR REVIEW</span>}
                              {item.review_state === "UNVERIFIED" && (
                                <span>PHRASE-CUE GUARD · NOT COUNTED AS CLAIM EVIDENCE</span>
                              )}
                            </div>
                          )}
                        </div>
                      ))}
                    </div>

                    <details className="challenge-box" open>
                      <summary>
                        Challenge a source quote & recompute{" "}
                        <span>Exact substring validation · atomic revision check (409 on stale state)</span>
                      </summary>
                      <form onSubmit={challengeClaim}>
                        <label>
                          SOURCE RECORD CITED BY THIS CLAIM
                          <select required value={sourceId} onChange={(e) => chooseSource(e.target.value)}>
                            <option value="">Choose a source record to challenge…</option>
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
                          EXACT QUOTE SUBSTRING FROM RECORD
                          <textarea
                            required
                            minLength={3}
                            maxLength={1000}
                            value={quote}
                            onChange={(e) => setQuote(e.target.value)}
                            placeholder="Select a source above to auto-load its exact verbatim text"
                          />
                        </label>
                        <label>
                          REVIEWER CHALLENGE REASON (8–1000 CHARS)
                          <textarea
                            required
                            minLength={8}
                            maxLength={1000}
                            value={reason}
                            onChange={(e) => setReason(e.target.value)}
                            placeholder="Explain why this source quote is disputed, incomplete, or contextually misapplied…"
                          />
                        </label>
                        {chosenRecord && <small>Full source text: “{chosenRecord.text}”</small>}
                        <div style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "center" }}>
                          <button
                            type="submit"
                            className="secondary"
                            disabled={busy || !sourceId || reason.trim().length < 8 || quote.trim().length < 3}
                          >
                            {busy ? "Recomputing…" : "Submit Challenge & Recompute"}
                            <span>↗</span>
                          </button>
                          <button
                            type="button"
                            className="quick-fill-btn"
                            onClick={() => {
                              const firstDep = selected.dependencies[0];
                              if (firstDep) {
                                chooseSource(firstDep);
                                setReason(
                                  "Supervisor confirmed manual paper fallback checklist was active at Desk B during the transition window."
                                );
                              }
                            }}
                          >
                            ⚡ Auto-Fill Demo Challenge
                          </button>
                        </div>
                        <small>
                          Only claims depending on this record are reevaluated. The challenge is appended to the audit
                          trail; original source records are never erased.
                        </small>
                      </form>
                    </details>
                  </article>
                )}
              </div>
            </section>

            {change && (
              <section className="change-card" role="status" aria-live="polite">
                <div className="change-mark">↻</div>
                <div>
                  <span className="section-kicker">ATOMIC RECOMPUTATION SUMMARY</span>
                  <h3>{HYPOTHESES[change.after.hypothesis_id] ?? change.after.hypothesis_id}</h3>
                  <p>
                    <b>{change.before.status}</b> ({Math.round(change.before.confidence * 100)}%)
                    <span> → </span>
                    <b>{change.after.status}</b> ({Math.round(change.after.confidence * 100)}%) · Revision v
                    {change.after.version}
                  </p>
                  <span>{change.after.uncertainty}</span>
                </div>
              </section>
            )}

            <section className="history-section">
              <div className="workspace-heading">
                <div>
                  <span className="section-kicker">03 — APPEND-ONLY AUDIT TRAIL</span>
                  <h2>Investigation revision history</h2>
                </div>
                <span className="record-count">{history.length} RECORDED VERSIONS</span>
              </div>
              <ol className="timeline">
                {history
                  .slice()
                  .reverse()
                  .map((entry) => (
                    <li key={entry.version}>
                      <span className={`timeline-node ${entry.event.toLowerCase()}`} />
                      <div className="timeline-entry">
                        <div>
                          <b>
                            {entry.event === "CREATED"
                              ? "Investigation initialized · 5 candidate hypotheses evaluated"
                              : "Source quote challenged · dependent claims atomically recomputed"}
                          </b>
                          <time>{new Date(entry.created_at).toLocaleString()}</time>
                        </div>
                        {entry.reason && <p>“{entry.reason}”</p>}
                        {entry.recomputed_claim_ids.length > 0 && (
                          <span>
                            Recomputed claims:{" "}
                            {entry.recomputed_claim_ids.map((id) => HYPOTHESES[id] ?? id).join(", ")}
                          </span>
                        )}
                        <small>Revision {String(entry.version).padStart(2, "0")}</small>
                      </div>
                    </li>
                  ))}
              </ol>
            </section>
          </>
        )}
      </main>

      <footer>
        <span>
          STORY CONNECT <i>·</i> HANDOVER EVIDENCE ENGINE
        </span>
        <span>
          PROTOTYPE 0.1 <i>·</i> HUMAN REVIEW REQUIRED
        </span>
      </footer>
    </div>
  );
}

export default App;