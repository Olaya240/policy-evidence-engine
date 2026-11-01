import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import PolicyDemoPage from "./PolicyDemoPage";

type Status = "SUPPORTED" | "PARTIAL" | "CONTRADICTED" | "INSUFFICIENT";
type Stance = "SUPPORTS" | "CONTRADICTS" | "NEUTRAL";

type ExplanationTraceRule = {
  rule_id: string;
  description?: string;
  applied?: boolean;
  weight?: number;
};

type ExplanationTrace = {
  status_rule_id?: string;
  confidence_rule_id?: string;
  evidence_dispositions?: Record<string, string> | Array<{ source_record_id?: string; record_id?: string; disposition: string; reason?: string }>;
  rules_triggered?: ExplanationTraceRule[];
  notes?: string[];
};

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
  explanation_trace?: ExplanationTrace;
};

type Investigation = {
  id: string;
  question: string;
  created_at: string;
  version: number;
  claims: Claim[];
  preset_id?: string;
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

type ChallengeResponsePayload = {
  version?: number;
  before?: Record<string, Claim> | Claim;
  after?: Record<string, Claim> | Claim;
  recomputed_claim_ids?: string[];
  reason?: string;
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

// Exact 4 canonical presets and questions expected by the backend (Point #1 & #2)
const PRESETS = [
  {
    preset_id: "handover_omissions",
    label: "Recurring handover omissions",
    question: "Why do handover notes keep missing open guest requests?",
  },
  {
    preset_id: "checklist_access",
    label: "Checklist access",
    question: "Did checklist availability contribute to missing handover information?",
  },
  {
    preset_id: "desk_coverage",
    label: "Desk coverage",
    question: "Did staffing constraints affect how guest requests were handed over?",
  },
  {
    preset_id: "property_system",
    label: "Property system",
    question: "Did property system interruptions affect handover note completion?",
  },
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
  question: PRESETS[0].question,
  created_at: new Date().toISOString(),
  version: 1,
  preset_id: PRESETS[0].preset_id,
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
      explanation_trace: {
        status_rule_id: "STATUS_SUPPORTED_BY_ACCEPTED_EVIDENCE",
        confidence_rule_id: "CONF_BASE_PLUS_CORROBORATION",
        evidence_dispositions: { "REC-101": "COUNTED_SUPPORTS (EXACT_SUBSTRING_VERIFIED)" },
        rules_triggered: [
          {
            rule_id: "RULE_EXACT_SUBSTRING_MATCH",
            description: "Quoted text verified as exact substring of source REC-101.",
            applied: true,
            weight: 0.8,
          },
          {
            rule_id: "RULE_NO_ACTIVE_DISPUTE",
            description: "No human challenge currently flags REC-101.",
            applied: true,
            weight: 0.2,
          },
        ],
      },
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
      explanation_trace: {
        status_rule_id: "STATUS_PARTIAL_WITH_CONFLICT",
        confidence_rule_id: "CONF_PENALIZED_BY_GAP",
        evidence_dispositions: { "REC-102": "COUNTED_SUPPORTS (CONFLICT_PRESENT)" },
        rules_triggered: [
          {
            rule_id: "RULE_SUPPORT_WITH_MISSING_CONTEXT",
            description: "Training gap verified in REC-102, but shift pairing log is absent.",
            applied: true,
            weight: 0.58,
          },
        ],
      },
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
      explanation_trace: {
        status_rule_id: "STATUS_PARTIAL_SINGLE_SOURCE",
        confidence_rule_id: "CONF_MODERATE_SINGLE_GROUP",
        evidence_dispositions: { "REC-104": "COUNTED_SUPPORTS (SINGLE_SOURCE_GROUP)" },
        rules_triggered: [
          {
            rule_id: "RULE_SINGLE_DEPARTMENT_SOURCE",
            description: "Supported by REC-104; capped at PARTIAL until cross-department roster is linked.",
            applied: true,
            weight: 0.64,
          },
        ],
      },
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
      explanation_trace: {
        status_rule_id: "STATUS_INSUFFICIENT_UNVERIFIED_GUARD",
        confidence_rule_id: "CONF_FLOOR_NO_ACCEPTED_SUPPORT",
        evidence_dispositions: { "REC-108": "EXCLUDED_UNVERIFIED (PHRASE_CUE_GUARD_DOWNGRADED)" },
        rules_triggered: [
          {
            rule_id: "RULE_PHRASE_CUE_GUARD_DOWNGRADE",
            description: "Proposed SUPPORTS downgraded to NEUTRAL/UNVERIFIED; not counted as claim evidence.",
            applied: true,
            weight: 0.34,
          },
        ],
      },
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
      explanation_trace: {
        status_rule_id: "STATUS_SUPPORTED_DIRECT_TIMELINE_MATCH",
        confidence_rule_id: "CONF_HIGH_DIRECT_EVIDENCE",
        evidence_dispositions: { "REC-112": "COUNTED_SUPPORTS (ACCEPTED)" },
        rules_triggered: [
          {
            rule_id: "RULE_TEMPORAL_OVERLAP_VERIFIED",
            description: "REC-112 documents acute briefing compression during the 15:00 handover window.",
            applied: true,
            weight: 0.72,
          },
        ],
      },
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

function TracePill({ text, tone = "green" }: { text: string; tone?: "green" | "orange" | "muted" | "purple" }) {
  const bg: Record<string, string> = {
    green: "#e1ede7",
    orange: "#f4e8de",
    muted: "#eeeee8",
    purple: "#ede8f5",
  };
  const fg: Record<string, string> = {
    green: "#285f4d",
    orange: "#b45c37",
    muted: "#6e7770",
    purple: "#583c87",
  };
  return (
    <span
      style={{
        fontFamily: "ui-monospace,monospace",
        fontSize: 9,
        letterSpacing: "0.08em",
        padding: "4px 7px",
        background: bg[tone],
        color: fg[tone],
        borderRadius: 2,
        fontWeight: 600,
        display: "inline-block",
      }}
    >
      {text}
    </span>
  );
}

function normalizeError(body: unknown, status: number): string {
  if (body && typeof body === "object" && "detail" in body) {
    const detail = (body as { detail: unknown }).detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
      return detail
        .map((d) => (typeof d === "object" && d && "msg" in d ? String(d.msg) : JSON.stringify(d)))
        .join("; ");
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

function renderEvidenceDispositions(
  dispositions: ExplanationTrace["evidence_dispositions"]
): Array<{ key: string; value: string }> {
  if (!dispositions) return [];
  if (Array.isArray(dispositions)) {
    return dispositions.map((item, idx) => ({
      key: item.source_record_id || item.record_id || `EV-${idx + 1}`,
      value: item.reason ? `${item.disposition} (${item.reason})` : item.disposition,
    }));
  }
  return Object.entries(dispositions).map(([key, value]) => ({
    key,
    value: typeof value === "string" ? value : JSON.stringify(value),
  }));
}

function App() {
  const [showDemo, setShowDemo] = useState(window.location.hash === "#/demo");
  const [records, setRecords] = useState<RecordItem[]>([]);
  const [investigation, setInvestigation] = useState<Investigation | null>(null);
  const [history, setHistory] = useState<History[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [selectedPresetIndex, setSelectedPresetIndex] = useState(0);
  const [sourceId, setSourceId] = useState("");
  const [quote, setQuote] = useState("");
  const [reason, setReason] = useState("");
  const [change, setChange] = useState<{
    before: Claim;
    after: Claim;
    version: number;
    recomputedIds: string[];
    reason: string;
    disputedCount: number;
  } | null>(null);
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
    return next;
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
      insufficient: investigation.claims.filter((c) => c.status === "INSUFFICIENT" || c.status === "CONTRADICTED")
        .length,
      disputed: investigation.claims.reduce((acc, c) => acc + c.evidence.filter((e) => e.disputed).length, 0),
    };
  }, [investigation]);

  async function startInvestigation() {
    setBusy(true);
    setError("");
    setChange(null);
    const chosen = PRESETS[selectedPresetIndex];
    try {
      // Point #1 & #2: Send both preset_id and exact canonical question
      const result = await api<Investigation>("/investigations", {
        method: "POST",
        body: JSON.stringify({
          preset_id: chosen.preset_id,
          question: chosen.question,
        }),
      });
      setInvestigation(result);
      const firstClaim = result.claims[0];
      setSelectedId(firstClaim?.id ?? "");
      if (firstClaim?.dependencies[0]) {
        setSourceId(firstClaim.dependencies[0]);
        const rec = records.find((r) => r.id === firstClaim.dependencies[0]);
        setQuote(rec?.text ?? "");
      }
      setHistory(await api<History[]>(`/investigations/${result.id}/history`));
      setOfflineMode(false);
    } catch {
      const mockInv: Investigation = {
        ...FALLBACK_INVESTIGATION,
        question: chosen.question,
        preset_id: chosen.preset_id,
        created_at: new Date().toISOString(),
      };
      setInvestigation(mockInv);
      setSelectedId(mockInv.claims[0].id);
      setSourceId(mockInv.claims[0].dependencies[0] ?? "");
      setQuote(FALLBACK_RECORDS[0].text);
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
    const beforeFallback = selected;
    try {
      const challengeRes = await api<ChallengeResponsePayload>(
        `/investigations/${investigation.id}/claims/${selected.id}/challenge`,
        {
          method: "POST",
          body: JSON.stringify({
            reason: reason.trim(),
            source_record_id: sourceId,
            quote: quote.trim(),
          }),
        }
      );
      const updatedInv = await refresh(investigation.id);
      const afterFromInv = updatedInv.claims.find((claim) => claim.id === selected.id);
      const beforeSnap =
        extractClaimFromSnapshot(challengeRes.before, selected.id, selected.hypothesis_id) ?? beforeFallback;
      const afterSnap =
        extractClaimFromSnapshot(challengeRes.after, selected.id, selected.hypothesis_id) ?? afterFromInv;

      if (afterSnap) {
        const disputedCount = afterSnap.evidence.filter((e) => e.disputed).length;
        setChange({
          before: beforeSnap,
          after: afterSnap,
          version: challengeRes.version ?? afterSnap.version ?? updatedInv.version,
          recomputedIds: challengeRes.recomputed_claim_ids ?? [selected.hypothesis_id],
          reason: challengeRes.reason ?? reason.trim(),
          disputedCount,
        });
      }
      setReason("");
    } catch (e) {
      if (offlineMode) {
        const nextVersion = investigation.version + 1;
        const updatedEvidence = selected.evidence.map((ev) =>
          ev.source_record_id === sourceId ? { ...ev, disputed: true } : ev
        );
        const afterClaim: Claim = {
          ...selected,
          status: "PARTIAL",
          confidence: Math.max(0.28, selected.confidence - 0.24),
          version: nextVersion,
          uncertainty: `Human review flagged source ${sourceId}: "${reason.trim()}". Conclusion downgraded pending audit.`,
          evidence: updatedEvidence,
          explanation_trace: {
            status_rule_id: "STATUS_DOWNGRADED_BY_DISPUTED_SOURCE",
            confidence_rule_id: "CONF_PENALTY_ACTIVE_CHALLENGE",
            evidence_dispositions: {
              [sourceId]: "DISPUTED_RETAINED_FOR_HUMAN_REVIEW",
            },
            rules_triggered: [
              {
                rule_id: "RULE_CHALLENGED_EVIDENCE_PENALTY",
                description: `Source ${sourceId} marked disputed; dependent claim recomputed at revision v${nextVersion}.`,
                applied: true,
                weight: -0.24,
              },
            ],
          },
        };
        setInvestigation({
          ...investigation,
          version: nextVersion,
          claims: investigation.claims.map((c) => (c.id === selected.id ? afterClaim : c)),
        });
        setChange({
          before: beforeFallback,
          after: afterClaim,
          version: nextVersion,
          recomputedIds: [selected.hypothesis_id],
          reason: reason.trim(),
          disputedCount: updatedEvidence.filter((ev) => ev.disputed).length,
        });
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
          <span className="pulse" /> {offlineMode ? "OFFLINE SYNTHETIC FALLBACK" : "MAIN BACKEND · 127.0.0.1:8000"}{" "}
          <span className="divider">/</span> STORY CONNECT AI COPILOT
        </div>
        <div className="nav-actions">
          <div className="mode-switcher" role="navigation" aria-label="Workspace mode">
            <a href="#top" className="mode-pill active">
              01 · Handover Copilot (Port 8000)
            </a>
            <a href="#/demo" className="mode-pill">
              02 · Isolated Policy Demo (Port 8083) ↗
            </a>
          </div>
          <div className="profile">
            <span className="profile-icon">HR</span>
            <span>
              Hospitality &amp; HR
              <br />
              <b>Operations Manager</b>
            </span>
          </div>
        </div>
      </header>

      <main id="top">
        {/* ── Story Connect Platform Context Strip ── */}
        <div className="eyebrow">
          <span>STORY CONNECT LUXURY HOTEL PLATFORM</span>
          <span className="line" />
          <span>AI COPILOT · EVIDENCE VERIFICATION &amp; REASSESSMENT ENGINE</span>
        </div>

        <section className="intro">
          <div>
            <h1>
              Find what gets
              <br />
              <em>left behind.</em>
            </h1>
            <p>
              Story Connect unifies luxury hotel HR policies, training, and shift operations across Administrators, HR
              Managers, Department Managers, and Employees. The <strong>Story Connect AI Copilot</strong> adds
              deterministic evidence verification, dependency tracking, and auditable reassessment so AI proposals never
              override human governance.
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

        {/* ── Executive Telemetry Ribbon ── */}
        <section className="kpi-ribbon" aria-label="Engine governance telemetry">
          <div className="kpi-tile">
            <span className="kpi-label">EVIDENCE CORPUS</span>
            <strong>{records.length} Source Records</strong>
            <small>Exact-substring provenance</small>
          </div>
          <div className="kpi-tile">
            <span className="kpi-label">EXPLANATION TRACE</span>
            <strong>Rule IDs + Dispositions</strong>
            <small>Deterministic engine authority</small>
          </div>
          <div className="kpi-tile">
            <span className="kpi-label">PROVIDER SAFEGUARDS</span>
            <strong>181 Focused Tests</strong>
            <small>MockProvider default · Muse Spark gated</small>
          </div>
          <div className="kpi-tile">
            <span className="kpi-label">GOVERNANCE GATE</span>
            <strong>Append-Only Audit</strong>
            <small>Atomic challenge recomputation</small>
          </div>
        </section>

        <aside className="synthetic-banner">
          <span className="banner-icon">✳</span>
          <div>
            <strong>Synthetic hospitality case · decision support only · human review required</strong>
            <span>
              All records are fictional. Quote presence establishes exact-substring provenance only — not semantic
              entailment or causation. Never use for employee ranking, blame, or employment decisions.
            </span>
          </div>
          <span className="banner-tag">{offlineMode ? "OFFLINE FALLBACK" : "FASTAPI :8000"}</span>
        </aside>

        {error && (
          <div className="error" role="alert">
            {error}
          </div>
        )}

        {/* ── Section 01: Canonical Preset & Question Launchpad ── */}
        <section className="workspace">
          <div className="workspace-heading">
            <div>
              <span className="section-kicker">01 — CANONICAL INVESTIGATION LAUNCHPAD</span>
              <h2>Select a preset hospitality inquiry</h2>
            </div>
            <span className="record-count">
              PRESET_ID: <b>{PRESETS[selectedPresetIndex].preset_id}</b> · {records.length} RECORDS
            </span>
          </div>
          <div className="investigation-row">
            <label className="select-wrap">
              <span>CANONICAL PRESET (PRESET_ID)</span>
              <select
                value={selectedPresetIndex}
                onChange={(e) => setSelectedPresetIndex(Number(e.target.value))}
              >
                {PRESETS.map((item, i) => (
                  <option value={i} key={item.preset_id}>
                    {item.label} [{item.preset_id}]
                  </option>
                ))}
              </select>
            </label>
            <div className="question-preview">
              <span>CANONICAL BACKEND QUESTION</span>
              <p>{PRESETS[selectedPresetIndex].question}</p>
            </div>
            <button className="primary" onClick={startInvestigation} disabled={busy}>
              {busy ? "Evaluating…" : investigation ? "Re-run Investigation" : "Run Investigation"}
              <span>↗</span>
            </button>
          </div>
        </section>

        {/* ── Section 01B: Challenge Snapshot Banner (Point #5) ── */}
        {change && (
          <section className="change-card" role="status" aria-live="polite">
            <div className="change-mark">↻</div>
            <div style={{ flex: 1 }}>
              <span className="section-kicker">
                CHALLENGE RECOMPUTATION SNAPSHOT · UPDATED REVISION v{String(change.version).padStart(2, "0")}
              </span>
              <h3>{HYPOTHESES[change.after.hypothesis_id] ?? change.after.hypothesis_id}</h3>

              <div className="challenge-snapshot-grid">
                <div className="snapshot-box">
                  <span className="kpi-label">BEFORE CHALLENGE (REV v{change.before.version})</span>
                  <strong>
                    {change.before.status} · {Math.round(change.before.confidence * 100)}% est.
                  </strong>
                  <small>{change.before.uncertainty}</small>
                </div>
                <div className="snapshot-box after">
                  <span className="kpi-label">AFTER CHALLENGE (REV v{change.after.version})</span>
                  <strong>
                    {change.after.status} · {Math.round(change.after.confidence * 100)}% est.
                  </strong>
                  <small>{change.after.uncertainty}</small>
                </div>
              </div>

              <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 10 }}>
                <TracePill
                  text={`RECOMPUTED CLAIM IDS: ${change.recomputedIds.map((id) => HYPOTHESES[id] ?? id).join(", ")}`}
                  tone="green"
                />
                <TracePill text={`DISPUTED EVIDENCE ITEMS: ${change.disputedCount}`} tone="orange" />
                <TracePill text={`CHALLENGE REASON: "${change.reason}"`} tone="muted" />
              </div>
            </div>
          </section>
        )}

        {investigation && (
          <>
            <section className="findings">
              <div className="workspace-heading">
                <div>
                  <span className="section-kicker">02 — HYPOTHESIS &amp; EVIDENCE MATRIX</span>
                  <h2>Five candidate contributors</h2>
                </div>
                <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                  <span className="version-pill">SUPPORTED: {statusCounts.supported}</span>
                  <span className="version-pill">PARTIAL: {statusCounts.partial}</span>
                  <span className="version-pill">DISPUTED EVIDENCE: {statusCounts.disputed}</span>
                  <span
                    className="version-pill"
                    style={{ background: "#e3ede7", color: "#285f4d", fontWeight: 600 }}
                  >
                    REVISION {String(investigation.version).padStart(2, "0")}
                  </span>
                </div>
              </div>

              <div className="finding-grid">
                <div className="claim-list" role="tablist" aria-label="Hypothesis claims">
                  {investigation.claims.map((claim, index) => {
                    const pct = Math.round(claim.confidence * 100);
                    const hasDisputed = claim.evidence.some((e) => e.disputed);
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
                        }}
                      >
                        <span className="claim-number">0{index + 1}</span>
                        <div className="claim-tab-body">
                          <span className="claim-title">
                            {HYPOTHESES[claim.hypothesis_id] ?? claim.hypothesis_id}
                          </span>
                          <span className={`status-text ${claim.status.toLowerCase()}`}>
                            {claim.status} · {pct}% est. · v{claim.version}
                            {hasDisputed ? " · DISPUTED" : ""}
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
                        {Math.round(selected.confidence * 100)}% review estimate (deterministic engine assessment ·
                        human verification required)
                      </span>
                    </p>

                    {/* ── Point #4: Backend Explanation Trace Inspector ── */}
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
                          ENGINE EXPLANATION TRACE (STATUS &amp; CONFIDENCE RULES + DISPOSITIONS)
                        </span>
                        <TracePill text="DETERMINISTIC ENGINE AUTHORITY" tone="purple" />
                      </div>

                      {selected.explanation_trace ? (
                        <>
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
                          </div>

                          {renderEvidenceDispositions(selected.explanation_trace.evidence_dispositions).length > 0 && (
                            <div style={{ marginTop: 10 }}>
                              <span className="kpi-label">EVIDENCE DISPOSITIONS</span>
                              <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginTop: 4 }}>
                                {renderEvidenceDispositions(selected.explanation_trace.evidence_dispositions).map(
                                  (d) => (
                                    <TracePill
                                      key={d.key}
                                      text={`${d.key} → ${d.value}`}
                                      tone={d.value.includes("DISPUTED") || d.value.includes("EXCLUDED") ? "orange" : "green"}
                                    />
                                  )
                                )}
                              </div>
                            </div>
                          )}

                          {selected.explanation_trace.rules_triggered &&
                            selected.explanation_trace.rules_triggered.length > 0 && (
                              <ul style={{ margin: "8px 0 0 16px", padding: 0, fontSize: 11, color: "#4f5a52" }}>
                                {selected.explanation_trace.rules_triggered.map((rule) => (
                                  <li key={rule.rule_id} style={{ marginBottom: 3 }}>
                                    <code>{rule.rule_id}</code>
                                    {rule.description ? `: ${rule.description}` : ""}
                                    {rule.weight !== undefined ? ` (weight: ${rule.weight})` : ""}
                                  </li>
                                ))}
                              </ul>
                            )}
                        </>
                      ) : (
                        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 8 }}>
                          <TracePill text={`STATUS_RULE: DERIVED_${selected.status}`} tone="green" />
                          <TracePill
                            text={`EVIDENCE_COUNT: ${selected.evidence.length} (${
                              selected.evidence.filter((e) => e.disputed).length
                            } DISPUTED)`}
                            tone="muted"
                          />
                        </div>
                      )}
                    </div>

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
                        <span className="section-kicker">SOURCE RECORDS &amp; REVIEW STATES</span>
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
                              {item.disputed && <span>DISPUTED · CHALLENGED BY REVIEWER · RETAINED FOR AUDIT</span>}
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
                        Challenge a source quote &amp; recompute{" "}
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
                            placeholder="Describe why this source quote is disputed, incomplete, or contextually misapplied…"
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
                                  "Supervisor confirmed manual paper fallback checklist was active at Desk B during the shift handover window."
                                );
                              }
                            }}
                          >
                            ⚡ Auto-Fill Demo Challenge
                          </button>
                        </div>
                        <small>
                          Only claims depending on this record are reevaluated. The challenge is stored in append-only
                          history; source material is never erased.
                        </small>
                      </form>
                    </details>
                  </article>
                )}
              </div>
            </section>

            <section className="history-section">
              <div className="workspace-heading">
                <div>
                  <span className="section-kicker">03 — APPEND-ONLY AUDIT TRAIL</span>
                  <h2>Investigation revision history &amp; before/after snapshots</h2>
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
                              : "Claim challenged · dependent claims atomically recomputed"}
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
                        {entry.before && entry.after && (
                          <div style={{ marginTop: 6, fontSize: 10, fontFamily: "ui-monospace,monospace", color: "#496a58" }}>
                            Snapshot recorded for {Object.keys(entry.after).length} claim(s)
                          </div>
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
          STORY CONNECT AI COPILOT <i>·</i> LUXURY HOTEL EMPLOYEE EXPERIENCE PLATFORM
        </span>
        <span>
          META GLOBAL AI HACKATHON <i>·</i> HUMAN REVIEW REQUIRED
        </span>
      </footer>
    </div>
  );
}

export default App;