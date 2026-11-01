import { useCallback, useEffect, useState } from "react";

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
    maskRegionLabel: "SAM 3.1 Mask #01: Shift Lock Banner & Missing Scope Tag",
    iouConfidence: "0.964 IoU",
    bboxCoords: "[x: 42, y: 18, w: 310, h: 74]",
    olderVisualNote: "v1 Capture: Displays 48-hour lock notice scoped to Front Desk.",
    newerVisualNote: "v2 Capture: Displays 24-hour notice header with blank scope tag.",
    policyTieIn:
      "SAM 3.1 segmentation isolates the physical roster header and confirms the v2 notice omits explicit department tags—explaining why department applicability is UNGROUNDED.",
    v1Highlight: "LOCK WINDOW: 48 HOURS",
    v2Highlight: "LOCK WINDOW: 24 HOURS",
  },
  uniform_grooming: {
    evidenceId: "VIS-SAM-302 · AMBASSADOR BLAZER SPEC DIAGRAM",
    caption: "Guest Relations Standard Blazer — Lapel Pin Placement Audit",
    maskRegionLabel: "SAM 3.1 Mask #02: Left vs. Right Lapel Emblem Region",
    iouConfidence: "0.982 IoU",
    bboxCoords: "[x: 118, y: 64, w: 96, h: 92]",
    olderVisualNote: "v1 Spec Diagram: Crest pin segmented on LEFT lapel (1.5 cm above stitch).",
    newerVisualNote: "v2 Spec Diagram: Crest pin segmented on RIGHT lapel (direct spatial conflict).",
    policyTieIn:
      "SAM 3.1 isolates the exact lapel coordinates across v1 and v2 uniform specification diagrams, visually proving the spatial CONTRADICTION while keeping department scope separate.",
    v1Highlight: "LEFT LAPEL CREST [x:118]",
    v2Highlight: "RIGHT LAPEL CREST [x:264]",
  },
  lounge_access: {
    evidenceId: "VIS-SAM-303 · EXECUTIVE LOUNGE KEYCARD READER",
    caption: "Floor 14 Executive Lounge Access Reader & Tier Signage",
    maskRegionLabel: "SAM 3.1 Mask #03: Property Collection Plaque & Effective Date Window",
    iouConfidence: "0.951 IoU",
    bboxCoords: "[x: 78, y: 30, w: 245, h: 88]",
    olderVisualNote: "v1 Signage: Heritage Wing plaque (2022–2024 window).",
    newerVisualNote: "v2 Signage: Signature Tower plaque (2025–2028 window).",
    policyTieIn:
      "Visual region extraction isolates disjoint property wing plaques and non-overlapping date stamps, reinforcing SCOPE_OR_TIME_DIFFERENCE.",
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
  if (body && typeof body === "object" && "detail" in body) {
    const detail = (body as { detail: unknown }).detail;
    if (typeof detail === "string") return detail;
    if (detail && typeof detail === "object") {
      return "message" in detail ? String((detail as { message: unknown }).message) : JSON.stringify(detail);
    }
  }
  return `Policy Demo API request failed (HTTP ${status})`;
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
    green: "#e1ede7",
    orange: "#f4e8de",
    muted: "#eeeee8",
    review: "#f3ecdf",
    purple: "#ede8f5",
  };
  const colorMap: Record<string, string> = {
    green: "#285f4d",
    orange: "#b45c37",
    muted: "#777f78",
    review: "#8a5c20",
    purple: "#583c87",
  };
  return (
    <span
      style={{
        fontFamily: "ui-monospace,monospace",
        fontSize: 9,
        letterSpacing: "0.1em",
        padding: "4px 7px",
        background: bgMap[color],
        color: colorMap[color],
        borderRadius: 2,
        display: "inline-block",
        fontWeight: 600,
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
        fontFamily: "ui-monospace,monospace",
        fontSize: 10,
        letterSpacing: "0.12em",
        color: "#758078",
        display: "block",
        marginBottom: 6,
      }}
    >
      {children}
    </span>
  );
}

function SectionHeading({ num, title }: { num: string; title: string }) {
  return (
    <div style={{ borderTop: "1px solid var(--line)", paddingTop: 28, marginTop: 44 }}>
      <SectionKicker>{num}</SectionKicker>
      <h2
        style={{
          fontFamily: "Georgia,'Times New Roman',serif",
          fontSize: 22,
          fontWeight: 500,
          margin: "6px 0 18px",
          color: "#2c3832",
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
    background: "#fbfaf6",
    border: "1px solid #e1e1d9",
    borderRadius: 3,
    padding: "20px 22px",
  };

  const labelStyle: React.CSSProperties = {
    fontFamily: "ui-monospace,monospace",
    fontSize: 9,
    letterSpacing: "0.1em",
    color: "#858c84",
    display: "block",
    marginBottom: 4,
  };

  const valueStyle: React.CSSProperties = {
    fontFamily: "Georgia,'Times New Roman',serif",
    fontSize: 14,
    color: "#27322f",
    margin: 0,
  };

  return (
    <div className="shell">
      <header className="topbar">
        <a className="brand" href="#" aria-label="Story Connect home">
          <span className="brand-mark">S</span>
          <span>
            STORY <i>CONNECT</i>
          </span>
        </a>
        <div className="top-context">
          <span className="pulse" />{" "}
          {explicitOfflineDemo ? "EXPLICIT DEMO FIXTURE MODE (OPT-IN)" : "POLICY DEMO API · 127.0.0.1:8083"}{" "}
          <span className="divider">/</span> MULTIMODAL EVIDENCE STUDIO
        </div>
        <div className="nav-actions">
          <div className="mode-switcher" role="navigation" aria-label="Workspace mode">
            <a href="#" className="mode-pill">
              ← 01 · Handover Copilot (Port 8000)
            </a>
            <a href="#/demo" className="mode-pill active">
              02 · Isolated Policy Demo (Port 8083)
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

      <main>
        <div className="eyebrow" style={{ marginBottom: 20 }}>
          <span>FIELD NOTE 02</span>
          <span className="line" />
          <span>POLICY EVIDENCE &amp; SAM 3.1 MULTIMODAL AUDIT STUDIO</span>
        </div>

        <section className="intro">
          <div>
            <h1>
              Policy versions,
              <br />
              <em>evidence-first.</em>
            </h1>
            <p>
              Compare synthetic policy revisions across v1 and v2, verify exact SHA-256 citation provenance and Meta
              SAM 3.1 visual evidence regions locally, then challenge department applicability to observe honest
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

        <section className="kpi-ribbon" aria-label="Policy engine telemetry">
          <div className="kpi-tile">
            <span className="kpi-label">CITATION PROVENANCE</span>
            <strong>SHA-256 + Codepoints</strong>
            <small>Verified locally · Not by model</small>
          </div>
          <div className="kpi-tile">
            <span className="kpi-label">MULTIMODAL LAYER</span>
            <strong>Meta SAM 3.1 Masks</strong>
            <small>Visual IoU ≠ semantic proof</small>
          </div>
          <div className="kpi-tile">
            <span className="kpi-label">OFFICIAL POLICY STATE</span>
            <strong>Immutable (False)</strong>
            <small>PROPOSAL_ONLY contract enforced</small>
          </div>
          <div className="kpi-tile">
            <span className="kpi-label">SESSION AUDIT LOG</span>
            <strong>{historyEvents.length} / 20 Events</strong>
            <small>Ephemeral in-memory trail</small>
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
              All policy data is fictional. Local SHA-256 citation provenance and SAM 3.1 visual region masks do not
              establish semantic support or legal applicability. Official policy is never mutated (
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
            background: explicitOfflineDemo ? "#f3ecdf" : "#e8eee6",
            border: `1px solid ${explicitOfflineDemo ? "#e8d4b8" : "#d5e0d4"}`,
            borderRadius: 3,
            fontSize: 11,
            color: explicitOfflineDemo ? "#8a5c20" : "#315b47",
            lineHeight: 1.55,
          }}
        >
          <b>Service Boundary Notice (Studio 02 Isolation):</b> This Policy &amp; SAM 3.1 Studio is strictly decoupled
          from the main Handover Backend (<code>127.0.0.1:8000</code>).{" "}
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

        {/* ── Scenario Selector Pills + Dropdown ───────────────────────────── */}
        <div style={{ ...card, marginTop: 24, padding: "18px 22px" }}>
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
                  color: "#36443b",
                  fontFamily: "Georgia,'Times New Roman',serif",
                }}
              >
                Switch between synthetic luxury hospitality scenarios to inspect policy relations, SAM 3.1 visual
                masks, and department challenges.
              </p>
            </div>
            <div style={{ minWidth: 290 }}>
              <select
                aria-label="Select policy comparison scenario"
                value={selectedScenarioId}
                onChange={(e) => {
                  setSelectedScenarioId(e.target.value);
                  setChallenge(null);
                  setChallengeError("");
                }}
                style={{
                  fontFamily: "ui-monospace,monospace",
                  fontSize: 12,
                  color: "#27322f",
                  border: "1px solid #c7ccc4",
                  background: "#fbfaf6",
                  padding: "9px 12px",
                  borderRadius: 2,
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
            {scenarios.map((s) => (
              <button
                key={s.id}
                type="button"
                className={`scenario-pill-btn ${selectedScenarioId === s.id ? "active" : ""}`}
                onClick={() => {
                  setSelectedScenarioId(s.id);
                  setChallenge(null);
                  setChallengeError("");
                }}
              >
                <span>{s.id.toUpperCase()}</span>
                <small>{s.relation_type}</small>
              </button>
            ))}
          </div>

          {currentScenarioMeta && (
            <div
              style={{
                marginTop: 12,
                display: "flex",
                gap: 8,
                alignItems: "center",
                flexWrap: "wrap",
              }}
            >
              <span
                style={{
                  fontSize: 12,
                  color: "#617568",
                  fontFamily: "Georgia,'Times New Roman',serif",
                  fontStyle: "italic",
                }}
              >
                {currentScenarioMeta.description}
              </span>
              <Badge
                text={currentScenarioMeta.relation_type}
                color={
                  currentScenarioMeta.relation_type === "CONTRADICTION"
                    ? "orange"
                    : currentScenarioMeta.relation_type === "SCOPE_OR_TIME_DIFFERENCE"
                    ? "review"
                    : "green"
                }
              />
            </div>
          )}
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
                  <div style={{ ...card, borderTop: "3px solid #9da79b" }}>
                    <SectionKicker>POLICY v1 — OLDER BASELINE</SectionKicker>
                    <div style={{ display: "grid", gap: 10 }}>
                      <div style={{ display: "flex", justifyContent: "space-between" }}>
                        <div>
                          <span style={labelStyle}>VERSION ID</span>
                          <p style={valueStyle}>v1</p>
                        </div>
                        <div>
                          <span style={labelStyle}>EFFECTIVE DATES</span>
                          <p style={valueStyle}>{olderDates}</p>
                        </div>
                      </div>
                      <div>
                        <span style={labelStyle}>DOCUMENT ID</span>
                        <p style={{ ...valueStyle, fontFamily: "ui-monospace,monospace", fontSize: 11 }}>
                          {scenario.comparison_id
                            .replace("cmp-", "")
                            .replace("-001", "")
                            .replace("-002", "")
                            .replace("-003", "")}
                        </p>
                      </div>
                      <div>
                        <span style={labelStyle}>PASSAGE ID</span>
                        <p style={{ fontFamily: "ui-monospace,monospace", fontSize: 10, color: "#758078", margin: 0 }}>
                          {older?.passage_id ?? "—"}
                        </p>
                      </div>
                      <div>
                        <span style={labelStyle}>RELEVANT PASSAGE (BASELINE REQUIREMENT)</span>
                        <blockquote
                          style={{
                            fontFamily: "Georgia,'Times New Roman',serif",
                            fontSize: 13,
                            fontStyle: "italic",
                            color: "#37443c",
                            margin: "8px 0 0",
                            padding: "10px 14px",
                            background: "#e8f0eb",
                            borderLeft: "3px solid #285f4d",
                            lineHeight: 1.6,
                          }}
                        >
                          "{older?.quote ?? "—"}"
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
                  <div style={{ ...card, borderTop: "3px solid #285f4d" }}>
                    <SectionKicker>POLICY v2 — NEWER REVISION</SectionKicker>
                    <div style={{ display: "grid", gap: 10 }}>
                      <div style={{ display: "flex", justifyContent: "space-between" }}>
                        <div>
                          <span style={labelStyle}>VERSION ID</span>
                          <p style={valueStyle}>v2</p>
                        </div>
                        <div>
                          <span style={labelStyle}>EFFECTIVE DATES</span>
                          <p style={valueStyle}>{newerDates}</p>
                        </div>
                      </div>
                      <div>
                        <span style={labelStyle}>DOCUMENT ID</span>
                        <p style={{ ...valueStyle, fontFamily: "ui-monospace,monospace", fontSize: 11 }}>
                          {scenario.comparison_id
                            .replace("cmp-", "")
                            .replace("-001", "")
                            .replace("-002", "")
                            .replace("-003", "")}
                        </p>
                      </div>
                      <div>
                        <span style={labelStyle}>PASSAGE ID</span>
                        <p style={{ fontFamily: "ui-monospace,monospace", fontSize: 10, color: "#758078", margin: 0 }}>
                          {newer?.passage_id ?? "—"}
                        </p>
                      </div>
                      <div>
                        <span style={labelStyle}>RELEVANT PASSAGE (REVISED REQUIREMENT)</span>
                        <blockquote
                          style={{
                            fontFamily: "Georgia,'Times New Roman',serif",
                            fontSize: 13,
                            fontStyle: "italic",
                            color: "#37443c",
                            margin: "8px 0 0",
                            padding: "10px 14px",
                            background: "#e3ede7",
                            borderLeft: "3px solid #285f4d",
                            lineHeight: 1.6,
                          }}
                        >
                          "{newer?.quote ?? "—"}"
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

            <div style={{ ...card, display: "grid", gap: 18 }}>
              <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 28 }}>
                <div>
                  <span style={labelStyle}>CANDIDATE PROPOSED RELATION</span>
                  <p
                    style={{
                      fontFamily: "Georgia,'Times New Roman',serif",
                      fontSize: 20,
                      fontWeight: 500,
                      margin: 0,
                      color: "#285f4d",
                    }}
                  >
                    {scenario.proposed_relation}
                  </p>
                </div>
                <div>
                  <span style={labelStyle}>VALIDATED CORE CLASSIFICATION</span>
                  <p
                    style={{
                      fontFamily: "Georgia,'Times New Roman',serif",
                      fontSize: 20,
                      fontWeight: 500,
                      margin: 0,
                      color: "#b45c37",
                    }}
                  >
                    {scenario.core_classification}
                  </p>
                </div>
                <div>
                  <span style={labelStyle}>OFFICIAL POLICY MUTATED</span>
                  <p style={{ fontFamily: "ui-monospace,monospace", fontSize: 13, margin: 0, color: "#285f4d" }}>
                    {String(scenario.official_policy_mutated).toUpperCase()} (IMMUTABLE)
                  </p>
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
                  background: "#f3ecdf",
                  border: "1px solid #e8d4b8",
                  borderRadius: 2,
                  padding: "12px 15px",
                  fontSize: 11,
                  color: "#8a5c20",
                  lineHeight: 1.6,
                }}
              >
                <b>Status Boundary Notice:</b> <code>PROPOSAL_ONLY</code> indicates a candidate relation, never an
                approved policy conclusion. <code>NOT_VERIFIED</code> means semantic support has not been independently
                established.
              </div>

              <div>
                <span style={labelStyle}>CANDIDATE REASONING</span>
                <p
                  style={{
                    fontSize: 12,
                    color: "#57645b",
                    lineHeight: 1.65,
                    margin: 0,
                    fontFamily: "Georgia,'Times New Roman',serif",
                    fontStyle: "italic",
                  }}
                >
                  "{scenario.reasoning}"
                </p>
              </div>
            </div>

            <SectionHeading
              num="03 — EVIDENCE & MULTIMODAL INSPECTOR"
              title="Local SHA-256 citation provenance & SAM 3.1 visual region isolation"
            />

            <div
              style={{
                marginBottom: 14,
                padding: "10px 14px",
                background: "#e8eee6",
                border: "1px solid #d5e0d4",
                borderRadius: 2,
                fontSize: 11,
                color: "#315b47",
              }}
            >
              <b>Provenance verified locally — not by model.</b> {scenario.provenance_limitation_notice}
            </div>

            <div style={{ display: "grid", gap: 14 }}>
              {scenario.provenance_details.map((detail, i) => (
                <div
                  key={detail.passage_id + i}
                  style={{
                    ...card,
                    borderLeft: `4px solid ${detail.side === "OLDER" ? "#9da79b" : "#285f4d"}`,
                  }}
                >
                  <div
                    style={{
                      display: "flex",
                      justifyContent: "space-between",
                      alignItems: "flex-start",
                      flexWrap: "wrap",
                      gap: 10,
                      marginBottom: 12,
                    }}
                  >
                    <div>
                      <SectionKicker>
                        {detail.side} CITATION — PASSAGE {detail.passage_ordinal ?? i + 1}
                      </SectionKicker>
                      <span style={{ fontFamily: "ui-monospace,monospace", fontSize: 10, color: "#496a58" }}>
                        {detail.passage_id}
                      </span>
                    </div>
                    <Badge text={detail.verified_locally ? "✓ SHA-256 VERIFIED LOCALLY" : "UNVERIFIED"} color="green" />
                  </div>

                  <div className="citation-offsets-grid">
                    <div>
                      <span style={labelStyle}>START CP</span>
                      <p style={{ fontFamily: "ui-monospace,monospace", fontSize: 11, margin: 0 }}>{detail.start_cp}</p>
                    </div>
                    <div>
                      <span style={labelStyle}>END CP</span>
                      <p style={{ fontFamily: "ui-monospace,monospace", fontSize: 11, margin: 0 }}>{detail.end_cp}</p>
                    </div>
                    <div>
                      <span style={labelStyle}>SOURCE SHA256</span>
                      <p style={{ fontFamily: "ui-monospace,monospace", fontSize: 11, margin: 0 }}>
                        {detail.source_sha256.slice(0, 16)}…
                      </p>
                    </div>
                  </div>

                  <div>
                    <span style={labelStyle}>EXACT VERBATIM SUBSTRING</span>
                    <blockquote
                      style={{
                        fontFamily: "Georgia,'Times New Roman',serif",
                        fontSize: 13,
                        fontStyle: "italic",
                        color: "#37443c",
                        margin: "6px 0 0",
                        padding: "10px 14px",
                        background: "#f4f3ee",
                        borderLeft: "2px solid #cfd4ca",
                        lineHeight: 1.6,
                      }}
                    >
                      "{detail.quote}"
                    </blockquote>
                  </div>
                </div>
              ))}
            </div>

            <div className="sam-inspector-card" style={{ marginTop: 18 }}>
              <div className="sam-header">
                <div>
                  <SectionKicker>03B — FOCUSED MULTIMODAL EXTENSION (META SAM 3.1 SEGMENTATION)</SectionKicker>
                  <h3 style={{ margin: "4px 0 0", fontFamily: "Georgia,serif", fontSize: 18, fontWeight: 500 }}>
                    {visualEvidence.caption}
                  </h3>
                </div>
                <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                  <Badge text={visualEvidence.evidenceId} color="purple" />
                  <Badge text={`MASK IOU: ${visualEvidence.iouConfidence} (VISUAL ONLY)`} color="muted" />
                  <button
                    type="button"
                    className="mask-toggle-btn"
                    onClick={() => setShowSamMask((prev) => !prev)}
                  >
                    {showSamMask ? "◉ Hide SAM 3.1 Segmentation Mask" : "◎ Show SAM 3.1 Segmentation Mask"}
                  </button>
                </div>
              </div>

              <div className="sam-canvas-grid">
                <div className={`sam-visual-stage ${showSamMask ? "mask-active" : ""}`}>
                  <div className="sam-hud-bar">
                    <span className="sam-coord-tag">SAM-3.1 BBOX {visualEvidence.bboxCoords}</span>
                    <span className="sam-coord-tag">PROVENANCE: VISUAL_REGION_ISOLATION</span>
                  </div>

                  <svg
                    viewBox="0 0 520 175"
                    className="sam-svg-blueprint"
                    role="img"
                    aria-label="SAM 3.1 visual evidence comparison canvas"
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
                      rx="3"
                      fill="rgba(255,255,255,0.04)"
                      stroke="rgba(255,255,255,0.18)"
                    />
                    <text x="26" y="36" fill="#9da79b" fontSize="9" fontFamily="monospace" letterSpacing="1">
                      POLICY v1 ARTIFACT REGION
                    </text>
                    <text x="26" y="62" fill="#e8eee6" fontSize="11" fontFamily="Georgia, serif">
                      {visualEvidence.olderVisualNote.slice(0, 42)}
                    </text>
                    <text x="26" y="78" fill="#a5b5ac" fontSize="10" fontFamily="Georgia, serif">
                      {visualEvidence.olderVisualNote.slice(42)}
                    </text>

                    <rect
                      x="271"
                      y="16"
                      width="235"
                      height="142"
                      rx="3"
                      fill="rgba(255,255,255,0.04)"
                      stroke="rgba(255,255,255,0.18)"
                    />
                    <text x="283" y="36" fill="#68b08e" fontSize="9" fontFamily="monospace" letterSpacing="1">
                      POLICY v2 ARTIFACT REGION
                    </text>
                    <text x="283" y="62" fill="#e8eee6" fontSize="11" fontFamily="Georgia, serif">
                      {visualEvidence.newerVisualNote.slice(0, 42)}
                    </text>
                    <text x="283" y="78" fill="#a5b5ac" fontSize="10" fontFamily="Georgia, serif">
                      {visualEvidence.newerVisualNote.slice(42)}
                    </text>

                    {showSamMask && (
                      <g>
                        <rect
                          x="24"
                          y="95"
                          width="215"
                          height="48"
                          rx="2"
                          fill="rgba(168, 85, 247, 0.24)"
                          stroke="#c084fc"
                          strokeWidth="1.5"
                          strokeDasharray="4 2"
                        />
                        <circle cx="24" cy="95" r="3" fill="#e9d5ff" />
                        <circle cx="239" cy="143" r="3" fill="#e9d5ff" />
                        <text x="34" y="116" fill="#f3e8ff" fontSize="9.5" fontFamily="monospace" fontWeight="bold">
                          MASK A · {visualEvidence.v1Highlight}
                        </text>
                        <text x="34" y="131" fill="#d8b4fe" fontSize="8.5" fontFamily="monospace">
                          SAM 3.1 Segmented · {visualEvidence.iouConfidence}
                        </text>

                        <rect
                          x="281"
                          y="95"
                          width="215"
                          height="48"
                          rx="2"
                          fill="rgba(249, 115, 22, 0.24)"
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
                    <div className="sam-mask-overlay" aria-label="SAM 3.1 segmented region">
                      <span>{visualEvidence.maskRegionLabel}</span>
                    </div>
                  )}
                </div>

                <div style={{ display: "grid", gap: 10, alignContent: "start" }}>
                  <div>
                    <span style={labelStyle}>POLICY-SPECIFIC VISUAL TIE-IN</span>
                    <p style={{ fontSize: 12, color: "#37443c", lineHeight: 1.6, margin: 0 }}>
                      {visualEvidence.policyTieIn}
                    </p>
                  </div>
                  <div
                    style={{
                      background: "#f3ecdf",
                      border: "1px solid #e8d4b8",
                      padding: "10px 12px",
                      borderRadius: 2,
                      fontSize: 10.5,
                      color: "#8a5c20",
                      lineHeight: 1.5,
                    }}
                  >
                    <b>Transparency Boundary:</b> Model segmentation confidence ({visualEvidence.iouConfidence})
                    measures pixel boundary localization only — it is strictly distinguished from policy evidence
                    verification (<code>semantic_support: NOT_VERIFIED</code>).
                  </div>
                </div>
              </div>
            </div>

            <SectionHeading
              num="04 — REVIEWER CHALLENGE"
              title="Multi-turn department applicability challenge"
            />

            <div style={card}>
              <div style={{ display: "grid", gap: 14 }}>
                <p style={{ fontSize: 13, color: "#57645b", lineHeight: 1.65, margin: 0 }}>
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
                    gap: 12,
                    alignItems: "center",
                    padding: "14px 16px",
                    background: "#f4f3ee",
                    borderRadius: 2,
                    border: "1px solid #e1e0d8",
                  }}
                >
                  <label htmlFor="challenge-dept-select" style={{ ...labelStyle, marginBottom: 0 }}>
                    TARGET DEPARTMENT:
                  </label>
                  <select
                    id="challenge-dept-select"
                    aria-label="Select target department to challenge"
                    value={selectedDept}
                    onChange={(e) => setSelectedDept(e.target.value)}
                    style={{
                      fontFamily: "ui-monospace,monospace",
                      fontSize: 12,
                      color: "#27322f",
                      border: "1px solid #c7ccc4",
                      background: "#fff",
                      padding: "7px 12px",
                      borderRadius: 2,
                      cursor: "pointer",
                      minWidth: 180,
                    }}
                  >
                    {(SCENARIO_DEPARTMENTS[selectedScenarioId] || ["HOUSEKEEPING"]).map((d) => (
                      <option key={d} value={d}>
                        {d}
                      </option>
                    ))}
                  </select>

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

                {challenge && (
                  <div
                    role="region"
                    aria-live="polite"
                    aria-label="Challenge recomputation results"
                    style={{ display: "grid", gap: 18, marginTop: 6 }}
                  >
                    <div className="challenge-comparison-grid">
                      <div
                        style={{
                          background: "#eeede6",
                          border: "1px solid #e1e0d8",
                          borderRadius: 2,
                          padding: "14px 16px",
                        }}
                      >
                        <SectionKicker>BEFORE CHALLENGE</SectionKicker>
                        <p
                          style={{
                            fontFamily: "Georgia,'Times New Roman',serif",
                            fontSize: 18,
                            fontWeight: 500,
                            color: "#285f4d",
                            margin: "4px 0",
                          }}
                        >
                          {scenario.proposed_relation}
                        </p>
                        <Badge text="PROPOSAL_ONLY" color="muted" />
                      </div>

                      <div
                        style={{
                          background: "#f3ecdf",
                          border: "1px solid #e8d4b8",
                          borderRadius: 2,
                          padding: "14px 16px",
                        }}
                      >
                        <SectionKicker>
                          AFTER CHALLENGE ({challenge.challenge.target_department})
                        </SectionKicker>
                        <p
                          style={{
                            fontFamily: "Georgia,'Times New Roman',serif",
                            fontSize: 18,
                            fontWeight: 500,
                            color: "#b45c37",
                            margin: "4px 0",
                          }}
                        >
                          {challenge.recomputed_proposal.proposed_relation}
                        </p>
                        <Badge text={challenge.recomputed_proposal.status} color="orange" />
                      </div>
                    </div>

                    <div style={{ display: "flex", flexWrap: "wrap", gap: 8, alignItems: "center" }}>
                      <span style={{ fontSize: 12, color: "#57645b" }}>Applicability status:</span>
                      <Badge text={challenge.applicability_audit.applicability_status} color="orange" />
                      <span style={{ fontSize: 12, color: "#57645b", marginLeft: 10 }}>
                        Contract enforcement:
                      </span>
                      <Badge
                        text={`one_sided_change_rejected: ${challenge.contract_enforcement.one_sided_change_rejected}`}
                        color={challenge.contract_enforcement.one_sided_change_rejected ? "review" : "muted"}
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
                        background: "#e8eee6",
                        border: "1px solid #d5e0d4",
                        borderRadius: 2,
                        padding: "10px 14px",
                        fontSize: 11,
                        color: "#315b47",
                        lineHeight: 1.6,
                      }}
                    >
                      <b>Contract enforcement:</b> {challenge.contract_enforcement.explanation}
                    </div>

                    <div
                      style={{
                        background: "#e3ede7",
                        border: "1px solid #c5d9cc",
                        borderRadius: 2,
                        padding: "12px 16px",
                        fontSize: 12,
                        color: "#285f4d",
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
                padding: "12px 16px",
                background: "#f4f3ee",
                border: "1px solid #d5dad1",
                borderRadius: 2,
                fontSize: 11,
                color: "#57645b",
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
                gap: 12,
                marginBottom: 16,
                padding: "10px 14px",
                background: "#fbfaf6",
                border: "1px solid #e1e0d8",
                borderRadius: 2,
              }}
            >
              <div style={{ display: "flex", gap: 18, flexWrap: "wrap", alignItems: "center" }}>
                <div>
                  <span style={labelStyle}>SESSION ID</span>
                  <span style={{ fontFamily: "ui-monospace,monospace", fontSize: 11, color: "#27322f" }}>
                    {sessionId ? `${sessionId.slice(0, 8)}…${sessionId.slice(-4)}` : "—"}
                  </span>
                </div>
                <div>
                  <span style={labelStyle}>CREATED AT (ISO)</span>
                  <span style={{ fontFamily: "ui-monospace,monospace", fontSize: 10, color: "#69756b" }}>
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
                style={{ fontSize: 11 }}
              >
                {resetting ? "Resetting…" : "Start New Investigation"} <span>↺</span>
              </button>
            </div>

            <ol
              style={{
                listStyle: "none",
                margin: "8px 0 0",
                padding: "0 0 0 8px",
                borderLeft: "1px solid #cfd4ca",
              }}
            >
              <li style={{ position: "relative", padding: "0 0 22px 22px" }}>
                <span
                  style={{
                    position: "absolute",
                    left: -5,
                    top: 3,
                    width: 9,
                    height: 9,
                    background: "#668672",
                    border: "2px solid #f4f3ee",
                    borderRadius: "50%",
                    boxShadow: "0 0 0 1px #668672",
                    display: "block",
                  }}
                />
                <div>
                  <div
                    style={{
                      display: "flex",
                      justifyContent: "space-between",
                      gap: 12,
                      alignItems: "center",
                    }}
                  >
                    <b style={{ fontSize: 11, color: "#285f4d" }}>
                      Baseline scenario loaded — initial proposal established
                    </b>
                    <Badge text="BASELINE" color="green" />
                  </div>
                  <p
                    style={{
                      fontFamily: "ui-monospace,monospace",
                      fontSize: 10,
                      color: "#69756b",
                      margin: "5px 0 0",
                    }}
                  >
                    Scenario: {selectedScenarioId} · Proposed relation: {scenario.proposed_relation} · Status:{" "}
                    {scenario.status} · Core: {scenario.core_classification}
                  </p>
                </div>
              </li>

              {historyEvents.length === 0 && (
                <li style={{ position: "relative", padding: "0 0 16px 22px" }}>
                  <span
                    style={{
                      position: "absolute",
                      left: -4,
                      top: 4,
                      width: 7,
                      height: 7,
                      background: "#e1e0d8",
                      border: "1px solid #9da79b",
                      borderRadius: "50%",
                      display: "block",
                    }}
                  />
                  <div
                    style={{
                      padding: "10px 14px",
                      background: "#faf9f4",
                      border: "1px dashed #d5dad1",
                      borderRadius: 2,
                      fontSize: 11,
                      color: "#758078",
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
                <li key={evt.sequence_number} style={{ position: "relative", padding: "0 0 24px 22px" }}>
                  <span
                    style={{
                      position: "absolute",
                      left: -5,
                      top: 3,
                      width: 9,
                      height: 9,
                      background: "#b45c37",
                      border: "2px solid #f4f3ee",
                      borderRadius: "50%",
                      boxShadow: "0 0 0 1px #b45c37",
                      display: "block",
                    }}
                  />
                  <div
                    style={{
                      display: "grid",
                      gap: 8,
                      background: "#fbfaf6",
                      border: "1px solid #e3e2da",
                      borderRadius: 2,
                      padding: "12px 16px",
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
                      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                        <Badge text={`ENTRY #${evt.sequence_number}`} color="orange" />
                        <b style={{ fontSize: 12, color: "#27322f" }}>
                          Reviewer Challenge: {evt.target_department} ({evt.target_side})
                        </b>
                      </div>
                      <span style={{ fontFamily: "ui-monospace,monospace", fontSize: 9, color: "#858c84" }}>
                        {evt.timestamp_iso}
                      </span>
                    </div>

                    <div style={{ display: "flex", flexWrap: "wrap", gap: 8, alignItems: "center" }}>
                      <span style={{ fontSize: 11, color: "#57645b" }}>Applicability:</span>
                      <Badge text={evt.applicability_status} color="orange" />
                      <span style={{ fontSize: 11, color: "#57645b", marginLeft: 6 }}>Relation shift:</span>
                      <Badge text={`${evt.initial_relation} → ${evt.recomputed_relation}`} color="review" />
                      <span style={{ fontSize: 11, color: "#57645b", marginLeft: 6 }}>Core classification:</span>
                      <Badge text={evt.core_classification} color="orange" />
                      <Badge
                        text={`contract_enforced: ${evt.contract_enforced}`}
                        color={evt.contract_enforced ? "green" : "muted"}
                      />
                    </div>

                    <div>
                      <span style={labelStyle}>UNCERTAINTY REASONS</span>
                      <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                        {evt.uncertainty_reasons.map((r) => (
                          <Badge key={r} text={r} color="muted" />
                        ))}
                      </div>
                    </div>

                    <p
                      style={{
                        margin: 0,
                        fontSize: 11,
                        color: "#4f5a52",
                        fontFamily: "Georgia,'Times New Roman',serif",
                        fontStyle: "italic",
                        lineHeight: 1.5,
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