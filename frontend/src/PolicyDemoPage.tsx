import { useCallback, useEffect, useState } from "react";

// ── Types ──────────────────────────────────────────────────────────────────

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

// ── Helpers ────────────────────────────────────────────────────────────────

async function demoApi<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/demo-api${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `Request failed (${res.status})`);
  }
  return res.json() as Promise<T>;
}

// ── Sub-components ─────────────────────────────────────────────────────────

function Badge({ text, color = "green" }: { text: string; color?: "green" | "orange" | "muted" | "review" }) {
  const bgMap: Record<string, string> = {
    green: "#e1ede7",
    orange: "#f4e8de",
    muted: "#eeeee8",
    review: "#f3ecdf",
  };
  const colorMap: Record<string, string> = {
    green: "#285f4d",
    orange: "#b45c37",
    muted: "#777f78",
    review: "#8a5c20",
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

// ── Main Page ──────────────────────────────────────────────────────────────

export default function PolicyDemoPage() {
  const [scenarios, setScenarios] = useState<ScenarioMeta[]>([]);
  const [selectedScenarioId, setSelectedScenarioId] = useState<string>("scheduling");
  const [scenario, setScenario] = useState<ScenarioResult | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [selectedDept, setSelectedDept] = useState<string>("HOUSEKEEPING");
  const [historyEvents, setHistoryEvents] = useState<AuditTrailEvent[]>([]);
  const [challenge, setChallenge] = useState<ChallengeResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [challenging, setChallenging] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [error, setError] = useState("");
  const [challengeError, setChallengeError] = useState("");

  const currentScenarioMeta = scenarios.find((s) => s.id === selectedScenarioId);

  // Load scenarios allowlist on mount
  useEffect(() => {
    demoApi<ScenarioMeta[]>("/scenarios")
      .then((data) => {
        setScenarios(data);
      })
      .catch(() => {
        // Fallback default list if API fails
        setScenarios([
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
            description: "Incompatible mandatory emblem placement rules (left lapel vs. right lapel) for Guest Relations Ambassadors.",
            default_challenge_department: "CONCIERGE",
          },
          {
            id: "lounge_access",
            title: "Executive Lounge Access — Scope / Time Difference",
            category: "Loyalty & Access",
            relation_type: "SCOPE_OR_TIME_DIFFERENCE",
            description: "Disjoint lounge access standards across distinct property collections and non-overlapping effective dates.",
            default_challenge_department: "VALET",
          },
        ]);
      });
  }, []);

  // Load selected scenario and initialize in-memory session on scenario change
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError("");
    setChallenge(null);
    setChallengeError("");
    setHistoryEvents([]);

    const depts = SCENARIO_DEPARTMENTS[selectedScenarioId] || ["HOUSEKEEPING"];
    setSelectedDept(depts[0]);

    Promise.all([
      demoApi<ScenarioResult>(`/scenario?id=${selectedScenarioId}`),
      demoApi<{ session_id: string; scenario_id: string; created_at: string }>("/session/new", {
        method: "POST",
        body: JSON.stringify({ scenario_id: selectedScenarioId }),
      }),
    ])
      .then(([scenarioData, sessionData]) => {
        if (cancelled) return;
        setScenario(scenarioData);
        setSessionId(sessionData.session_id);
        setError("");
      })
      .catch((e: Error) => {
        if (cancelled) return;
        setError(e.message);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [selectedScenarioId]);

  const runChallenge = useCallback(async () => {
    if (!scenario) return;
    setChallenging(true);
    setChallengeError("");
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
        const historyData = await demoApi<{ events: AuditTrailEvent[] }>(
          `/session/${sessionId}/history`
        );
        setHistoryEvents(historyData.events);
      }
    } catch (e: unknown) {
      setChallengeError((e as Error).message);
    } finally {
      setChallenging(false);
    }
  }, [scenario, selectedDept, selectedScenarioId, sessionId]);

  const startNewInvestigation = useCallback(async () => {
    if (!sessionId) return;
    setResetting(true);
    setChallengeError("");
    try {
      await demoApi<{ session_id: string; scenario_id: string; event_count: number }>(
        `/session/${sessionId}/reset`,
        {
          method: "POST",
          body: JSON.stringify({ scenario_id: selectedScenarioId }),
        }
      );
      setChallenge(null);
      setHistoryEvents([]);
      const depts = SCENARIO_DEPARTMENTS[selectedScenarioId] || ["HOUSEKEEPING"];
      setSelectedDept(depts[0]);
    } catch (e: unknown) {
      setChallengeError((e as Error).message);
    } finally {
      setResetting(false);
    }
  }, [sessionId, selectedScenarioId]);

  // ── Layout constants ──────────────────────────────────────────────────────

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

  // ── Render ────────────────────────────────────────────────────────────────

  return (
    <div className="shell">
      {/* ── Header (mirrors App.tsx topbar) ──────────────────────────────── */}
      <header className="topbar">
        <a className="brand" href="#" aria-label="Story Connect home">
          <span className="brand-mark">S</span>
          <span>
            STORY <i>CONNECT</i>
          </span>
        </a>
        <div className="top-context">
          <span className="pulse" /> POLICY DEMO <span className="divider">/</span> EVIDENCE
          INVESTIGATOR
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 20 }}>
          <a
            href="#"
            style={{
              fontFamily: "ui-monospace,monospace",
              fontSize: 10,
              letterSpacing: "0.08em",
              color: "#285f4d",
              textDecoration: "none",
            }}
          >
            ← Back to Investigator
          </a>
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
        {/* ── Synthetic banner ─────────────────────────────────────────────── */}
        <div className="eyebrow" style={{ marginBottom: 20 }}>
          <span>FIELD NOTE 02</span>
          <span className="line" />
          <span>POLICY EVIDENCE DEMO</span>
        </div>
        <section className="intro">
          <div>
            <h1>
              Policy versions,
              <br />
              <em>evidence-first.</em>
            </h1>
            <p>
              Trace how scheduling policy changed between v1 and v2, verify citation provenance
              locally, then challenge department applicability and observe honest recomputation to
              INCONCLUSIVE.
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

        <aside className="synthetic-banner">
          <span className="banner-icon">✳</span>
          <div>
            <strong>Synthetic demo · offline only · human review required</strong>
            <span>
              All policy data is fictional. Evidence demonstrates local citation provenance only —
              not semantic correctness or legal force.
            </span>
          </div>
          <span className="banner-tag">LOCAL ONLY</span>
        </aside>

        {/* ── Scenario Selector ────────────────────────────────────────────── */}
        <div style={{ ...card, marginTop: 24, padding: "16px 20px" }}>
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              flexWrap: "wrap",
              gap: 12,
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
                Switch between synthetic luxury hotel scenarios to evaluate distinct policy relations through the evidence engine.
              </p>
            </div>
            <div style={{ minWidth: 280 }}>
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
                  padding: "8px 12px",
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
          {currentScenarioMeta && (
            <div
              style={{
                marginTop: 10,
                display: "flex",
                gap: 8,
                alignItems: "center",
                flexWrap: "wrap",
              }}
            >
              <span
                style={{
                  fontSize: 11,
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

        {/* ── Loading / error ───────────────────────────────────────────────── */}
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
        {error && (
          <div className="error" role="alert" style={{ marginTop: 20 }}>
            {error}
          </div>
        )}

        {scenario && (
          <>
            {/* ──────────────────────────────────────────────────────────────
                SECTION 1: Policy Versions Panel
            ────────────────────────────────────────────────────────────── */}
            <SectionHeading
              num="01 — POLICY VERSIONS"
              title={
                currentScenarioMeta
                  ? `The Grand Luminary Hotel — ${currentScenarioMeta.title}`
                  : "The Grand Luminary Hotel — Policy Versions"
              }
            />

            <div className="policy-versions-grid">
              {/* V1 Card */}
              {(() => {
                const older = scenario.provenance_details.find((d) => d.side === "OLDER");
                const isLounge = scenario.comparison_id.includes("lounge");
                const olderDates = isLounge ? "2022-01-01 → 2024-01-01" : "2024-01-01 → 2027-01-01";
                return (
                  <div style={{ ...card, borderTop: "3px solid #9da79b" }}>
                    <SectionKicker>POLICY v1 — OLDER BASELINE</SectionKicker>
                    <div style={{ display: "grid", gap: 10 }}>
                      <div>
                        <span style={labelStyle}>VERSION ID</span>
                        <p style={valueStyle}>v1</p>
                      </div>
                      <div>
                        <span style={labelStyle}>EFFECTIVE DATES</span>
                        <p style={valueStyle}>{olderDates}</p>
                      </div>
                      <div>
                        <span style={labelStyle}>DOCUMENT ID</span>
                        <p style={{ ...valueStyle, fontFamily: "ui-monospace,monospace", fontSize: 11 }}>
                          {scenario.comparison_id.replace("cmp-", "").replace("-001", "").replace("-002", "").replace("-003", "")}
                        </p>
                      </div>
                      <div>
                        <span style={labelStyle}>PASSAGE ID</span>
                        <p
                          style={{
                            fontFamily: "ui-monospace,monospace",
                            fontSize: 10,
                            color: "#758078",
                            margin: 0,
                          }}
                        >
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

              {/* V2 Card */}
              {(() => {
                const newer = scenario.provenance_details.find((d) => d.side === "NEWER");
                const isLounge = scenario.comparison_id.includes("lounge");
                const newerDates = isLounge ? "2025-01-01 → 2028-01-01" : "2026-01-01 → 2027-01-01";
                return (
                  <div style={{ ...card, borderTop: "3px solid #285f4d" }}>
                    <SectionKicker>POLICY v2 — NEWER REVISION</SectionKicker>
                    <div style={{ display: "grid", gap: 10 }}>
                      <div>
                        <span style={labelStyle}>VERSION ID</span>
                        <p style={valueStyle}>v2</p>
                      </div>
                      <div>
                        <span style={labelStyle}>EFFECTIVE DATES</span>
                        <p style={valueStyle}>{newerDates}</p>
                      </div>
                      <div>
                        <span style={labelStyle}>DOCUMENT ID</span>
                        <p style={{ ...valueStyle, fontFamily: "ui-monospace,monospace", fontSize: 11 }}>
                          {scenario.comparison_id.replace("cmp-", "").replace("-001", "").replace("-002", "").replace("-003", "")}
                        </p>
                      </div>
                      <div>
                        <span style={labelStyle}>PASSAGE ID</span>
                        <p
                          style={{
                            fontFamily: "ui-monospace,monospace",
                            fontSize: 10,
                            color: "#758078",
                            margin: 0,
                          }}
                        >
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

            {/* ──────────────────────────────────────────────────────────────
                SECTION 2: Proposal vs Assessment Panel
            ────────────────────────────────────────────────────────────── */}
            <SectionHeading num="02 — PROPOSAL vs ASSESSMENT" title="What the system proposed — and what it can verify" />

            <div style={{ ...card, display: "grid", gap: 18 }}>
              <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 14 }}>
                <div>
                  <span style={labelStyle}>PROPOSED RELATION</span>
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
                <div style={{ marginLeft: 28 }}>
                  <span style={labelStyle}>SYSTEM ASSESSMENT</span>
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
              </div>

              <div style={{ display: "flex", flexWrap: "wrap", gap: 8, alignItems: "center" }}>
                <Badge text={scenario.status} color="muted" />
                <Badge text={scenario.semantic_support} color="orange" />
                {scenario.human_review_required && (
                  <Badge text="HUMAN REVIEW REQUIRED" color="review" />
                )}
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
                <b>Notice:</b> This proposal has not been verified. Quote matching establishes text
                provenance only — not semantic correctness or department applicability.
              </div>

              <div>
                <span style={labelStyle}>REASONING</span>
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

            {/* ──────────────────────────────────────────────────────────────
                SECTION 3: Evidence Inspector
            ────────────────────────────────────────────────────────────── */}
            <SectionHeading num="03 — EVIDENCE INSPECTOR" title="Citation provenance — locally derived" />

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
              <b>Provenance verified locally — not by model.</b>{" "}
              {scenario.provenance_limitation_notice}
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
                      <span
                        style={{
                          fontFamily: "ui-monospace,monospace",
                          fontSize: 10,
                          color: "#496a58",
                        }}
                      >
                        {detail.passage_id}
                      </span>
                    </div>
                    <Badge text={detail.verified_locally ? "LOCALLY VERIFIED" : "UNVERIFIED"} color="green" />
                  </div>

                  <div className="citation-offsets-grid">
                    <div>
                      <span style={labelStyle}>START CP</span>
                      <p style={{ fontFamily: "ui-monospace,monospace", fontSize: 11, margin: 0 }}>
                        {detail.start_cp}
                      </p>
                    </div>
                    <div>
                      <span style={labelStyle}>END CP</span>
                      <p style={{ fontFamily: "ui-monospace,monospace", fontSize: 11, margin: 0 }}>
                        {detail.end_cp}
                      </p>
                    </div>
                    <div>
                      <span style={labelStyle}>SOURCE SHA256</span>
                      <p style={{ fontFamily: "ui-monospace,monospace", fontSize: 11, margin: 0 }}>
                        {detail.source_sha256.slice(0, 8)}…
                      </p>
                    </div>
                  </div>

                  <div>
                    <span style={labelStyle}>EXACT QUOTE</span>
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

            {/* ──────────────────────────────────────────────────────────────
                SECTION 4: Reviewer Challenge Panel
            ────────────────────────────────────────────────────────────── */}
            <SectionHeading
              num="04 — REVIEWER CHALLENGE"
              title="Multi-turn department applicability challenge"
            />

            <div style={card}>
              <div style={{ display: "grid", gap: 14 }}>
                <p style={{ fontSize: 13, color: "#57645b", lineHeight: 1.65, margin: 0 }}>
                  A reviewer questions whether the v1 baseline requirement applied to a specific
                  department. Select an operational department below to submit a challenge and
                  observe honest recomputation to <strong>INCONCLUSIVE</strong>. Consecutive challenges
                  are recorded in the session audit trail.
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
                    {/* Before / After comparison */}
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

                    {/* Applicability audit */}
                    <div style={{ display: "flex", flexWrap: "wrap", gap: 8, alignItems: "center" }}>
                      <span style={{ fontSize: 12, color: "#57645b" }}>Applicability status:</span>
                      <Badge
                        text={`${challenge.applicability_audit.applicability_status}`}
                        color="orange"
                      />
                      <span style={{ fontSize: 12, color: "#57645b", marginLeft: 10 }}>
                        Contract enforcement:
                      </span>
                      <Badge
                        text={`one_sided_change_rejected: ${challenge.contract_enforcement.one_sided_change_rejected}`}
                        color={
                          challenge.contract_enforcement.one_sided_change_rejected
                            ? "review"
                            : "muted"
                        }
                      />
                    </div>

                    {/* Uncertainty reasons */}
                    <div>
                      <span style={labelStyle}>UNCERTAINTY REASONS (RECOMPUTED)</span>
                      <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 4 }}>
                        {challenge.recomputed_core_result.uncertainty_reasons.map((r) => (
                          <Badge key={r} text={r} color="muted" />
                        ))}
                      </div>
                    </div>

                    {/* Contract explanation */}
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

                    {/* Differentiator takeaway */}
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

            {/* ──────────────────────────────────────────────────────────────
                SECTION 5: Audit Trail
            ────────────────────────────────────────────────────────────── */}
            <SectionHeading
              num="05 — AUDIT TRAIL"
              title="Investigation timeline (in-memory audit log)"
            />

            {/* Ephemeral in-memory notice */}
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
              <b>In-Memory Audit Notice:</b> This investigation session maintains an in-memory,
              append-only audit log. The trail is ephemeral (held only in server memory for this
              active session) and is reset when starting a new investigation, switching scenarios, or
              restarting the process. No database persistence or local storage is used.
            </div>

            {/* Session Status & Reset Strip */}
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
              <div style={{ display: "flex", gap: 14, flexWrap: "wrap", alignItems: "center" }}>
                <div>
                  <span style={labelStyle}>SESSION ID</span>
                  <span
                    style={{
                      fontFamily: "ui-monospace,monospace",
                      fontSize: 11,
                      color: "#27322f",
                    }}
                  >
                    {sessionId ? `${sessionId.slice(0, 8)}…${sessionId.slice(-4)}` : "—"}
                  </span>
                </div>
                <div>
                  <span style={labelStyle}>ACTIVE SCENARIO</span>
                  <Badge text={selectedScenarioId} color="green" />
                </div>
                <div>
                  <span style={labelStyle}>CHALLENGES RECORDED</span>
                  <Badge
                    text={`${historyEvents.length}`}
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
              {/* Event 0: Baseline investigation */}
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
                    Scenario: {selectedScenarioId} · Proposed relation:{" "}
                    {scenario.proposed_relation} · Status: {scenario.status} · Core:{" "}
                    {scenario.core_classification}
                  </p>
                </div>
              </li>

              {/* Empty state when no challenges have been run yet */}
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
                    No challenges recorded yet in this session. The baseline investigation proposal
                    remains uncontradicted. Select a department in Section 04 and submit a challenge
                    to record an immutable audit entry.
                  </div>
                </li>
              )}

              {/* Dynamic consecutive challenges from session manager */}
              {historyEvents.map((evt) => (
                <li
                  key={evt.sequence_number}
                  style={{ position: "relative", padding: "0 0 24px 22px" }}
                >
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
                      <span
                        style={{
                          fontFamily: "ui-monospace,monospace",
                          fontSize: 9,
                          color: "#858c84",
                        }}
                      >
                        {evt.timestamp_iso}
                      </span>
                    </div>

                    <div style={{ display: "flex", flexWrap: "wrap", gap: 8, alignItems: "center" }}>
                      <span style={{ fontSize: 11, color: "#57645b" }}>Applicability:</span>
                      <Badge text={evt.applicability_status} color="orange" />
                      <span style={{ fontSize: 11, color: "#57645b", marginLeft: 6 }}>
                        Relation shift:
                      </span>
                      <Badge
                        text={`${evt.initial_relation} → ${evt.recomputed_relation}`}
                        color="review"
                      />
                      <span style={{ fontSize: 11, color: "#57645b", marginLeft: 6 }}>
                        Core classification:
                      </span>
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
