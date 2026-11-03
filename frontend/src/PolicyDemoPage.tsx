import { useCallback, useEffect, useState } from "react";
import {
  extractDemoError,
  POLICY_DEMO_PROPOSAL_LABEL,
  STATIC_VISUAL_NOTICE,
} from "./auditParsers";

type ProvenanceDetail = {
  side: "OLDER" | "NEWER";
  passage_id: string;
  passage_ordinal: number | null;
  start_cp: number;
  end_cp: number;
  quote: string;
  source_sha256: string;
  verified_locally: boolean;
};

type ScenarioResult = {
  comparison_id: string;
  request_id: string;
  proposed_relation: string;
  candidate_id: string;
  reasoning: string;
  status: string;
  semantic_support: string;
  human_review_required: boolean;
  core_classification: string;
  core_proposed_classification: string;
  uncertainty_reasons: string[];
  official_policy_mutated: boolean;
  impact_status: string;
  provenance_details: ProvenanceDetail[];
  provenance_limitation_notice: string;
  scenario_id?: string;
};

type ScenarioMeta = {
  id: string;
  title: string;
  category: string;
  relation_type: string;
  description: string;
  default_challenge_department: string;
};

type SessionCreatedResponse = {
  session_id: string;
  scenario_id: string;
  created_at_iso?: string;
  created_at?: string;
};

type ChallengeResult = {
  challenge: {
    challenge_id: string;
    target_department: string;
    target_side: string;
    target_passage_id: string;
    description: string;
  };
  applicability_audit: {
    department_id: string;
    applicability_status: string;
    finding: string;
    older_scope_state: string;
    newer_scope_state: string;
    older_departments?: string[];
    newer_departments?: string[];
    dependency_count?: number;
    text_mention?: boolean;
  };
  contract_enforcement: {
    one_sided_change_rejected: boolean;
    explanation: string;
  };
  recomputed_proposal: {
    candidate_id: string;
    proposed_relation: string;
    status: string;
    semantic_support: string;
    human_review_required: boolean;
    abstain: boolean;
    citations_count: number;
    uncertainty_reasons: string[];
  };
  recomputed_core_result: {
    classification: string;
    proposed_classification: string;
    human_review_required: boolean;
    official_policy_mutated: boolean;
    uncertainty_reasons: string[];
    impact_status: string;
  };
  differentiator_takeaway: string;
};

type AuditTrailEvent = {
  sequence_number: number;
  timestamp_iso: string;
  scenario_id: string;
  target_department: string;
  target_side: string;
  applicability_status: string;
  initial_relation: string;
  recomputed_relation: string;
  core_classification: string;
  uncertainty_reasons: string[];
  contract_enforced: boolean;
  summary: string;
};

const SCENARIO_DEPARTMENTS: Record<string, string[]> = {
  scheduling: ["HOUSEKEEPING", "FRONT_DESK", "MAINTENANCE"],
  uniform_grooming: ["CONCIERGE", "BELL_SERVICE", "VALET"],
  lounge_access: ["VALET", "SECURITY", "BANQUETS"],
};

const DEFAULT_SCENARIO_LIST: ScenarioMeta[] = [
  {
    id: "scheduling",
    title: "Scheduling Notice — Compatible Change",
    category: "Operations & Scheduling",
    relation_type: "COMPATIBLE_CHANGE",
    description: "Shift-change notification timeline updated from 48h to 24h across property operations.",
    default_challenge_department: "HOUSEKEEPING",
  },
  {
    id: "uniform_grooming",
    title: "Uniform & Grooming — Contradiction",
    category: "Guest Relations & Standards",
    relation_type: "CONTRADICTION",
    description:
      "Incompatible mandatory emblem placement rules (left lapel vs. right lapel) for Guest Relations Ambassadors.",
    default_challenge_department: "CONCIERGE",
  },
  {
    id: "lounge_access",
    title: "Executive Lounge Access — Scope / Time Difference",
    category: "Loyalty & Access",
    relation_type: "SCOPE_OR_TIME_DIFFERENCE",
    description:
      "Disjoint lounge access standards across distinct property collections and non-overlapping effective dates.",
    default_challenge_department: "VALET",
  },
];

const SAM_VISUAL_EVIDENCE: Record<
  string,
  {
    evidenceId: string;
    caption: string;
    maskRegionLabel: string;
    iouConfidence: string;
    bboxCoords: string;
    olderVisualNote: string;
    newerVisualNote: string;
    policyTieIn: string;
    v1Highlight: string;
    v2Highlight: string;
  }
> = {
  scheduling: {
    evidenceId: "VIS-SAM-301 · ROSTER TERMINAL CAPTURE",
    caption: "Back-of-House Digital Shift Notice Board (Terminal B)",
    maskRegionLabel: "Illustrative Mask #01: Shift Lock Banner & Missing Scope Tag",
    iouConfidence: "0.964 IoU",
    bboxCoords: "[x: 42, y: 18, w: 310, h: 74]",
    olderVisualNote: "v1 Capture: Displays 48-hour lock notice scoped to Front Desk.",
    newerVisualNote: "v2 Capture: Displays 24-hour notice header with blank scope tag.",
    policyTieIn:
      "Static mask illustration marks the roster header; it is not a model result. The policy demo API separately returns department applicability as UNGROUNDED.",
    v1Highlight: "LOCK WINDOW: 48 HOURS",
    v2Highlight: "LOCK WINDOW: 24 HOURS",
  },
  uniform_grooming: {
    evidenceId: "VIS-SAM-302 · AMBASSADOR BLAZER SPEC DIAGRAM",
    caption: "Guest Relations Standard Blazer — Lapel Pin Placement Audit",
    maskRegionLabel: "Illustrative Mask #02: Left vs. Right Lapel Emblem Region",
    iouConfidence: "0.982 IoU",
    bboxCoords: "[x: 118, y: 64, w: 96, h: 92]",
    olderVisualNote: "v1 Spec Diagram: Static illustration marks the LEFT lapel (1.5 cm above stitch).",
    newerVisualNote: "v2 Spec Diagram: Static illustration marks the RIGHT lapel (diagram only).",
    policyTieIn:
      "Static mask illustration marks lapel regions in the v1 and v2 diagrams; it does not prove a spatial contradiction. The policy demo API supplies the proposal and review status.",
    v1Highlight: "LEFT LAPEL CREST [x:118]",
    v2Highlight: "RIGHT LAPEL CREST [x:264]",
  },
  lounge_access: {
    evidenceId: "VIS-SAM-303 · EXECUTIVE LOUNGE KEYCARD READER",
    caption: "Floor 14 Executive Lounge Access Reader & Tier Signage",
    maskRegionLabel: "Illustrative Mask #03: Property Collection Plaque & Effective Date Window",
    iouConfidence: "0.951 IoU",
    bboxCoords: "[x: 78, y: 30, w: 245, h: 88]",
    olderVisualNote: "v1 Signage: Heritage Wing plaque (2022–2024 window).",
    newerVisualNote: "v2 Signage: Signature Tower plaque (2025–2028 window).",
    policyTieIn:
      "Static illustration marks property wing plaques and date stamps; it does not establish scope or time applicability. The policy demo API supplies its own proposal and uncertainty fields.",
    v1Highlight: "HERITAGE WING (2022-24)",
    v2Highlight: "SIGNATURE TOWER (2025-28)",
  },
};

const EXPLICIT_DEMO_SCENARIOS: Record<string, ScenarioResult> = {
  scheduling: {
    comparison_id: "cmp-scheduling-001",
    request_id: "req-demo-sched-01",
    proposed_relation: "COMPATIBLE_CHANGE",
    candidate_id: "cand-sched-v1-v2",
    reasoning:
      "v2 shortens shift notification from 48 hours to 24 hours; text offsets are verified locally, but department scope coverage requires human verification.",
    status: "PROPOSAL_ONLY",
    semantic_support: "NOT_VERIFIED",
    human_review_required: true,
    core_classification: "INCONCLUSIVE",
    core_proposed_classification: "COMPATIBLE_CHANGE",
    uncertainty_reasons: ["DEPARTMENT_SCOPE_UNGROUNDED", "SEMANTIC_ENTAILMENT_NOT_VERIFIED"],
    official_policy_mutated: false,
    impact_status: "INCONCLUSIVE",
    scenario_id: "scheduling",
    provenance_limitation_notice:
      "Exact character offsets and SHA-256 hashes prove local substring presence only — never semantic correctness or department applicability.",
    provenance_details: [
      {
        side: "OLDER",
        passage_id: "p000001-sched-v1",
        passage_ordinal: 1,
        start_cp: 0,
        end_cp: 89,
        quote: "Supervisors must publish shift-change notices at least 48 hours before the affected roster begins.",
        source_sha256: "8f434346648f6b96df89dda901c5176b10a6d83961dd3c1ac88b59b2dc327aa4",
        verified_locally: true,
      },
      {
        side: "NEWER",
        passage_id: "p000001-sched-v2",
        passage_ordinal: 1,
        start_cp: 0,
        end_cp: 89,
        quote: "Supervisors must publish shift-change notices at least 24 hours before the affected roster begins.",
        source_sha256: "2c26b46b68ffc68ff99b453c1d30413413422d706483bfa0f98a5e886266e7ae",
        verified_locally: true,
      },
    ],
  },
  uniform_grooming: {
    comparison_id: "cmp-uniform-002",
    request_id: "req-demo-unif-02",
    proposed_relation: "CONTRADICTION",
    candidate_id: "cand-unif-v1-v2",
    reasoning:
      "v1 mandates placement of the Grand Luminary emblem on the left lapel, whereas v2 mandates the right lapel without an exception clause.",
    status: "PROPOSAL_ONLY",
    semantic_support: "NOT_VERIFIED",
    human_review_required: true,
    core_classification: "INCONCLUSIVE",
    core_proposed_classification: "CONTRADICTION",
    uncertainty_reasons: ["SCOPE_APPLICABILITY_UNVERIFIED", "HUMAN_REVIEW_GATE_ACTIVE"],
    official_policy_mutated: false,
    impact_status: "INCONCLUSIVE",
    scenario_id: "uniform_grooming",
    provenance_limitation_notice:
      "Exact character offsets and SHA-256 hashes prove local substring presence only — never semantic correctness or department applicability.",
    provenance_details: [
      {
        side: "OLDER",
        passage_id: "p000002-unif-v1",
        passage_ordinal: 1,
        start_cp: 12,
        end_cp: 108,
        quote: "Guest Relations Ambassadors must wear the brass property emblem centered on the left blazer lapel.",
        source_sha256: "4e07408562bedb8b60ce05c1decfe3ad16b72230967de01f640b7e4729b49fce",
        verified_locally: true,
      },
      {
        side: "NEWER",
        passage_id: "p000002-unif-v2",
        passage_ordinal: 1,
        start_cp: 12,
        end_cp: 109,
        quote: "Guest Relations Ambassadors must wear the brass property emblem centered on the right blazer lapel.",
        source_sha256: "d4735e3a265e16eee03f59718b9b5d03019c07d8b6c51f90da3a666eec13ab35",
        verified_locally: true,
      },
    ],
  },
  lounge_access: {
    comparison_id: "cmp-lounge-003",
    request_id: "req-demo-lounge-03",
    proposed_relation: "SCOPE_OR_TIME_DIFFERENCE",
    candidate_id: "cand-lounge-v1-v2",
    reasoning:
      "v1 and v2 govern non-overlapping effective date windows and distinct property wings; direct conflict cannot be established without scope grounding.",
    status: "PROPOSAL_ONLY",
    semantic_support: "NOT_VERIFIED",
    human_review_required: true,
    core_classification: "INCONCLUSIVE",
    core_proposed_classification: "SCOPE_OR_TIME_DIFFERENCE",
    uncertainty_reasons: ["NON_OVERLAPPING_EFFECTIVE_DATES", "DEPARTMENT_GROUNDING_ABSENT"],
    official_policy_mutated: false,
    impact_status: "INCONCLUSIVE",
    scenario_id: "lounge_access",
    provenance_limitation_notice:
      "Exact character offsets and SHA-256 hashes prove local substring presence only — never semantic correctness or department applicability.",
    provenance_details: [
      {
        side: "OLDER",
        passage_id: "p000003-lounge-v1",
        passage_ordinal: 1,
        start_cp: 0,
        end_cp: 95,
        quote: "Heritage Wing Executive Lounge access is complimentary for Titanium guests between 06:00 and 22:00.",
        source_sha256: "6b86b273ff34fce19d6b804eff5a3f5747ada4eaa22f1d49c01e52ddb7875b4b",
        verified_locally: true,
      },
      {
        side: "NEWER",
        passage_id: "p000003-lounge-v2",
        passage_ordinal: 1,
        start_cp: 0,
        end_cp: 98,
        quote: "Signature Tower Lounge access requires an active keycard endorsement after 20:00 for all guest tiers.",
        source_sha256: "e7f6c011776e8db7cd330b54174fd76f7d0216b612387a5ffcfb81e6f0919683",
        verified_locally: true,
      },
    ],
  },
};

function normalizeDemoError(body: unknown, status: number): string {
  return extractDemoError(body, status);
}

async function demoApi<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`/demo-api${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...init?.headers },
    });
  } catch (err) {
    throw new Error(
      `Cannot reach Policy Demo API at 127.0.0.1:8083 (/demo-api${path}). Start policy_demo_api.py on port 8083 or explicitly enable Demo Fixture Mode. (${
        (err as Error).message
      })`
    );
  }
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(normalizeDemoError(body, res.status));
  }
  return res.json() as Promise<T>;
}

function Badge({
  text,
  color = "green",
}: {
  text: string;
  color?: "green" | "orange" | "muted" | "review" | "purple";
}) {
  const bgMap: Record<string, string> = {
    green: "#e3f3eb",
    orange: "#fcf0e4",
    muted: "#f0f2f5",
    review: "#fef6e6",
    purple: "#f3e8ff",
  };
  const colorMap: Record<string, string> = {
    green: "#16583e",
    orange: "#b45309",
    muted: "#475569",
    review: "#92400e",
    purple: "#6b21a8",
  };
  const borderMap: Record<string, string> = {
    green: "#a7d9c0",
    orange: "#fcd34d",
    muted: "#cbd5e1",
    review: "#fde68a",
    purple: "#d8b4fe",
  };
  return (
    <span
      style={{
        fontFamily: "var(--mono)",
        fontSize: 9.5,
        letterSpacing: "0.08em",
        padding: "4px 9px",
        background: bgMap[color],
        color: colorMap[color],
        border: `1px solid ${borderMap[color]}`,
        borderRadius: 4,
        display: "inline-block",
        fontWeight: 700,
        textTransform: "uppercase",
      }}
    >
      {text}
    </span>
  );
}

function SectionKicker({ children }: { children: React.ReactNode }) {
  return (
    <span
      style={{
        fontFamily: "var(--mono)",
        fontSize: 10,
        letterSpacing: "0.14em",
        color: "var(--ink-tertiary)",
        display: "block",
        marginBottom: 6,
        fontWeight: 700,
        textTransform: "uppercase",
      }}
    >
      {children}
    </span>
  );
}

function SectionHeading({ num, title }: { num: string; title: string }) {
  return (
    <div style={{ borderTop: "1px solid var(--line)", paddingTop: 32, marginTop: 44, marginBottom: 18 }}>
      <SectionKicker>{num}</SectionKicker>
      <h2
        style={{
          fontFamily: "Inter, Georgia, serif",
          fontSize: 24,
          fontWeight: 600,
          margin: "4px 0 0",
          color: "var(--ink)",
          letterSpacing: "-0.02em",
        }}
      >
        {title}
      </h2>
    </div>
  );
}

export default function PolicyDemoPage() {
  const [scenarios, setScenarios] = useState<ScenarioMeta[]>(DEFAULT_SCENARIO_LIST);
  const [selectedScenarioId, setSelectedScenarioId] = useState<string>("scheduling");
  const [scenario, setScenario] = useState<ScenarioResult | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [sessionCreatedAtIso, setSessionCreatedAtIso] = useState<string | null>(null);
  const [selectedDept, setSelectedDept] = useState<string>("HOUSEKEEPING");
  const [historyEvents, setHistoryEvents] = useState<AuditTrailEvent[]>([]);
  const [challenge, setChallenge] = useState<ChallengeResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [challenging, setChallenging] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [error, setError] = useState("");
  const [challengeError, setChallengeError] = useState("");
  const [showSamMask, setShowSamMask] = useState(true);
  // P0.2: Never fall back silently — require explicit user selection for offline demo fixtures
  const [explicitOfflineDemo, setExplicitOfflineDemo] = useState(false);

  const currentScenarioMeta = scenarios.find((s) => s.id === selectedScenarioId);
  const visualEvidence = SAM_VISUAL_EVIDENCE[selectedScenarioId] || SAM_VISUAL_EVIDENCE.scheduling;

  useEffect(() => {
    if (explicitOfflineDemo) return;
    demoApi<ScenarioMeta[]>("/scenarios")
      .then((data) => {
        setScenarios(data);
      })
      .catch(() => {
        // Keep selector metadata available; actual scenario load will surface the error
      });
  }, [explicitOfflineDemo]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError("");
    setChallenge(null);
    setChallengeError("");
    setHistoryEvents([]);

    const depts = SCENARIO_DEPARTMENTS[selectedScenarioId] || ["HOUSEKEEPING"];
    setSelectedDept(depts[0]);

    if (explicitOfflineDemo) {
      const fixture = EXPLICIT_DEMO_SCENARIOS[selectedScenarioId] || EXPLICIT_DEMO_SCENARIOS.scheduling;
      setScenario(fixture);
      setSessionId("explicit-demo-session-8083");
      setSessionCreatedAtIso(new Date().toISOString());
      setLoading(false);
      return;
    }

    Promise.all([
      demoApi<ScenarioResult>(`/scenario?id=${selectedScenarioId}`),
      demoApi<SessionCreatedResponse>("/session/new", {
        method: "POST",
        body: JSON.stringify({ scenario_id: selectedScenarioId }),
      }),
    ])
      .then(([scenarioData, sessionData]) => {
        if (cancelled) return;
        setScenario(scenarioData);
        setSessionId(sessionData.session_id);
        setSessionCreatedAtIso(sessionData.created_at_iso ?? sessionData.created_at ?? new Date().toISOString());
        setError("");
      })
      .catch((e: Error) => {
        if (cancelled) return;
        // P0.2: No silent fallback! Clear scenario and display visible error message
        setScenario(null);
        setSessionId(null);
        setError(e.message);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [selectedScenarioId, explicitOfflineDemo]);

  const runChallenge = useCallback(async () => {
    if (!scenario) return;
    setChallenging(true);
    setChallengeError("");

    if (explicitOfflineDemo) {
      const nextSeq = historyEvents.length + 1;
      const syntheticChallenge: ChallengeResult = {
        challenge: {
          challenge_id: `chg-${selectedScenarioId}-${nextSeq}`,
          target_department: selectedDept,
          target_side: "OLDER_AND_NEWER",
          target_passage_id: scenario.provenance_details[0]?.passage_id ?? "p000001",
          description: `Reviewer challenged whether ${selectedDept} is grounded in policy scope metadata.`,
        },
        applicability_audit: {
          department_id: selectedDept,
          applicability_status: "UNGROUNDED",
          finding: `Scope metadata does not establish verified applicability for ${selectedDept}.`,
          older_scope_state: "EXCERPT_ONLY",
          newer_scope_state: "UNVERIFIED_SCOPE",
        },
        contract_enforcement: {
          one_sided_change_rejected: true,
          explanation:
            "Unverified candidate proposals cannot mutate official policy or override missing department scope grounding.",
        },
        recomputed_proposal: {
          candidate_id: scenario.candidate_id,
          proposed_relation: "INCONCLUSIVE",
          status: "PROPOSAL_ONLY",
          semantic_support: "NOT_VERIFIED",
          human_review_required: true,
          abstain: true,
          citations_count: scenario.provenance_details.length,
          uncertainty_reasons: [
            `DEPARTMENT_${selectedDept}_UNGROUNDED`,
            "APPLICABILITY_AUDIT_FAILED",
            "HUMAN_REVIEW_REQUIRED",
          ],
        },
        recomputed_core_result: {
          classification: "INCONCLUSIVE",
          proposed_classification: scenario.proposed_relation,
          human_review_required: true,
          official_policy_mutated: false,
          uncertainty_reasons: [
            `DEPARTMENT_${selectedDept}_UNGROUNDED`,
            "QUOTE_PROVENANCE_ONLY",
            "SEMANTIC_SUPPORT_NOT_VERIFIED",
          ],
          impact_status: "INCONCLUSIVE",
        },
        differentiator_takeaway: `Challenging ${selectedDept} applicability exposes ungrounded scope assumptions: the engine abstains and recomputes the proposal from ${scenario.proposed_relation} to INCONCLUSIVE while preserving immutable audit history.`,
      };
      setChallenge(syntheticChallenge);
      setHistoryEvents((prev) => [
        ...prev,
        {
          sequence_number: nextSeq,
          timestamp_iso: new Date().toISOString(),
          scenario_id: selectedScenarioId,
          target_department: selectedDept,
          target_side: "OLDER_AND_NEWER",
          applicability_status: "UNGROUNDED",
          initial_relation: scenario.proposed_relation,
          recomputed_relation: "INCONCLUSIVE",
          core_classification: "INCONCLUSIVE",
          uncertainty_reasons: syntheticChallenge.recomputed_core_result.uncertainty_reasons,
          contract_enforced: true,
          summary: `Department ${selectedDept} applicability challenged; proposal recomputed from ${scenario.proposed_relation} to INCONCLUSIVE.`,
        },
      ]);
      setChallenging(false);
      return;
    }

    try {
      const result = await demoApi<
        ChallengeResult & { session_id?: string; sequence_number?: number; history_count?: number }
      >("/challenge", {
        method: "POST",
        body: JSON.stringify({
          department_id: selectedDept,
          scenario_id: selectedScenarioId,
          session_id: sessionId ?? undefined,
        }),
      });
      setChallenge(result);

      if (sessionId) {
        const historyData = await demoApi<{ events: AuditTrailEvent[] }>(`/session/${sessionId}/history`);
        setHistoryEvents(historyData.events);
      }
    } catch (e: unknown) {
      // P0.2: Show visible error when challenge fails
      setChallengeError((e as Error).message);
    } finally {
      setChallenging(false);
    }
  }, [scenario, selectedDept, selectedScenarioId, sessionId, explicitOfflineDemo, historyEvents.length]);

  const startNewInvestigation = useCallback(async () => {
    if (!sessionId) return;
    setResetting(true);
    setChallengeError("");
    try {
      if (!explicitOfflineDemo) {
        await demoApi<{ session_id: string; scenario_id: string; event_count: number }>(
          `/session/${sessionId}/reset`,
          {
            method: "POST",
            body: JSON.stringify({ scenario_id: selectedScenarioId }),
          }
        );
      }
      setChallenge(null);
      setHistoryEvents([]);
      const depts = SCENARIO_DEPARTMENTS[selectedScenarioId] || ["HOUSEKEEPING"];
      setSelectedDept(depts[0]);
    } catch (e: unknown) {
      setChallengeError((e as Error).message);
    } finally {
      setResetting(false);
    }
  }, [sessionId, selectedScenarioId, explicitOfflineDemo]);

  const card: React.CSSProperties = {
    background: "#ffffff",
    border: "1px solid var(--line)",
    borderRadius: 12,
    padding: "24px 26px",
    boxShadow: "var(--shadow-md)",
  };

  const labelStyle: React.CSSProperties = {
    fontFamily: "var(--mono)",
    fontSize: 9.5,
    letterSpacing: "0.12em",
    color: "var(--ink-tertiary)",
    display: "block",
    marginBottom: 5,
    fontWeight: 700,
    textTransform: "uppercase",
  };

  const valueStyle: React.CSSProperties = {
    fontFamily: "Inter, sans-serif",
    fontSize: 15,
    fontWeight: 600,
    color: "var(--ink)",
    margin: 0,
    letterSpacing: "-0.01em",
  };

  return (
    <div className="shell">
      <header className="topbar policy-topbar">
        <a className="brand" href="#" aria-label="Story Connect home">
          <span className="brand-mark">S</span>
          <div className="brand-text">
            <strong>storyconnect</strong>
            <span>POLICY EVIDENCE · STORY CONNECT</span>
          </div>
        </a>
        <div className={`top-context ${error ? "is-error" : loading ? "is-loading" : "is-ready"}`} aria-label={explicitOfflineDemo ? "Explicit demo fixture mode" : error ? "Policy Demo API error" : loading ? "Connecting to Policy Demo API" : "Policy Demo API ready"}>
          <span className="top-context-status"><span className={`pulse ${error ? "is-error" : loading ? "is-loading" : "is-ready"}`} />
            {explicitOfflineDemo ? "DEMO FIXTURE · OPT-IN" : error ? "POLICY API ERROR" : loading ? "CONNECTING TO POLICY API" : "POLICY API READY"}
          </span>
          <span className="divider" aria-hidden="true">/</span>
          <span className="top-context-title">POLICY COMPARISON</span>
        </div>
        <div className="nav-actions">
          <nav className="mode-switcher" aria-label="Workspace mode">
            <a href="#" className="mode-pill">
              Handover review
            </a>
            <a href="#/demo" className="mode-pill active">
              Policy comparison
            </a>
          </nav>
          <details className="mobile-nav">
            <summary aria-label="Open workspace navigation"><span aria-hidden="true">☰</span><span>Menu</span></summary>
            <nav aria-label="Workspace navigation">
              <a href="#">Handover investigation</a>
              <a href="#/demo">Policy comparison</a>
            </nav>
          </details>
          <div className="profile" aria-label="Policy review workspace">Review workspace</div>
        </div>
      </header>

      <main>
        <section className="overview-hero policy-overview" aria-label="Policy comparison overview">
          <div className="overview-copy">
        <div className="eyebrow" style={{ marginBottom: 20 }}>
          <span className="gold-dot" aria-hidden="true" />

          <span>POLICY DEMO · POLICY COMPARISON</span>
        </div>

        <section className="intro">
          <div>
            <h1>
              Policy <em>comparison.</em>
            </h1>
            <p>
              Compare synthetic policy revisions across v1 and v2, inspect exact SHA-256 citation provenance and
              illustrative static mask diagrams, then challenge department applicability to observe
              recomputation to <strong>INCONCLUSIVE</strong>.
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

          </div>
          <div className="overview-panel">
            <div className="overview-panel-head">
              <strong>Policy comparison overview</strong>
              <span>Provenance, review status and history</span>
            </div>
        <section className="kpi-ribbon" aria-label="Policy engine telemetry">
          <div className="kpi-tile">
            <div className="kpi-tile-header">
              <span className="kpi-label">CITATION PROVENANCE</span>
              <span className="kpi-micro-badge">LOCAL HASH</span>
            </div>
            <strong>SHA-256 + Codepoints</strong>
            <small>
              <span className="kpi-dot" style={{ background: "#16583e" }} />
              Synthetic fixture · review required
            </small>
          </div>
          <div className="kpi-tile">
            <div className="kpi-tile-header">
              <span className="kpi-label">MULTIMODAL LAYER</span>
              <span className="kpi-micro-badge">VISION MASK</span>
            </div>
            <strong>Illustrative Mask Diagrams</strong>
            <small>
              <span className="kpi-dot" style={{ background: "#8a7533" }} />
              Visual IoU ≠ semantic proof
            </small>
          </div>
          <div className="kpi-tile">
            <div className="kpi-tile-header">
              <span className="kpi-label">OFFICIAL POLICY STATE</span>
              <span className="kpi-micro-badge">IMMUTABLE</span>
            </div>
            <strong>Immutable (False)</strong>
            <small>
              <span className="kpi-dot" style={{ background: "#b45309" }} />
              PROPOSAL_ONLY contract enforced
            </small>
          </div>
          <div className="kpi-tile">
            <div className="kpi-tile-header">
              <span className="kpi-label">SESSION AUDIT LOG</span>
              <span className="kpi-micro-badge">APPEND-ONLY</span>
            </div>
            <strong>{historyEvents.length} / 20 Events</strong>
            <small>
              <span className="kpi-dot" style={{ background: "#475569" }} />
              Ephemeral in-memory session trail
            </small>
          </div>
        </section>
          </div>
        </section>

        <aside className="synthetic-banner">
          <span className="banner-icon">✳</span>
          <div>
            <strong>
              {explicitOfflineDemo
                ? "EXPLICIT DEMO FIXTURE MODE ACTIVE · NOT CONNECTED TO 127.0.0.1:8083"
                : "Synthetic demo · strict status boundaries · human review required"}
            </strong>
            <span>
              All policy data is fictional. SHA-256 citation provenance is returned by the policy demo API. Mask
              diagrams and IoU values are static frontend illustrations, not model output. Neither establishes
              semantic support or legal applicability. Official policy is never mutated (
              <code>official_policy_mutated: false</code>).
            </span>
          </div>
          {explicitOfflineDemo ? (
            <button type="button" className="quick-fill-btn" onClick={() => setExplicitOfflineDemo(false)}>
              Exit Demo Mode &amp; Reconnect Port 8083
            </button>
          ) : (
            <span className="banner-tag">PORT 8083</span>
          )}
        </aside>

        <aside
          style={{
            marginTop: 12,
            padding: "12px 16px",
            background: explicitOfflineDemo ? "#f3ecdf" : "#f1f5f9",
            border: `1px solid ${explicitOfflineDemo ? "#e8d4b8" : "#cbd5e1"}`,
            borderRadius: 8,
            fontSize: 11.5,
            color: explicitOfflineDemo ? "#8a5c20" : "#334155",
            lineHeight: 1.55,
          }}
        >
          <b>Service Boundary Notice (Studio 02 Isolation):</b> This Policy &amp; SAM 3.1 Studio is strictly decoupled
          from the main Handover Backend (<code>127.0.0.1:8081</code>).{" "}
          {explicitOfflineDemo
            ? "Explicit Demo Fixture Mode was manually selected by the user — no results are attributed to the main backend or live port 8083 service."
            : "Targeting the isolated policy_demo_api.py service on 127.0.0.1:8083."}
        </aside>

        {/* P0.2: Visible error alert with explicit opt-in demo button */}
        {error && (
          <div
            className="error"
            role="alert"
            style={{
              marginTop: 20,
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              flexWrap: "wrap",
              gap: 12,
            }}
          >
            <div>
              <strong>Policy Demo API Error:</strong> {error}
            </div>
            <button type="button" className="quick-fill-btn" onClick={() => setExplicitOfflineDemo(true)}>
              Enable Explicit Demo Fixture Mode
            </button>
          </div>
        )}

        {/* ── Scenario Selector Cards + Dropdown ───────────────────────────── */}
        <div style={{ ...card, marginTop: 24, padding: "20px 24px" }}>
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              flexWrap: "wrap",
              gap: 14,
            }}
          >
            <div>
              <span className="section-kicker" style={{ marginBottom: 4 }}>
                SELECT INVESTIGATION SCENARIO
              </span>
              <p
                style={{
                  margin: 0,
                  fontSize: 13,
                  color: "var(--ink-secondary)",
                  fontFamily: "Inter, sans-serif",
                }}
              >
                Switch between synthetic hospitality scenarios to inspect policy demo proposals, static illustrative
                mask diagrams, and department challenges.
              </p>
            </div>
            <div style={{ minWidth: 260 }}>
              <select
                aria-label="Select policy comparison scenario"
                value={selectedScenarioId}
                onChange={(e) => {
                  setSelectedScenarioId(e.target.value);
                  setChallenge(null);
                  setChallengeError("");
                }}
                style={{
                  fontFamily: "var(--mono)",
                  fontSize: 12,
                  fontWeight: 600,
                  color: "var(--ink)",
                  border: "1px solid var(--line-strong)",
                  background: "#ffffff",
                  padding: "9px 12px",
                  borderRadius: 6,
                  width: "100%",
                  cursor: "pointer",
                }}
              >
                {scenarios.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.title}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <div className="scenario-pills">
            {scenarios.map((s) => {
              const isActive = selectedScenarioId === s.id;
              return (
                <button
                  key={s.id}
                  type="button"
                  className={`scenario-pill-btn ${isActive ? "active" : ""}`}
                  onClick={() => {
                    setSelectedScenarioId(s.id);
                    setChallenge(null);
                    setChallengeError("");
                  }}
                >
                  <div>
                    <div
                      style={{
                        display: "flex",
                        justifyContent: "space-between",
                        alignItems: "center",
                        marginBottom: 6,
                      }}
                    >
                      <span
                        style={{
                          fontSize: 9.5,
                          fontFamily: "var(--mono)",
                          color: "var(--ink-tertiary)",
                          letterSpacing: "0.1em",
                          fontWeight: 700,
                        }}
                      >
                        {s.id.toUpperCase()}
                      </span>
                      <Badge
                        text={s.relation_type}
                        color={
                          s.relation_type === "CONTRADICTION"
                            ? "orange"
                            : s.relation_type === "SCOPE_OR_TIME_DIFFERENCE"
                            ? "review"
                            : "green"
                        }
                      />
                    </div>
                    <span>{s.title}</span>
                  </div>
                  <small>{s.description}</small>
                </button>
              );
            })}
          </div>
        </div>

        {loading && (
          <div
            style={{
              marginTop: 40,
              textAlign: "center",
              fontFamily: "ui-monospace,monospace",
              fontSize: 11,
              color: "#758078",
              letterSpacing: "0.08em",
            }}
          >
            LOADING SCENARIO…
          </div>
        )}

        {scenario && (
          <>
            <SectionHeading
              num="01 — POLICY VERSIONS"
              title={
                currentScenarioMeta
                  ? `The Grand Luminary Hotel — ${currentScenarioMeta.title}`
                  : "The Grand Luminary Hotel — Policy Versions"
              }
            />

            <div className="policy-versions-grid">
              {(() => {
                const older = scenario.provenance_details.find((d) => d.side === "OLDER");
                const isLounge = scenario.comparison_id.includes("lounge");
                const olderDates = isLounge ? "2022-01-01 → 2024-01-01" : "2024-01-01 → 2027-01-01";
                return (
                  <div style={{ ...card, borderTop: "3px solid #64748b", background: "#ffffff" }}>
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
                      <SectionKicker>POLICY v1 — HISTORIC BASELINE</SectionKicker>
                      <Badge text="BASELINE v1" color="muted" />
                    </div>
                    <div style={{ display: "grid", gap: 14 }}>
                      <div style={{ display: "flex", justifyContent: "space-between", gap: 12 }}>
                        <div>
                          <span style={labelStyle}>VERSION ID</span>
                          <p style={valueStyle}>v1</p>
                        </div>
                        <div>
                          <span style={labelStyle}>EFFECTIVE DATES</span>
                          <p style={{ ...valueStyle, fontFamily: "var(--mono)", fontSize: 13 }}>{olderDates}</p>
                        </div>
                      </div>
                      <div style={{ display: "flex", justifyContent: "space-between", gap: 12 }}>
                        <div>
                          <span style={labelStyle}>DOCUMENT ID</span>
                          <p style={{ ...valueStyle, fontFamily: "var(--mono)", fontSize: 12 }}>
                            {scenario.comparison_id
                              .replace("cmp-", "")
                              .replace("-001", "")
                              .replace("-002", "")
                              .replace("-003", "")}
                          </p>
                        </div>
                        <div>
                          <span style={labelStyle}>PASSAGE ID</span>
                          <p style={{ fontFamily: "var(--mono)", fontSize: 11, color: "var(--ink-secondary)", margin: 0 }}>
                            {older?.passage_id ?? "—"}
                          </p>
                        </div>
                      </div>
                      <div>
                        <span style={labelStyle}>RELEVANT PASSAGE (BASELINE REQUIREMENT)</span>
                        <blockquote
                          style={{
                            fontFamily: "Georgia,'Times New Roman',serif",
                            fontSize: 14,
                            fontStyle: "italic",
                            color: "#1e293b",
                            margin: "8px 0 0",
                            padding: "16px 20px",
                            background: "#f8fafc",
                            borderLeft: "3px solid #64748b",
                            borderRadius: "0 8px 8px 0",
                            lineHeight: 1.65,
                          }}
                        >
                          “{older?.quote ?? "—"}”
                        </blockquote>
                      </div>
                    </div>
                  </div>
                );
              })()}

              {(() => {
                const newer = scenario.provenance_details.find((d) => d.side === "NEWER");
                const isLounge = scenario.comparison_id.includes("lounge");
                const newerDates = isLounge ? "2025-01-01 → 2028-01-01" : "2026-01-01 → 2027-01-01";
                return (
                  <div style={{ ...card, borderTop: "3px solid #16583e", background: "#ffffff" }}>
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
                      <SectionKicker>POLICY v2 — REVISED AMENDMENT</SectionKicker>
                      <Badge text="REVISED v2" color="green" />
                    </div>
                    <div style={{ display: "grid", gap: 14 }}>
                      <div style={{ display: "flex", justifyContent: "space-between", gap: 12 }}>
                        <div>
                          <span style={labelStyle}>VERSION ID</span>
                          <p style={valueStyle}>v2</p>
                        </div>
                        <div>
                          <span style={labelStyle}>EFFECTIVE DATES</span>
                          <p style={{ ...valueStyle, fontFamily: "var(--mono)", fontSize: 13 }}>{newerDates}</p>
                        </div>
                      </div>
                      <div style={{ display: "flex", justifyContent: "space-between", gap: 12 }}>
                        <div>
                          <span style={labelStyle}>DOCUMENT ID</span>
                          <p style={{ ...valueStyle, fontFamily: "var(--mono)", fontSize: 12 }}>
                            {scenario.comparison_id
                              .replace("cmp-", "")
                              .replace("-001", "")
                              .replace("-002", "")
                              .replace("-003", "")}
                          </p>
                        </div>
                        <div>
                          <span style={labelStyle}>PASSAGE ID</span>
                          <p style={{ fontFamily: "var(--mono)", fontSize: 11, color: "var(--ink-secondary)", margin: 0 }}>
                            {newer?.passage_id ?? "—"}
                          </p>
                        </div>
                      </div>
                      <div>
                        <span style={labelStyle}>RELEVANT PASSAGE (REVISED REQUIREMENT)</span>
                        <blockquote
                          style={{
                            fontFamily: "Georgia,'Times New Roman',serif",
                            fontSize: 14,
                            fontStyle: "italic",
                            color: "#0f172a",
                            margin: "8px 0 0",
                            padding: "16px 20px",
                            background: "#f0fdf4",
                            borderLeft: "3px solid #16583e",
                            borderRadius: "0 8px 8px 0",
                            lineHeight: 1.65,
                          }}
                        >
                          “{newer?.quote ?? "—"}”
                        </blockquote>
                      </div>
                    </div>
                  </div>
                );
              })()}
            </div>

            <SectionHeading
              num="02 — PROPOSAL vs ASSESSMENT"
              title="Candidate proposal vs. validated system classification"
            />

            <div style={{ ...card, display: "grid", gap: 20 }}>
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))",
                  gap: 20,
                  alignItems: "stretch",
                }}
              >
                <div
                  style={{
                    padding: "18px 20px",
                    background: "#f8fafc",
                    border: "1px solid #e2e8f0",
                    borderRadius: 10,
                    display: "flex",
                    flexDirection: "column",
                    justifyContent: "space-between",
                  }}
                >
                  <div>
                    <span style={labelStyle}>{POLICY_DEMO_PROPOSAL_LABEL}</span>
                    <p
                      style={{
                        fontFamily: "Inter, sans-serif",
                        fontSize: 22,
                        fontWeight: 700,
                        margin: "6px 0 4px",
                        color: "#1e293b",
                        letterSpacing: "-0.02em",
                      }}
                    >
                      {scenario.proposed_relation}
                    </p>
                  </div>
                  <div style={{ marginTop: 12 }}>
                    <Badge text="STATUS: PROPOSAL_ONLY" color="muted" />
                  </div>
                </div>

                <div
                  style={{
                    padding: "18px 20px",
                    background: "#fffbeb",
                    border: "1px solid #fef3c7",
                    borderLeft: "4px solid #d97706",
                    borderRadius: 10,
                    display: "flex",
                    flexDirection: "column",
                    justifyContent: "space-between",
                  }}
                >
                  <div>
                    <span style={labelStyle}>VALIDATED CORE CLASSIFICATION (DETERMINISTIC)</span>
                    <p
                      style={{
                        fontFamily: "Inter, sans-serif",
                        fontSize: 22,
                        fontWeight: 700,
                        margin: "6px 0 4px",
                        color: "#b45309",
                        letterSpacing: "-0.02em",
                      }}
                    >
                      {scenario.core_classification}
                    </p>
                  </div>
                  <div style={{ marginTop: 12 }}>
                    <Badge text="CORE ENGINE: INCONCLUSIVE (ABSTAIN)" color="orange" />
                  </div>
                </div>

                <div
                  style={{
                    padding: "18px 20px",
                    background: "#f0fdf4",
                    border: "1px solid #dcfce7",
                    borderLeft: "4px solid #16583e",
                    borderRadius: 10,
                    display: "flex",
                    flexDirection: "column",
                    justifyContent: "space-between",
                  }}
                >
                  <div>
                    <span style={labelStyle}>OFFICIAL POLICY MUTATED</span>
                    <p
                      style={{
                        fontFamily: "var(--mono)",
                        fontSize: 18,
                        fontWeight: 700,
                        margin: "6px 0 4px",
                        color: "#16583e",
                      }}
                    >
                      {String(scenario.official_policy_mutated).toUpperCase()} (IMMUTABLE)
                    </p>
                  </div>
                  <div style={{ marginTop: 12 }}>
                    <Badge text="CONTRACT: MUTATION LOCKED" color="green" />
                  </div>
                </div>
              </div>

              <div style={{ display: "flex", flexWrap: "wrap", gap: 8, alignItems: "center" }}>
                <Badge text={`STATUS: ${scenario.status}`} color="muted" />
                <Badge text={`SEMANTIC SUPPORT: ${scenario.semantic_support}`} color="orange" />
                <Badge text={`CORE: ${scenario.core_classification}`} color="review" />
                {scenario.human_review_required && <Badge text="HUMAN REVIEW REQUIRED" color="review" />}
              </div>

              <div
                style={{
                  background: "#fefcf6",
                  border: "1px solid #fde68a",
                  borderLeft: "4px solid #d97706",
                  borderRadius: 8,
                  padding: "14px 18px",
                  fontSize: 12,
                  color: "#92400e",
                  lineHeight: 1.6,
                }}
              >
                <b>Status Boundary Notice:</b> <code>PROPOSAL_ONLY</code> indicates a candidate relation synthesized by
                the model, never an approved policy conclusion. <code>NOT_VERIFIED</code> confirms semantic support has
                not been independently proven.
              </div>

              <div>
                <span style={labelStyle}>CANDIDATE REASONING</span>
                <p
                  style={{
                    fontSize: 13,
                    color: "var(--ink-secondary)",
                    lineHeight: 1.65,
                    margin: "4px 0 0",
                    fontFamily: "Georgia,'Times New Roman',serif",
                    fontStyle: "italic",
                    background: "#f8fafc",
                    padding: "14px 18px",
                    borderRadius: 8,
                    border: "1px solid #e2e8f0",
                  }}
                >
                  "{scenario.reasoning}"
                </p>
              </div>
            </div>

            <SectionHeading
              num="03 — EVIDENCE & MULTIMODAL INSPECTOR"
              title="API citation provenance & illustrative static visual regions"
            />

            <div
              style={{
                marginBottom: 16,
                padding: "12px 16px",
                background: "#f1f5f9",
                border: "1px solid #cbd5e1",
                borderRadius: 8,
                fontSize: 11.5,
                color: "#334155",
                display: "flex",
                alignItems: "center",
                gap: 8,
              }}
            >
              <Badge text="ZERO TRUST" color="green" />
              <span>
                <b>Provenance verified locally — not by model.</b> {scenario.provenance_limitation_notice}
              </span>
            </div>

            <div style={{ display: "grid", gap: 14 }}>
              {scenario.provenance_details.map((detail, i) => (
                <div
                  key={detail.passage_id + i}
                  style={{
                    ...card,
                    borderLeft: `4px solid ${detail.side === "OLDER" ? "#64748b" : "#16583e"}`,
                  }}
                >
                  <div
                    style={{
                      display: "flex",
                      justifyContent: "space-between",
                      alignItems: "flex-start",
                      flexWrap: "wrap",
                      gap: 10,
                      marginBottom: 14,
                    }}
                  >
                    <div>
                      <SectionKicker>
                        {detail.side} CITATION — PASSAGE {detail.passage_ordinal ?? i + 1}
                      </SectionKicker>
                      <span style={{ fontFamily: "var(--mono)", fontSize: 11, color: "var(--ink-secondary)", fontWeight: 600 }}>
                        {detail.passage_id}
                      </span>
                    </div>
                    <Badge text={detail.verified_locally ? "✓ SHA-256 VERIFIED LOCALLY" : "UNVERIFIED"} color="green" />
                  </div>

                  <div className="citation-offsets-grid">
                    <div>
                      <span style={labelStyle}>START CP</span>
                      <p style={{ fontFamily: "var(--mono)", fontSize: 12, fontWeight: 700, margin: 0 }}>{detail.start_cp}</p>
                    </div>
                    <div>
                      <span style={labelStyle}>END CP</span>
                      <p style={{ fontFamily: "var(--mono)", fontSize: 12, fontWeight: 700, margin: 0 }}>{detail.end_cp}</p>
                    </div>
                    <div>
                      <span style={labelStyle}>OFFSET LENGTH</span>
                      <p style={{ fontFamily: "var(--mono)", fontSize: 12, fontWeight: 700, margin: 0 }}>
                        {detail.end_cp - detail.start_cp} chars
                      </p>
                    </div>
                    <div>
                      <span style={labelStyle}>SOURCE SHA256</span>
                      <p style={{ fontFamily: "var(--mono)", fontSize: 11, margin: 0, color: "var(--ink-secondary)" }}>
                        {detail.source_sha256.slice(0, 24)}…
                      </p>
                    </div>
                  </div>

                  <div>
                    <span style={labelStyle}>EXACT VERBATIM SUBSTRING</span>
                    <blockquote
                      style={{
                        fontFamily: "Georgia,'Times New Roman',serif",
                        fontSize: 13.5,
                        fontStyle: "italic",
                        color: "var(--ink)",
                        margin: "6px 0 0",
                        padding: "12px 16px",
                        background: "#f8fafc",
                        borderLeft: "3px solid #cbd5e1",
                        borderRadius: "0 6px 6px 0",
                        lineHeight: 1.6,
                      }}
                    >
                      "{detail.quote}"
                    </blockquote>
                  </div>
                </div>
              ))}
            </div>

            <div className="sam-inspector-card" style={{ marginTop: 24 }}>
              <div className="sam-header">
                <div>
                  <SectionKicker>03B — STATIC FRONTEND ILLUSTRATION (NOT MODEL SEGMENTATION)</SectionKicker>
                  <h3 style={{ margin: "4px 0 0", fontFamily: "Inter, Georgia, serif", fontSize: 20, fontWeight: 600 }}>
                    {visualEvidence.caption}
                  </h3>
                </div>
                <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                  <Badge text={visualEvidence.evidenceId} color="purple" />
                  <Badge text={`ILLUSTRATIVE STATIC IOU: ${visualEvidence.iouConfidence}`} color="muted" />
                  <button
                    type="button"
                    className="mask-toggle-btn"
                    onClick={() => setShowSamMask((prev) => !prev)}
                  >
                    {showSamMask ? "◉ Hide Illustrative Mask Overlay" : "◎ Show Illustrative Mask Overlay"}
                  </button>
                </div>
              </div>

              <div className="sam-canvas-grid">
                <div className={`sam-visual-stage ${showSamMask ? "mask-active" : ""}`}>
                  <div className="sam-hud-bar">
                    <span className="sam-coord-tag">STATIC ILLUSTRATION RECTANGLE {visualEvidence.bboxCoords}</span>
                    <span className="sam-coord-tag">SOURCE: FRONTEND FIXTURE ART</span>
                  </div>

                  <svg
                    viewBox="0 0 520 175"
                    className="sam-svg-blueprint"
                    role="img"
                    aria-label="Illustrative static visual comparison canvas; not model output"
                  >
                    <defs>
                      <pattern id="samGrid" width="20" height="20" patternUnits="userSpaceOnUse">
                        <path
                          d="M 20 0 L 0 0 0 20"
                          fill="none"
                          stroke="rgba(255,255,255,0.06)"
                          strokeWidth="1"
                        />
                      </pattern>
                    </defs>
                    <rect width="520" height="175" fill="url(#samGrid)" />

                    <rect
                      x="14"
                      y="16"
                      width="235"
                      height="142"
                      rx="4"
                      fill="rgba(255,255,255,0.04)"
                      stroke="rgba(255,255,255,0.18)"
                    />
                    <text x="26" y="36" fill="#94a3b8" fontSize="9" fontFamily="monospace" letterSpacing="1" fontWeight="bold">
                      POLICY v1 ARTIFACT REGION
                    </text>
                    <text x="26" y="62" fill="#f8fafc" fontSize="11" fontFamily="Inter, sans-serif">
                      {visualEvidence.olderVisualNote.slice(0, 42)}
                    </text>
                    <text x="26" y="78" fill="#94a3b8" fontSize="10" fontFamily="Inter, sans-serif">
                      {visualEvidence.olderVisualNote.slice(42)}
                    </text>

                    <rect
                      x="271"
                      y="16"
                      width="235"
                      height="142"
                      rx="4"
                      fill="rgba(255,255,255,0.04)"
                      stroke="rgba(255,255,255,0.18)"
                    />
                    <text x="283" y="36" fill="#4ade80" fontSize="9" fontFamily="monospace" letterSpacing="1" fontWeight="bold">
                      POLICY v2 ARTIFACT REGION
                    </text>
                    <text x="283" y="62" fill="#f8fafc" fontSize="11" fontFamily="Inter, sans-serif">
                      {visualEvidence.newerVisualNote.slice(0, 42)}
                    </text>
                    <text x="283" y="78" fill="#94a3b8" fontSize="10" fontFamily="Inter, sans-serif">
                      {visualEvidence.newerVisualNote.slice(42)}
                    </text>

                    {showSamMask && (
                      <g>
                        <rect
                          x="24"
                          y="95"
                          width="215"
                          height="48"
                          rx="3"
                          fill="rgba(199, 163, 43, 0.22)"
                          stroke="#c7a32b"
                          strokeWidth="1.5"
                          strokeDasharray="4 2"
                        />
                        <circle cx="24" cy="95" r="3" fill="#e9d5ff" />
                        <circle cx="239" cy="143" r="3" fill="#e9d5ff" />
                        <text x="34" y="116" fill="#f3e8ff" fontSize="9.5" fontFamily="monospace" fontWeight="bold">
                          MASK A · {visualEvidence.v1Highlight}
                        </text>
                        <text x="34" y="131" fill="#d8b4fe" fontSize="8.5" fontFamily="monospace">
                          STATIC ILLUSTRATION · {visualEvidence.iouConfidence}
                        </text>

                        <rect
                          x="281"
                          y="95"
                          width="215"
                          height="48"
                          rx="3"
                          fill="rgba(249, 115, 22, 0.28)"
                          stroke="#fb923c"
                          strokeWidth="1.5"
                          strokeDasharray="4 2"
                        />
                        <circle cx="281" cy="95" r="3" fill="#fed7aa" />
                        <circle cx="496" cy="143" r="3" fill="#fed7aa" />
                        <text x="291" y="116" fill="#ffedd5" fontSize="9.5" fontFamily="monospace" fontWeight="bold">
                          MASK B · {visualEvidence.v2Highlight}
                        </text>
                        <text x="291" y="131" fill="#fdba74" fontSize="8.5" fontFamily="monospace">
                          Spatial Delta Detected · Review Required
                        </text>
                      </g>
                    )}
                  </svg>

                  {showSamMask && (
                    <div className="sam-mask-overlay" aria-label="Illustrative static mask region">
                      <span>{visualEvidence.maskRegionLabel}</span>
                    </div>
                  )}
                </div>

                <div style={{ display: "grid", gap: 12, alignContent: "start" }}>
                  <div>
                    <span style={labelStyle}>POLICY-SPECIFIC VISUAL TIE-IN</span>
                    <p style={{ fontSize: 13, color: "var(--ink)", lineHeight: 1.6, margin: "4px 0 0" }}>
                      {visualEvidence.policyTieIn}
                    </p>
                  </div>
                  <div
                    style={{
                      background: "#fffbeb",
                      border: "1px solid #fef3c7",
                      borderLeft: "4px solid #d97706",
                      padding: "12px 14px",
                      borderRadius: 8,
                      fontSize: 11.5,
                      color: "#92400e",
                      lineHeight: 1.55,
                    }}
                  >
                    <b>Transparency Boundary:</b> The displayed IoU value ({visualEvidence.iouConfidence}) is static
                    illustrative fixture content, not model segmentation confidence. It is separate from policy
                    evidence verification (<code>semantic_support: NOT_VERIFIED</code>).
                  </div>
                </div>
              </div>

              <p className="static-visual-notice">{STATIC_VISUAL_NOTICE}</p>
            </div>

            <SectionHeading
              num="04 — REVIEWER CHALLENGE"
              title="Multi-turn department applicability challenge"
            />

            <div style={card}>
              <div style={{ display: "grid", gap: 16 }}>
                <p style={{ fontSize: 13.5, color: "var(--ink-secondary)", lineHeight: 1.65, margin: 0 }}>
                  A reviewer questions whether the policy revision is grounded for a specific operational department.
                  Select a target department below to submit a challenge to <code>POST /demo-api/challenge</code> and
                  observe honest recomputation to <strong>INCONCLUSIVE</strong>.
                </p>

                {challengeError && (
                  <div className="error" role="alert">
                    {challengeError}
                  </div>
                )}

                <div
                  style={{
                    display: "flex",
                    flexWrap: "wrap",
                    gap: 14,
                    alignItems: "center",
                    padding: "20px 22px",
                    background: "#f8fafc",
                    borderRadius: 12,
                    border: "1px solid #e2e8f0",
                  }}
                >
                  <span style={{ ...labelStyle, marginBottom: 0 }}>
                    SELECT TARGET DEPARTMENT:
                  </span>

                  <div className="dept-pill-selector">
                    {(SCENARIO_DEPARTMENTS[selectedScenarioId] || ["HOUSEKEEPING"]).map((d) => (
                      <button
                        key={d}
                        type="button"
                        className={`dept-pill-btn ${selectedDept === d ? "active" : ""}`}
                        onClick={() => setSelectedDept(d)}
                      >
                        {d}
                      </button>
                    ))}
                  </div>

                  <div style={{ marginLeft: "auto", display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
                    <button
                      className="primary"
                      onClick={runChallenge}
                      disabled={challenging}
                      aria-busy={challenging}
                    >
                      {challenging ? "Recomputing…" : `Challenge Applicability to ${selectedDept}`}
                      <span>↗</span>
                    </button>

                    {challenge && (
                      <button
                        className="secondary"
                        onClick={startNewInvestigation}
                        disabled={resetting}
                        aria-busy={resetting}
                      >
                        {resetting ? "Resetting…" : "Start New Investigation"} <span>↺</span>
                      </button>
                    )}
                  </div>
                </div>

                {challenge && (
                  <div
                    role="region"
                    aria-live="polite"
                    aria-label="Challenge recomputation results"
                    style={{ display: "grid", gap: 18, marginTop: 10 }}
                  >
                    <div className="challenge-comparison-grid">
                      <div className="before-after-card before">
                        <div>
                          <SectionKicker>BEFORE CHALLENGE</SectionKicker>
                          <p
                            style={{
                              fontFamily: "Inter, sans-serif",
                              fontSize: 20,
                              fontWeight: 700,
                              color: "#334155",
                              margin: "6px 0",
                            }}
                          >
                            {scenario.proposed_relation}
                          </p>
                        </div>
                        <div>
                          <Badge text="PROPOSAL_ONLY" color="muted" />
                        </div>
                      </div>

                      <div className="before-after-card after">
                        <div>
                          <SectionKicker>
                            AFTER CHALLENGE ({challenge.challenge.target_department})
                          </SectionKicker>
                          <p
                            style={{
                              fontFamily: "Inter, sans-serif",
                              fontSize: 20,
                              fontWeight: 700,
                              color: "#b45309",
                              margin: "6px 0",
                            }}
                          >
                            {challenge.recomputed_proposal.proposed_relation}
                          </p>
                        </div>
                        <div>
                          <Badge text={`${challenge.recomputed_proposal.status} (ABSTAIN)`} color="orange" />
                        </div>
                      </div>
                    </div>

                    <div style={{ display: "flex", flexWrap: "wrap", gap: 8, alignItems: "center" }}>
                      <span style={{ fontSize: 12, color: "var(--ink-secondary)" }}>Applicability status:</span>
                      <Badge text={challenge.applicability_audit.applicability_status} color="orange" />
                      <span style={{ fontSize: 12, color: "var(--ink-secondary)", marginLeft: 10 }}>
                        Contract enforcement:
                      </span>
                      <Badge
                        text={`one_sided_change_rejected: ${challenge.contract_enforcement.one_sided_change_rejected}`}
                        color={challenge.contract_enforcement.one_sided_change_rejected ? "green" : "muted"}
                      />
                    </div>

                    <div>
                      <span style={labelStyle}>UNCERTAINTY REASONS (RECOMPUTED)</span>
                      <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 4 }}>
                        {challenge.recomputed_core_result.uncertainty_reasons.map((r) => (
                          <Badge key={r} text={r} color="muted" />
                        ))}
                      </div>
                    </div>

                    <div
                      style={{
                        background: "#f0fdf4",
                        border: "1px solid #dcfce7",
                        borderLeft: "4px solid #16583e",
                        borderRadius: 8,
                        padding: "12px 16px",
                        fontSize: 12,
                        color: "#16583e",
                        lineHeight: 1.6,
                      }}
                    >
                      <b>Contract enforcement:</b> {challenge.contract_enforcement.explanation}
                    </div>

                    <div
                      style={{
                        background: "#fffbeb",
                        border: "1px solid #fef3c7",
                        borderRadius: 8,
                        padding: "14px 18px",
                        fontSize: 13,
                        color: "#92400e",
                        lineHeight: 1.65,
                        fontFamily: "Georgia,'Times New Roman',serif",
                        fontStyle: "italic",
                      }}
                    >
                      ✳ {challenge.differentiator_takeaway}
                    </div>
                  </div>
                )}
              </div>
            </div>

            <SectionHeading
              num="05 — AUDIT TRAIL"
              title="Investigation timeline (in-memory session audit log)"
            />

            <div
              style={{
                marginBottom: 16,
                padding: "14px 18px",
                background: "#f8fafc",
                border: "1px solid #e2e8f0",
                borderRadius: 8,
                fontSize: 12,
                color: "var(--ink-secondary)",
                lineHeight: 1.6,
              }}
            >
              <b>In-Memory Audit Notice:</b> This investigation session maintains an ephemeral, append-only audit log
              (<code>storage_mode: ephemeral_in_memory</code>, max 20 events). It resets when starting a new
              investigation, switching scenarios, or restarting the server process.
            </div>

            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                flexWrap: "wrap",
                gap: 14,
                marginBottom: 20,
                padding: "16px 20px",
                background: "#ffffff",
                border: "1px solid var(--line)",
                borderRadius: 12,
                boxShadow: "var(--shadow-sm)",
              }}
            >
              <div style={{ display: "flex", gap: 20, flexWrap: "wrap", alignItems: "center" }}>
                <div>
                  <span style={labelStyle}>SESSION ID</span>
                  <span style={{ fontFamily: "var(--mono)", fontSize: 12, fontWeight: 700, color: "var(--ink)" }}>
                    {sessionId ? `${sessionId.slice(0, 8)}…${sessionId.slice(-4)}` : "—"}
                  </span>
                </div>
                <div>
                  <span style={labelStyle}>CREATED AT (ISO)</span>
                  <span style={{ fontFamily: "var(--mono)", fontSize: 11, color: "var(--ink-secondary)" }}>
                    {sessionCreatedAtIso ? new Date(sessionCreatedAtIso).toLocaleTimeString() : "—"}
                  </span>
                </div>
                <div>
                  <span style={labelStyle}>ACTIVE SCENARIO</span>
                  <Badge text={selectedScenarioId} color="green" />
                </div>
                <div>
                  <span style={labelStyle}>CHALLENGES RECORDED</span>
                  <Badge
                    text={`${historyEvents.length} / 20`}
                    color={historyEvents.length > 0 ? "orange" : "muted"}
                  />
                </div>
              </div>

              <button
                className="secondary"
                onClick={startNewInvestigation}
                disabled={resetting || (!challenge && historyEvents.length === 0)}
                aria-busy={resetting}
                style={{ fontSize: 12 }}
              >
                {resetting ? "Resetting…" : "Start New Investigation"} <span>↺</span>
              </button>
            </div>

            <ol className="audit-timeline">
              <li className="audit-timeline-item">
                <span className="audit-timeline-node baseline" />
                <div className="audit-timeline-card">
                  <div
                    style={{
                      display: "flex",
                      justifyContent: "space-between",
                      gap: 12,
                      alignItems: "center",
                    }}
                  >
                    <b style={{ fontSize: 12.5, color: "#16583e" }}>
                      Baseline scenario loaded — initial proposal established
                    </b>
                    <Badge text="BASELINE" color="green" />
                  </div>
                  <p
                    style={{
                      fontFamily: "var(--mono)",
                      fontSize: 11,
                      color: "var(--ink-secondary)",
                      margin: 0,
                    }}
                  >
                    Scenario: {selectedScenarioId} · Proposed relation: {scenario.proposed_relation} · Status:{" "}
                    {scenario.status} · Core: {scenario.core_classification}
                  </p>
                </div>
              </li>

              {historyEvents.length === 0 && (
                <li className="audit-timeline-item">
                  <span className="audit-timeline-node" />
                  <div
                    style={{
                      padding: "14px 18px",
                      background: "#faf9f4",
                      border: "1px dashed #d5dad1",
                      borderRadius: 8,
                      fontSize: 12,
                      color: "var(--ink-tertiary)",
                      fontFamily: "Georgia,'Times New Roman',serif",
                      fontStyle: "italic",
                    }}
                  >
                    No challenges recorded yet in this session. Select a department in Section 04 and submit a
                    challenge to record an audit entry.
                  </div>
                </li>
              )}

              {historyEvents.map((evt) => (
                <li key={evt.sequence_number} className="audit-timeline-item">
                  <span className="audit-timeline-node challenge" />
                  <div className="audit-timeline-card">
                    <div
                      style={{
                        display: "flex",
                        justifyContent: "space-between",
                        alignItems: "center",
                        flexWrap: "wrap",
                        gap: 8,
                      }}
                    >
                      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                        <Badge text={`ENTRY #${evt.sequence_number}`} color="orange" />
                        <b style={{ fontSize: 13, color: "var(--ink)" }}>
                          Reviewer Challenge: {evt.target_department} ({evt.target_side})
                        </b>
                      </div>
                      <span style={{ fontFamily: "var(--mono)", fontSize: 10, color: "var(--ink-tertiary)" }}>
                        {evt.timestamp_iso}
                      </span>
                    </div>

                    <div style={{ display: "flex", flexWrap: "wrap", gap: 8, alignItems: "center" }}>
                      <span style={{ fontSize: 11.5, color: "var(--ink-secondary)" }}>Applicability:</span>
                      <Badge text={evt.applicability_status} color="orange" />
                      <span style={{ fontSize: 11.5, color: "var(--ink-secondary)", marginLeft: 6 }}>Relation shift:</span>
                      <Badge text={`${evt.initial_relation} → ${evt.recomputed_relation}`} color="review" />
                      <span style={{ fontSize: 11.5, color: "var(--ink-secondary)", marginLeft: 6 }}>Core classification:</span>
                      <Badge text={evt.core_classification} color="orange" />
                      <Badge
                        text={`contract_enforced: ${evt.contract_enforced}`}
                        color={evt.contract_enforced ? "green" : "muted"}
                      />
                    </div>

                    <div>
                      <span style={labelStyle}>UNCERTAINTY REASONS</span>
                      <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 4 }}>
                        {evt.uncertainty_reasons.map((r) => (
                          <Badge key={r} text={r} color="muted" />
                        ))}
                      </div>
                    </div>

                    <p
                      style={{
                        margin: 0,
                        fontSize: 12,
                        color: "var(--ink-secondary)",
                        fontFamily: "Georgia,'Times New Roman',serif",
                        fontStyle: "italic",
                        lineHeight: 1.55,
                      }}
                    >
                      "{evt.summary}"
                    </p>
                  </div>
                </li>
              ))}
            </ol>
          </>
        )}
      </main>

      <footer>
        <span>
          STORY CONNECT <i>·</i> POLICY EVIDENCE DEMO
        </span>
        <span>
          PROTOTYPE 0.1 <i>·</i> SYNTHETIC DATA ONLY
        </span>
      </footer>
    </div>
  );
}
