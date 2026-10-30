import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import PolicyDemoPage from "./PolicyDemoPage";

type Status = "SUPPORTED" | "PARTIAL" | "CONTRADICTED" | "INSUFFICIENT";
type Stance = "SUPPORTS" | "CONTRADICTS" | "NEUTRAL";
type Evidence = { source_record_id: string; timestamp: string; quote: string; stance: Stance; review_state?: "ACCEPTED" | "UNVERIFIED"; proposed_stance?: Stance | null; rationale: string; stale: boolean; disputed: boolean; department: string };
type Claim = { id: string; hypothesis_id: string; status: Status; confidence: number; uncertainty: string; summary: string; evidence: Evidence[]; conflicts: string[]; missing_evidence: string[]; dependencies: string[]; version: number };
type Investigation = { id: string; question: string; created_at: string; version: number; claims: Claim[] };
type History = { version: number; created_at: string; event: string; claim_id?: string; reason?: string; before?: Record<string, Claim>; after?: Record<string, Claim>; evidence_changes: string[]; recomputed_claim_ids: string[] };
type RecordItem = { id: string; timestamp: string; department: string; text: string; tags: string[] };

const HYPOTHESES: Record<string, string> = {
  CHECKLIST_UNAVAILABLE: "Checklist unavailable",
  TRAINING_GAP: "Training gap",
  STAFFING_CONSTRAINTS: "Staffing constraints",
  PMS_SYSTEM_ISSUE: "PMS system issue",
  TIME_PRESSURE: "Time pressure"
};
const CASES = [
  { label: "Recurring handover omissions", question: "Why do handover notes keep missing open guest requests?" },
  { label: "Checklist access", question: "Did checklist availability contribute to missing handover information?" },
  { label: "Desk coverage", question: "Did staffing constraints affect how guest requests were handed over?" },
  { label: "Property system", question: "Did property system interruptions affect handover note completion?" }
];

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api${path}`, { ...init, headers: { "Content-Type": "application/json", ...init?.headers } });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || `Request failed (${response.status})`);
  }
  return response.json() as Promise<T>;
}

function App() {
  const [showDemo, setShowDemo] = useState(window.location.hash === "#/demo");
  useEffect(() => {
    const handler = () => setShowDemo(window.location.hash === "#/demo");
    window.addEventListener("hashchange", handler);
    return () => window.removeEventListener("hashchange", handler);
  }, []);

  if (showDemo) return <PolicyDemoPage />;

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

  const refresh = useCallback(async (id: string) => {
    const [next, events] = await Promise.all([
      api<Investigation>(`/investigations/${id}`),
      api<History[]>(`/investigations/${id}/history`)
    ]);
    setInvestigation(next);
    setHistory(events);
    setSelectedId((current) => current || next.claims[0]?.id || "");
  }, []);

  useEffect(() => {
    api<RecordItem[]>("/records").then(setRecords).catch((e: Error) => setError(e.message));
  }, []);

  const selected = useMemo(() => investigation?.claims.find((claim) => claim.id === selectedId) ?? null, [investigation, selectedId]);
  const chosenRecord = records.find((record) => record.id === sourceId);

  async function startInvestigation() {
    setBusy(true); setError(""); setChange(null);
    try {
      const result = await api<Investigation>("/investigations", { method: "POST", body: JSON.stringify({ question: CASES[selectedCase].question }) });
      setInvestigation(result); setSelectedId(result.claims[0]?.id ?? "");
      setHistory(await api<History[]>(`/investigations/${result.id}/history`));
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }

  async function challengeClaim(event: FormEvent) {
    event.preventDefault();
    if (!investigation || !selected) return;
    setBusy(true); setError(""); setChange(null);
    const before = selected;
    try {
      await api(`/investigations/${investigation.id}/claims/${selected.id}/challenge`, {
        method: "POST", body: JSON.stringify({ reason, source_record_id: sourceId, quote })
      });
      await refresh(investigation.id);
      const after = (await api<Investigation>(`/investigations/${investigation.id}`)).claims.find((claim) => claim.id === selected.id);
      if (after) setChange({ before, after });
      setReason("");
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }

  function chooseSource(id: string) {
    setSourceId(id);
    const record = records.find((item) => item.id === id);
    setQuote(record?.text ?? "");
  }

  return <div className="shell">
    <header className="topbar">
      <a className="brand" href="#top" aria-label="Story Connect home"><span className="brand-mark">S</span><span>STORY <i>CONNECT</i></span></a>
      <div className="top-context"><span className="pulse" /> LOCAL PROTOTYPE <span className="divider">/</span> OPERATIONS INTELLIGENCE</div>
      <div style={{ display: "flex", alignItems: "center", gap: 18 }}>
        <a href="#/demo" style={{ fontFamily: "ui-monospace,monospace", fontSize: 10, letterSpacing: "0.08em", color: "#285f4d", textDecoration: "none" }}>Policy Demo ↗</a>
        <div className="profile"><span className="profile-icon">OM</span><span>Operations<br /><b>Manager</b></span></div>
      </div>
    </header>

    <main id="top">
      <div className="eyebrow"><span>FIELD NOTE 01</span><span className="line" /><span>SHIFT HANDOVER REVIEW</span></div>
      <section className="intro">
        <div><h1>Find what gets<br /><em>left behind.</em></h1><p>Review handover signals with their source context. Investigate possible contributing factors, challenge a claim, and keep a clear record of what changed.</p></div>
        <div className="intro-stamp"><span>HUMAN<br />REVIEW</span><span className="stamp-star">✳</span></div>
      </section>

      <aside className="synthetic-banner"><span className="banner-icon">✳</span><div><strong>Synthetic case · human review required</strong><span>All records are fictional. Evidence can inform inquiry; it cannot prove causation or support employee ranking, blame, or employment decisions.</span></div><span className="banner-tag">LOCAL ONLY</span></aside>
      {error && <div className="error" role="alert">{error}</div>}

      <section className="workspace">
        <div className="workspace-heading"><div><span className="section-kicker">01 — INVESTIGATION</span><h2>Choose a question</h2></div><span className="record-count">{records.length} AVAILABLE RECORDS</span></div>
        <div className="investigation-row">
          <label className="select-wrap"><span>STARTING POINT</span><select value={selectedCase} onChange={(e) => setSelectedCase(Number(e.target.value))}>{CASES.map((item, i) => <option value={i} key={item.label}>{item.label}</option>)}</select></label>
          <div className="question-preview"><span>INVESTIGATION QUESTION</span><p>{CASES[selectedCase].question}</p></div>
          <button className="primary" onClick={startInvestigation} disabled={busy}>{busy ? "Working…" : investigation ? "Run again" : "Run investigation"}<span>↗</span></button>
        </div>
      </section>

      {investigation && <>
        <section className="findings">
          <div className="workspace-heading"><div><span className="section-kicker">02 — EVIDENCE REVIEW</span><h2>Five possible contributors</h2></div><span className="version-pill">REVISION {String(investigation.version).padStart(2, "0")}</span></div>
          <div className="finding-grid">
            <div className="claim-list" role="tablist" aria-label="Hypothesis claims">
              {investigation.claims.map((claim, index) => <button className={`claim-tab ${selectedId === claim.id ? "active" : ""}`} role="tab" aria-selected={selectedId === claim.id} key={claim.id} onClick={() => { setSelectedId(claim.id); setChange(null); }}>
                <span className="claim-number">0{index + 1}</span><span className="claim-title">{HYPOTHESES[claim.hypothesis_id]}</span><span className={`status-dot ${claim.status.toLowerCase()}`} /><span className={`status-text ${claim.status.toLowerCase()}`}>{claim.status}</span><span className="chevron">›</span>
              </button>)}
            </div>
            {selected && <article className="claim-detail" role="tabpanel">
              <div className="detail-header"><div><span className="section-kicker">HYPOTHESIS / {selected.hypothesis_id}</span><h3>{HYPOTHESES[selected.hypothesis_id]}</h3></div><span className={`status-badge ${selected.status.toLowerCase()}`}>{selected.status}</span></div>
              <p className="claim-summary">{selected.summary} <span>{Math.round(selected.confidence * 100)}% confidence · review estimate</span></p>
              <div className="uncertainty"><span>!</span><div><b>What remains uncertain</b><p>{selected.uncertainty}</p></div></div>
              {selected.conflicts.map((item) => <div className="conflict" key={item}><b>Conflicting evidence</b><p>{item}</p></div>)}
              {selected.missing_evidence.map((item) => <div className="missing" key={item}><span>＋</span><p><b>Evidence gap</b><br />{item}</p></div>)}
              <div className="evidence-heading"><div><span className="section-kicker">SOURCE RECORDS</span><h4>Evidence considered <span>{selected.evidence.length}</span></h4></div><span>QUOTE MATCH ≠ PROOF</span></div>
              {selected.evidence.length === 0 && <p className="empty">No admissible evidence was found for this hypothesis.</p>}
              <div className="evidence-list">{selected.evidence.map((item, i) => <div className={`evidence-card ${item.stale ? "is-stale" : ""} ${item.disputed ? "is-disputed" : ""}`} key={`${item.source_record_id}-${i}`}>
                <div className="evidence-meta"><span className="source-id">{item.source_record_id}</span><span>{item.department}</span><time>{new Date(item.timestamp).toLocaleString()}</time><span className={`stance ${item.review_state === "UNVERIFIED" ? "unverified" : item.stance.toLowerCase()}`}>{item.review_state === "UNVERIFIED" ? `UNVERIFIED · PROPOSED ${item.proposed_stance ?? item.stance}` : item.stance}</span></div>
                <blockquote>“{item.quote}”</blockquote><p>{item.rationale}</p>
                {(item.stale || item.disputed || item.review_state === "UNVERIFIED") && <div className="evidence-flags">{item.stale && <span>STALE SOURCE</span>}{item.disputed && <span>CHALLENGED · RETAINED FOR REVIEW</span>}{item.review_state === "UNVERIFIED" && <span>NOT COUNTED AS CLAIM EVIDENCE · REVIEW REQUIRED</span>}</div>}
              </div>)}</div>
              <details className="challenge-box"><summary>Challenge this conclusion <span>Keep the evidence visible and mark a source for human review</span></summary>
                <form onSubmit={challengeClaim}>
                  <label>Source record<select required value={sourceId} onChange={(e) => chooseSource(e.target.value)}><option value="">Choose a source cited by this claim</option>{selected.dependencies.map((id) => { const r = records.find((record) => record.id === id); return r && <option key={id} value={id}>{id} · {r.department}</option>; })}</select></label>
                  <label>Exact quote from record<textarea required minLength={3} value={quote} onChange={(e) => setQuote(e.target.value)} placeholder="Select a source to load its exact text" /></label>
                  <label>Why should this be reviewed?<textarea required minLength={8} maxLength={1000} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Describe the concern with this source or interpretation" /></label>
                  {chosenRecord && <small>Source text: {chosenRecord.text}</small>}
                  <button className="secondary" disabled={busy || !sourceId || !reason.trim() || !quote.trim()}>{busy ? "Recomputing…" : "Submit challenge & recompute"}<span>↗</span></button>
                  <small>Only claims depending on this record are reevaluated. The challenge is stored in history; it does not erase source material.</small>
                </form>
              </details>
            </article>}
          </div>
        </section>

        {change && <section className="change-card"><div className="change-mark">↻</div><div><span className="section-kicker">RECOMPUTATION SUMMARY</span><h3>{HYPOTHESES[change.after.hypothesis_id]}</h3><p><b>{change.before.status}</b><span> → </span><b>{change.after.status}</b> · claim revision {change.after.version}</p><span>{change.after.uncertainty}</span></div></section>}

        <section className="history-section"><div className="workspace-heading"><div><span className="section-kicker">03 — AUDIT TRAIL</span><h2>Investigation history</h2></div><span className="record-count">{history.length} VERSIONS</span></div>
          <ol className="timeline">{history.slice().reverse().map((entry) => <li key={entry.version}><span className={`timeline-node ${entry.event.toLowerCase()}`} /><div className="timeline-entry"><div><b>{entry.event === "CREATED" ? "Investigation started" : "Claim challenged · evidence rechecked"}</b><time>{new Date(entry.created_at).toLocaleString()}</time></div>{entry.reason && <p>“{entry.reason}”</p>}{entry.recomputed_claim_ids.length > 0 && <span>Recomputed: {entry.recomputed_claim_ids.map((id) => HYPOTHESES[id] ?? id).join(", ")}</span>}<small>Revision {String(entry.version).padStart(2, "0")}</small></div></li>)}</ol>
        </section>
      </>}
    </main>
    <footer><span>STORY CONNECT <i>·</i> HANDOVER REVIEW</span><span>PROTOTYPE 0.1 <i>·</i> SYNTHETIC DATA ONLY</span></footer>
  </div>;
}

export default App;
