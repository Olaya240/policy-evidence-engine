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

type EvidenceDispositionItem = {
  source_record_id?: string;
  record_id?: string;
  codes?: string[];
  disposition?: string;
  reason?: string;
};

type AdvisoryCoverageCategory = {
  category?: string;
  category_id?: string;
  id?: string;
  name?: string;
  label?: string;
  status?: "COVERED" | "NOT_COVERED" | string;
  state?: "COVERED" | "NOT_COVERED" | string;
  covered?: boolean;
  details?: string;
  description?: string;
  matching_evidence_ids?: string[];
  fresh_accepted_support_ids?: string[];
  fresh_accepted_contradiction_ids?: string[];
  independent_source_groups?: string[];
  source_groups?: string[];
  source_record_ids?: string[];
};

type ExplanationTrace = {
  status_rule_id?: string;
  confidence_rule_id?: string;
  evidence_dispositions?:
    | Record<string, { codes?: string[]; disposition?: string; reason?: string } | string[] | string>
    | EvidenceDispositionItem[];
  advisory_coverage?: {
    categories?:
      | AdvisoryCoverageCategory[]
      | Record<string, AdvisoryCoverageCategory | "COVERED" | "NOT_COVERED" | string>;
    note?: string;
    disclaimer?: string;
  };
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

type WorkspaceSection = "overview" | "investigations" | "library" | "history";

const HYPOTHESES: Record<string, string> = {
  CHECKLIST_UNAVAILABLE: "Checklist unavailable",
  TRAINING_GAP: "Training gap",
  STAFFING_CONSTRAINTS: "Staffing constraints",
  PMS_SYSTEM_ISSUE: "PMS system issue",
  TIME_PRESSURE: "Time pressure",
};

// P0.1: Exact 4 canonical presets and questions expected by the backend
const PRESETS = [
  {
    preset_id: "handover_omissions",
    label: "Recurring handover omissions",
    question: "Did time pressure contribute to recurring handover omissions?",
    description: "Evaluate whether shift changeover time pressure and concurrent operational factors drove omitted guest requests.",
  },
  {
    preset_id: "checklist_access",
    label: "Checklist access",
    question: "Did checklist availability contribute to missing handover information?",
    description: "Assess whether template locks or missing checklist access prevented structured shift handover logging.",
  },
  {
    preset_id: "desk_coverage",
    label: "Desk coverage",
    question: "Did staffing constraints affect how guest requests were handed over?",
    description: "Examine single-agent desk coverage and staffing bottlenecks across front office and housekeeping shifts.",
  },
  {
    preset_id: "property_system",
    label: "Property system",
    question: "Did property system interruptions affect handover note completion?",
    description: "Inspect PMS sync telemetry and terminal availability during shift handover windows.",
  },
];

// Explicit opt-in demo fixtures (NEVER loaded silently on backend errors)
const EXPLICIT_DEMO_RECORDS: RecordItem[] = [
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

const EXPLICIT_DEMO_INVESTIGATION: Investigation = {
  id: "inv-explicit-demo-01",
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
        evidence_dispositions: [
          {
            source_record_id: "REC-101",
            codes: ["ACCEPTED_SUPPORT", "EXACT_SUBSTRING_VERIFIED", "ACTIVE_IN_SCORING"],
          },
        ],
        advisory_coverage: {
          categories: [
            {
              category: "SHIFT_LOG_OBSERVATION",
              status: "COVERED",
              matching_evidence_ids: ["REC-101"],
              fresh_accepted_support_ids: ["REC-101"],
              fresh_accepted_contradiction_ids: [],
              independent_source_groups: ["shift_logs"],
              details: "Direct shift log record REC-101 present",
            },
            {
              category: "PAPER_FALLBACK_VERIFICATION",
              status: "NOT_COVERED",
              matching_evidence_ids: [],
              fresh_accepted_support_ids: [],
              fresh_accepted_contradiction_ids: [],
              independent_source_groups: [],
              details: "Desk B physical binder not ingested",
            },
          ],
        },
        rules_triggered: [
          {
            rule_id: "RULE_EXACT_SUBSTRING_MATCH",
            description: "Quoted text verified as exact substring of source REC-101.",
            applied: true,
            weight: 0.8,
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
        evidence_dispositions: [
          {
            source_record_id: "REC-102",
            codes: ["ACCEPTED_SUPPORT", "CONFLICT_PRESENT_IN_CLAIM"],
          },
        ],
        advisory_coverage: {
          categories: [
            {
              category: "TRAINING_COMPLETION_LOG",
              status: "COVERED",
              matching_evidence_ids: ["REC-102"],
              fresh_accepted_support_ids: ["REC-102"],
              fresh_accepted_contradiction_ids: [],
              independent_source_groups: ["training_records"],
            },
            {
              category: "ROSTER_PAIRING_ASSIGNMENT",
              status: "NOT_COVERED",
              matching_evidence_ids: [],
              fresh_accepted_support_ids: [],
              fresh_accepted_contradiction_ids: [],
              independent_source_groups: [],
            },
          ],
        },
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
        evidence_dispositions: [
          {
            source_record_id: "REC-104",
            codes: ["ACCEPTED_SUPPORT", "SINGLE_SOURCE_GROUP"],
          },
        ],
        advisory_coverage: {
          categories: [
            {
              category: "DESK_SHIFT_LOG",
              status: "COVERED",
              matching_evidence_ids: ["REC-104"],
              fresh_accepted_support_ids: ["REC-104"],
              fresh_accepted_contradiction_ids: [],
              independent_source_groups: ["shift_logs"],
            },
            {
              category: "DUTY_MANAGER_ROSTER",
              status: "NOT_COVERED",
              matching_evidence_ids: [],
              fresh_accepted_support_ids: [],
              fresh_accepted_contradiction_ids: [],
              independent_source_groups: [],
            },
          ],
        },
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
        evidence_dispositions: [
          {
            source_record_id: "REC-108",
            codes: ["DOWNGRADED_TO_NEUTRAL", "PHRASE_CUE_GUARD_TRIGGERED", "EXCLUDED_FROM_SUPPORT"],
          },
        ],
        advisory_coverage: {
          categories: [
            {
              category: "MORNING_AUDIT_TELEMETRY",
              status: "COVERED",
              matching_evidence_ids: ["REC-108"],
              fresh_accepted_support_ids: [],
              fresh_accepted_contradiction_ids: [],
              independent_source_groups: ["telemetry"],
            },
            {
              category: "AFTERNOON_HANDOVER_TELEMETRY",
              status: "NOT_COVERED",
              matching_evidence_ids: [],
              fresh_accepted_support_ids: [],
              fresh_accepted_contradiction_ids: [],
              independent_source_groups: [],
            },
          ],
        },
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
        evidence_dispositions: [
          {
            source_record_id: "REC-112",
            codes: ["ACCEPTED_SUPPORT", "TEMPORAL_OVERLAP_VERIFIED"],
          },
        ],
        advisory_coverage: {
          categories: [
            {
              category: "SHIFT_TRANSITION_TIMELINE",
              status: "COVERED",
              matching_evidence_ids: ["REC-112"],
              fresh_accepted_support_ids: ["REC-112"],
              fresh_accepted_contradiction_ids: [],
              independent_source_groups: ["shift_logs"],
            },
            {
              category: "LOBBY_QUEUE_SENSOR_LOG",
              status: "NOT_COVERED",
              matching_evidence_ids: [],
              fresh_accepted_support_ids: [],
              fresh_accepted_contradiction_ids: [],
              independent_source_groups: [],
            },
          ],
        },
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
  return `Backend request failed (HTTP ${status})`;
}

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`/api${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...init?.headers },
    });
  } catch (err) {
    throw new Error(
      `Cannot reach main backend at 127.0.0.1:8000 (/api${path}). Verify the FastAPI server is running. (${
        (err as Error).message
      })`
    );
  }
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

// P1.1: Parse evidence_dispositions supporting `codes: string[]` in both array and keyed-object shapes
function parseEvidenceDispositions(
  dispositions: ExplanationTrace["evidence_dispositions"]
): Array<{ recordKey: string; codes: string[]; note?: string }> {
  if (!dispositions) return [];

  if (Array.isArray(dispositions)) {
    return dispositions.map((item, idx) => {
      const recordKey = item.source_record_id || item.record_id || `EV-${idx + 1}`;
      const codes = Array.isArray(item.codes)
        ? item.codes.map(String)
        : item.disposition
        ? [String(item.disposition)]
        : [];
      return { recordKey, codes, note: item.reason };
    });
  }

  return Object.entries(dispositions).map(([key, val]) => {
    if (Array.isArray(val)) {
      return { recordKey: key, codes: val.map(String) };
    }
    if (val && typeof val === "object") {
      const obj = val as { codes?: unknown; disposition?: unknown; reason?: unknown };
      const codes = Array.isArray(obj.codes)
        ? obj.codes.map(String)
        : typeof obj.disposition === "string"
        ? [obj.disposition]
        : [];
      return {
        recordKey: key,
        codes,
        note: typeof obj.reason === "string" ? obj.reason : undefined,
      };
    }
    return { recordKey: key, codes: [String(val)] };
  });
}

// P1.2 & PDF Section 5C: Parse structured advisory_coverage.categories including matching/fresh IDs & source groups
function parseAdvisoryCoverageCategories(
  advisory: ExplanationTrace["advisory_coverage"]
): Array<{
  name: string;
  state: "COVERED" | "NOT_COVERED" | string;
  details?: string;
  matchingIds: string[];
  freshSupportIds: string[];
  freshContradictionIds: string[];
  independentGroups: string[];
}> {
  if (!advisory || !advisory.categories) return [];
  const raw = advisory.categories;

  const toStrArray = (v: unknown): string[] => (Array.isArray(v) ? v.map(String) : []);

  if (Array.isArray(raw)) {
    return raw.map((item, idx) => {
      const name = item.category || item.category_id || item.id || item.name || item.label || `CATEGORY_${idx + 1}`;
      const state =
        item.status ||
        item.state ||
        (typeof item.covered === "boolean" ? (item.covered ? "COVERED" : "NOT_COVERED") : "NOT_COVERED");
      return {
        name: String(name),
        state: String(state).toUpperCase(),
        details: item.details || item.description,
        matchingIds: toStrArray(item.matching_evidence_ids ?? item.source_record_ids),
        freshSupportIds: toStrArray(item.fresh_accepted_support_ids),
        freshContradictionIds: toStrArray(item.fresh_accepted_contradiction_ids),
        independentGroups: toStrArray(item.independent_source_groups ?? item.source_groups),
      };
    });
  }

  return Object.entries(raw).map(([key, val]) => {
    if (typeof val === "string") {
      return {
        name: key,
        state: val.toUpperCase(),
        matchingIds: [],
        freshSupportIds: [],
        freshContradictionIds: [],
        independentGroups: [],
      };
    }
    if (val && typeof val === "object") {
      const state =
        val.status ||
        val.state ||
        (typeof val.covered === "boolean" ? (val.covered ? "COVERED" : "NOT_COVERED") : "NOT_COVERED");
      return {
        name: val.category || val.category_id || val.id || val.name || val.label || key,
        state: String(state).toUpperCase(),
        details: val.details || val.description,
        matchingIds: toStrArray(val.matching_evidence_ids ?? val.source_record_ids),
        freshSupportIds: toStrArray(val.fresh_accepted_support_ids),
        freshContradictionIds: toStrArray(val.fresh_accepted_contradiction_ids),
        independentGroups: toStrArray(val.independent_source_groups ?? val.source_groups),
      };
    }
    return {
      name: key,
      state: "NOT_COVERED",
      matchingIds: [],
      freshSupportIds: [],
      freshContradictionIds: [],
      independentGroups: [],
    };
  });
}

function App() {
  const [showDemo, setShowDemo] = useState(window.location.hash === "#/demo");
  const [activeSection, setActiveSection] = useState<WorkspaceSection>("investigations");
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
    beforeVersion: number;
    afterVersion: number;
    recomputedIds: string[];
    reason: string;
    disputedIds: string[];
  } | null>(null);
  const [inspectedHistoryVersion, setInspectedHistoryVersion] = useState<number | null>(null);
  const [expandedEvidenceKey, setExpandedEvidenceKey] = useState<string | null>(null);
  // Evidence Library search & filters (PDF Section 8)
  const [libraryQuery, setLibraryQuery] = useState("");
  const [libraryDeptFilter, setLibraryDeptFilter] = useState("ALL");
  const [libraryGroupFilter, setLibraryGroupFilter] = useState("ALL");
  const [expandedRecordId, setExpandedRecordId] = useState<string | null>(null);

  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  // P0.2: Explicit opt-in demo mode only — false by default, never activated silently
  const [explicitDemoMode, setExplicitDemoMode] = useState(false);

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

  const loadRecordsFromBackend = useCallback(() => {
    setError("");
    api<RecordItem[]>("/records")
      .then((data) => {
        setRecords(data);
        setExplicitDemoMode(false);
      })
      .catch((e: Error) => {
        // P0.2: No silent fallback to mock records. Clear records and surface error clearly.
        setRecords([]);
        setError(e.message);
      });
  }, []);

  useEffect(() => {
    loadRecordsFromBackend();
  }, [loadRecordsFromBackend]);

  function enableExplicitDemoMode() {
    setExplicitDemoMode(true);
    setError("");
    setRecords(EXPLICIT_DEMO_RECORDS);
    const chosen = PRESETS[selectedPresetIndex];
    const demoInv: Investigation = {
      ...EXPLICIT_DEMO_INVESTIGATION,
      question: chosen.question,
      preset_id: chosen.preset_id,
      created_at: new Date().toISOString(),
    };
    setInvestigation(demoInv);
    setSelectedId(demoInv.claims[0].id);
    setSourceId(demoInv.claims[0].dependencies[0] ?? "");
    setQuote(EXPLICIT_DEMO_RECORDS[0].text);
    setHistory([
      {
        version: 1,
        created_at: new Date().toISOString(),
        event: "CREATED",
        evidence_changes: [],
        recomputed_claim_ids: demoInv.claims.map((c) => c.hypothesis_id),
      },
    ]);
  }

  function exitExplicitDemoMode() {
    setExplicitDemoMode(false);
    setInvestigation(null);
    setHistory([]);
    setChange(null);
    setInspectedHistoryVersion(null);
    loadRecordsFromBackend();
  }

  const selected = useMemo(
    () => investigation?.claims.find((claim) => claim.id === selectedId) ?? null,
    [investigation, selectedId]
  );
  const chosenRecord = useMemo(() => records.find((record) => record.id === sourceId), [records, sourceId]);

  const inspectedHistoryEntry = useMemo(
    () => history.find((h) => h.version === inspectedHistoryVersion) ?? null,
    [history, inspectedHistoryVersion]
  );

  // Dynamic Overview metrics strictly from real backend/state data (PDF Section 3)
  const statusCounts = useMemo(() => {
    if (!investigation) {
      return {
        supported: 0,
        partial: 0,
        contradicted: 0,
        insufficient: 0,
        disputed: 0,
        claimsUnderReview: 0,
      };
    }
    return {
      supported: investigation.claims.filter((c) => c.status === "SUPPORTED").length,
      partial: investigation.claims.filter((c) => c.status === "PARTIAL").length,
      contradicted: investigation.claims.filter((c) => c.status === "CONTRADICTED").length,
      insufficient: investigation.claims.filter((c) => c.status === "INSUFFICIENT").length,
      disputed: investigation.claims.reduce((acc, c) => acc + c.evidence.filter((e) => e.disputed).length, 0),
      claimsUnderReview: investigation.claims.filter(
        (c) => c.status !== "SUPPORTED" || c.evidence.some((e) => e.disputed || e.review_state === "UNVERIFIED")
      ).length,
    };
  }, [investigation]);

  const recentChallengesCount = useMemo(
    () => history.filter((h) => h.event !== "CREATED").length,
    [history]
  );

  // Source Independence groups for the currently selected claim (PDF Section 5D)
  const selectedSourceGroups = useMemo(() => {
    if (!selected) return [];
    const groups = new Set<string>();
    selected.evidence.forEach((ev) => {
      if (ev.source_group) groups.add(ev.source_group);
      else {
        const rec = records.find((r) => r.id === ev.source_record_id);
        if (rec?.source_group) groups.add(rec.source_group);
      }
    });
    return Array.from(groups);
  }, [selected, records]);

  // Evidence Library filters (PDF Section 8)
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
    setBusy(true);
    setError("");
    setChange(null);
    setInspectedHistoryVersion(null);
    const chosen = PRESETS[selectedPresetIndex];

    if (explicitDemoMode) {
      const demoInv: Investigation = {
        ...EXPLICIT_DEMO_INVESTIGATION,
        question: chosen.question,
        preset_id: chosen.preset_id,
        created_at: new Date().toISOString(),
      };
      setInvestigation(demoInv);
      setSelectedId(demoInv.claims[0].id);
      setSourceId(demoInv.claims[0].dependencies[0] ?? "");
      setQuote(EXPLICIT_DEMO_RECORDS[0].text);
      setHistory([
        {
          version: 1,
          created_at: new Date().toISOString(),
          event: "CREATED",
          evidence_changes: [],
          recomputed_claim_ids: demoInv.claims.map((c) => c.hypothesis_id),
        },
      ]);
      setBusy(false);
      return;
    }

    try {
      // P0.1: Send both preset_id and exact canonical question
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
    } catch (e) {
      // P0.2: Never fall back silently to mock data. Show visible error.
      setError((e as Error).message);
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
    const prevInvVersion = investigation.version;

    if (explicitDemoMode) {
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
          ...selected.explanation_trace,
          status_rule_id: "STATUS_DOWNGRADED_BY_DISPUTED_SOURCE",
          confidence_rule_id: "CONF_PENALTY_ACTIVE_CHALLENGE",
          evidence_dispositions: [
            {
              source_record_id: sourceId,
              codes: ["DISPUTED_BY_REVIEWER", "RETAINED_FOR_HUMAN_AUDIT", "WEIGHT_PENALIZED"],
            },
          ],
        },
      };
      const beforeMap: Record<string, Claim> = { [selected.id]: beforeFallback };
      const afterMap: Record<string, Claim> = { [selected.id]: afterClaim };
      setInvestigation({
        ...investigation,
        version: nextVersion,
        claims: investigation.claims.map((c) => (c.id === selected.id ? afterClaim : c)),
      });
      setChange({
        before: beforeFallback,
        after: afterClaim,
        beforeVersion: prevInvVersion,
        afterVersion: nextVersion,
        recomputedIds: [selected.hypothesis_id],
        reason: reason.trim(),
        disputedIds: updatedEvidence.filter((ev) => ev.disputed).map((ev) => ev.source_record_id),
      });
      setHistory((prev) => [
        ...prev,
        {
          version: nextVersion,
          created_at: new Date().toISOString(),
          event: "CHALLENGED",
          claim_id: selected.id,
          reason: reason.trim(),
          before: beforeMap,
          after: afterMap,
          evidence_changes: [sourceId],
          recomputed_claim_ids: [selected.hypothesis_id],
        },
      ]);
      setInspectedHistoryVersion(nextVersion);
      setReason("");
      setBusy(false);
      return;
    }

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
        const disputedIds = afterSnap.evidence.filter((e) => e.disputed).map((e) => e.source_record_id);
        const revNum = challengeRes.version ?? updatedInv.version;
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
      }
      setReason("");
    } catch (e) {
      // P0.2: Surface real backend challenge errors directly without silent mock fallback
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  function chooseSource(id: string) {
    setSourceId(id);
    const record = records.find((item) => item.id === id);
    setQuote(record?.text ?? "");
  }

  function scrollToSection(section: WorkspaceSection, elementId: string) {
    setActiveSection(section);
    const el = document.getElementById(elementId);
    if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  if (showDemo) return <PolicyDemoPage />;

  const parsedDispositions = parseEvidenceDispositions(selected?.explanation_trace?.evidence_dispositions);
  const parsedCoverageCategories = parseAdvisoryCoverageCategories(selected?.explanation_trace?.advisory_coverage);

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
          <span className="pulse" />{" "}
          {explicitDemoMode ? "EXPLICIT DEMO FIXTURE MODE (OPT-IN)" : "LIVE BACKEND · 127.0.0.1:8000"}{" "}
          <span className="divider">/</span> STORY CONNECT AI COPILOT
        </div>
        <div className="nav-actions">
          <div className="mode-switcher" role="navigation" aria-label="Primary application navigation">
            <button
              type="button"
              className={`mode-pill ${activeSection === "overview" ? "active" : ""}`}
              onClick={() => scrollToSection("overview", "section-overview")}
              style={{ border: 0, cursor: "pointer" }}
            >
              Overview
            </button>
            <button
              type="button"
              className={`mode-pill ${activeSection === "investigations" ? "active" : ""}`}
              onClick={() => scrollToSection("investigations", "section-investigations")}
              style={{ border: 0, cursor: "pointer" }}
            >
              Investigations
            </button>
            <button
              type="button"
              className={`mode-pill ${activeSection === "library" ? "active" : ""}`}
              onClick={() => scrollToSection("library", "section-library")}
              style={{ border: 0, cursor: "pointer" }}
            >
              Evidence Library ({records.length})
            </button>
            <button
              type="button"
              className={`mode-pill ${activeSection === "history" ? "active" : ""}`}
              onClick={() => scrollToSection("history", "section-history")}
              style={{ border: 0, cursor: "pointer" }}
            >
              Revision History ({history.length})
            </button>
            <a href="#/demo" className="mode-pill">
              Policy Demo Studio ↗
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
              Select Scenario → Start Investigation → Inspect Claims → Explore Evidence → Understand Decision Rules →
              Challenge Evidence → Review Reassessment → Inspect Revision History.
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

        {/* ── PDF Section 3: Overview Dashboard Summary Cards (Strictly Live Backend Data) ── */}
        <section id="section-overview" className="kpi-ribbon" aria-label="Overview dashboard metrics">
          <div className="kpi-tile">
            <span className="kpi-label">TOTAL RECORDS</span>
            <strong>{records.length}</strong>
            <small>{explicitDemoMode ? "Explicit Demo Corpus" : "Loaded from GET /api/records"}</small>
          </div>
          <div className="kpi-tile">
            <span className="kpi-label">ACTIVE INVESTIGATIONS</span>
            <strong>{investigation ? `1 (Rev v${investigation.version})` : "0"}</strong>
            <small>{investigation ? `Preset: ${investigation.preset_id ?? PRESETS[selectedPresetIndex].preset_id}` : "Start an investigation below"}</small>
          </div>
          <div className="kpi-tile">
            <span className="kpi-label">CLAIMS UNDER REVIEW</span>
            <strong>{investigation ? `${statusCounts.claimsUnderReview} / ${investigation.claims.length}` : "—"}</strong>
            <small>
              {investigation
                ? `${statusCounts.supported} Supported · ${statusCounts.partial} Partial · ${statusCounts.insufficient} Insufficient`
                : "Awaiting investigation run"}
            </small>
          </div>
          <div className="kpi-tile">
            <span className="kpi-label">RECENT CHALLENGES</span>
            <strong>{recentChallengesCount}</strong>
            <small>{statusCounts.disputed} disputed evidence item(s)</small>
          </div>
        </section>

        <aside className="synthetic-banner">
          <span className="banner-icon">✳</span>
          <div>
            <strong>
              {explicitDemoMode
                ? "EXPLICIT DEMO FIXTURE MODE ACTIVE · NOT CONNECTED TO LIVE BACKEND"
                : "Synthetic hospitality case · decision support only · human review required"}
            </strong>
            <span>
              All records are fictional. Quote presence establishes exact-substring provenance only — not semantic
              entailment or causation. Confidence is a fixed engine review heuristic, not a calibrated probability.
            </span>
          </div>
          {explicitDemoMode ? (
            <button type="button" className="quick-fill-btn" onClick={exitExplicitDemoMode}>
              Exit Demo Mode &amp; Reconnect Port 8000
            </button>
          ) : (
            <span className="banner-tag">FASTAPI :8000</span>
          )}
        </aside>

        {/* P0.2: Visible backend error banner with explicit opt-in demo button */}
        {error && (
          <div
            className="error"
            role="alert"
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              flexWrap: "wrap",
              gap: 12,
            }}
          >
            <div>
              <strong>Backend Error:</strong> {error}
            </div>
            <div style={{ display: "flex", gap: 8 }}>
              <button type="button" className="quick-fill-btn" onClick={loadRecordsFromBackend}>
                ↻ Retry Backend (127.0.0.1:8000)
              </button>
              {!explicitDemoMode && (
                <button type="button" className="quick-fill-btn" onClick={enableExplicitDemoMode}>
                  Enable Explicit Demo Fixture Mode
                </button>
              )}
            </div>
          </div>
        )}

        {/* ── Section 01: Canonical Preset & Question Launchpad ── */}
        <section id="section-investigations" className="workspace">
          <div className="workspace-heading">
            <div>
              <span className="section-kicker">01 — INVESTIGATION SETUP</span>
              <h2>Select a supported hospitality investigation scenario</h2>
            </div>
            <span className="record-count">
              PRESET_ID: <b>{PRESETS[selectedPresetIndex].preset_id}</b> · {records.length} RECORDS
            </span>
          </div>
          <div className="investigation-row">
            <label className="select-wrap">
              <span>SUPPORTED SCENARIO (PRESET_ID)</span>
              <select
                value={selectedPresetIndex}
                onChange={(e) => setSelectedPresetIndex(Number(e.target.value))}
              >
                {PRESETS.map((item, i) => (
                  <option value={i} key={item.preset_id}>
                    {item.label} ({item.preset_id})
                  </option>
                ))}
              </select>
            </label>
            <div className="question-preview">
              <span>CANONICAL QUESTION &amp; SCOPE</span>
              <p>{PRESETS[selectedPresetIndex].question}</p>
              <small style={{ color: "#6e7770", fontSize: 11 }}>{PRESETS[selectedPresetIndex].description}</small>
            </div>
            <button className="primary" onClick={startInvestigation} disabled={busy}>
              {busy ? "Evaluating…" : investigation ? "Re-run Investigation" : "Start Investigation"}
              <span>↗</span>
            </button>
          </div>
        </section>

        {/* ── PDF Section 6: Before vs After Challenge Comparison ── */}
        {change && (
          <section className="change-card" role="status" aria-live="polite">
            <div className="change-mark">↻</div>
            <div style={{ flex: 1 }}>
              <span className="section-kicker">
                CHALLENGE &amp; REASSESSMENT COMPARISON · REVISION v{String(change.beforeVersion).padStart(2, "0")} → v
                {String(change.afterVersion).padStart(2, "0")}
              </span>
              <h3>{HYPOTHESES[change.after.hypothesis_id] ?? change.after.hypothesis_id}</h3>

              <div className="challenge-snapshot-grid">
                <div className="snapshot-box">
                  <span className="kpi-label">BEFORE CHALLENGE (REV v{change.before.version})</span>
                  <strong>
                    Status: {change.before.status} · {Math.round(change.before.confidence * 100)}% heuristic est.
                  </strong>
                  {change.before.explanation_trace?.status_rule_id && (
                    <small>
                      Rules: <code>{change.before.explanation_trace.status_rule_id}</code> /{" "}
                      <code>{change.before.explanation_trace.confidence_rule_id ?? "—"}</code>
                    </small>
                  )}
                  <small>{change.before.uncertainty}</small>
                </div>
                <div className="snapshot-box after">
                  <span className="kpi-label">AFTER CHALLENGE (REV v{change.after.version})</span>
                  <strong>
                    Status: {change.after.status} · {Math.round(change.after.confidence * 100)}% heuristic est.
                  </strong>
                  {change.after.explanation_trace?.status_rule_id && (
                    <small>
                      Rules: <code>{change.after.explanation_trace.status_rule_id}</code> /{" "}
                      <code>{change.after.explanation_trace.confidence_rule_id ?? "—"}</code>
                    </small>
                  )}
                  <small>{change.after.uncertainty}</small>
                </div>
              </div>

              <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 10 }}>
                <TracePill
                  text={`RECOMPUTED CLAIM IDS: ${change.recomputedIds.map((id) => HYPOTHESES[id] ?? id).join(", ")}`}
                  tone="green"
                />
                <TracePill
                  text={`DISPUTED EVIDENCE: ${change.disputedIds.length > 0 ? change.disputedIds.join(", ") : "NONE"}`}
                  tone="orange"
                />
                {change.before.explanation_trace?.status_rule_id !==
                  change.after.explanation_trace?.status_rule_id && (
                  <TracePill
                    text={`STATUS RULE CHANGED: ${change.before.explanation_trace?.status_rule_id ?? "—"} → ${
                      change.after.explanation_trace?.status_rule_id ?? "—"
                    }`}
                    tone="purple"
                  />
                )}
                <TracePill text={`REASON: "${change.reason}"`} tone="muted" />
              </div>
            </div>
          </section>
        )}

        {investigation && (
          <>
            <section className="findings">
              <div className="workspace-heading">
                <div>
                  <span className="section-kicker">02 — HYPOTHESIS RESULTS &amp; EVIDENCE EXPLORER</span>
                  <h2>Five candidate contributors</h2>
                </div>
                <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                  <span className="version-pill">SUPPORTED: {statusCounts.supported}</span>
                  <span className="version-pill">PARTIAL: {statusCounts.partial}</span>
                  <span className="version-pill">CONTRADICTED: {statusCounts.contradicted}</span>
                  <span className="version-pill">INSUFFICIENT: {statusCounts.insufficient}</span>
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
                            {claim.status} · {pct}% heuristic · v{claim.version}
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
                        {Math.round(selected.confidence * 100)}% fixed engine review heuristic (not a calibrated
                        probability · human verification required)
                      </span>
                    </p>

                    {/* ── PDF Section 5: Dedicated Explainability, Dispositions, Advisory Coverage & Source Independence ── */}
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
                          EXPLAINABILITY &amp; DECISION RULES (explanation_trace)
                        </span>
                        <TracePill text="ENGINE-OWNED VERIFICATION LOGIC" tone="purple" />
                      </div>

                      {/* 5A: Decision Rules */}
                      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 8 }}>
                        <TracePill
                          text={`STATUS RULE ID: ${
                            selected.explanation_trace?.status_rule_id ?? `DERIVED_${selected.status}`
                          }`}
                          tone="green"
                        />
                        <TracePill
                          text={`CONFIDENCE RULE ID: ${
                            selected.explanation_trace?.confidence_rule_id ?? "FIXED_HEURISTIC_RULE"
                          }`}
                          tone="muted"
                        />
                        <TracePill
                          text={`INDEPENDENT SOURCE GROUPS: ${
                            selectedSourceGroups.length > 0 ? selectedSourceGroups.join(", ") : "NONE"
                          }`}
                          tone={selectedSourceGroups.length > 1 ? "green" : "muted"}
                        />
                      </div>

                      {/* 5D: Source Independence explanation */}
                      <p style={{ margin: "8px 0 0", fontSize: 11, color: "#4f5a52", lineHeight: 1.5 }}>
                        <b>Source Independence:</b>{" "}
                        {selectedSourceGroups.length > 1
                          ? `Corroborated across ${selectedSourceGroups.length} distinct source groups (${selectedSourceGroups.join(
                              ", "
                            )}), reducing single-channel reporting bias.`
                          : selectedSourceGroups.length === 1
                          ? `Evidence currently originates from a single source group (${selectedSourceGroups[0]}). Cross-group corroboration is recommended before final sign-off.`
                          : "No verified source groups linked to this hypothesis."}
                      </p>

                      {/* 5B / P1.1: Evidence Dispositions (`codes: string[]`) */}
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
                                  background: "#fbfaf6",
                                  border: "1px solid #e1e0d8",
                                  borderRadius: 2,
                                }}
                              >
                                <span
                                  style={{
                                    fontFamily: "ui-monospace,monospace",
                                    fontSize: 10,
                                    fontWeight: 700,
                                    color: "#27322f",
                                    marginRight: 4,
                                  }}
                                >
                                  {item.recordKey}:
                                </span>
                                {item.codes.length > 0 ? (
                                  item.codes.map((code) => (
                                    <TracePill
                                      key={`${item.recordKey}-${code}`}
                                      text={code}
                                      tone={
                                        code.includes("DISPUTED") ||
                                        code.includes("EXCLUDED") ||
                                        code.includes("DOWNGRADED") ||
                                        code.includes("UNVERIFIED")
                                          ? "orange"
                                          : "green"
                                      }
                                    />
                                  ))
                                ) : (
                                  <TracePill text="NO_CODES" tone="muted" />
                                )}
                                {item.note && (
                                  <span style={{ fontSize: 10, color: "#69756b" }}>({item.note})</span>
                                )}
                              </div>
                            ))}
                          </div>
                        </div>
                      )}

                      {/* 5C / P1.2: Structured Advisory Evidence Coverage */}
                      {parsedCoverageCategories.length > 0 && (
                        <div
                          style={{
                            marginTop: 12,
                            padding: "10px 12px",
                            background: "#fbfaf6",
                            border: "1px solid #d8dacf",
                            borderRadius: 2,
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
                              tone="muted"
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
                                    background: isCovered ? "#eef4f0" : "#f7efe9",
                                    borderLeft: `3px solid ${isCovered ? "#285f4d" : "#b45c37"}`,
                                    display: "grid",
                                    gap: 5,
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
                                    <div>
                                      <span
                                        style={{
                                          fontFamily: "ui-monospace,monospace",
                                          fontSize: 10,
                                          fontWeight: 700,
                                          color: "#27322f",
                                        }}
                                      >
                                        {cat.name}
                                      </span>
                                      {cat.details && (
                                        <span style={{ fontSize: 10, color: "#57645b", marginLeft: 8 }}>
                                          — {cat.details}
                                        </span>
                                      )}
                                    </div>
                                    <TracePill text={cat.state} tone={isCovered ? "green" : "orange"} />
                                  </div>

                                  <div
                                    style={{
                                      display: "flex",
                                      flexWrap: "wrap",
                                      gap: 10,
                                      fontSize: 9.5,
                                      fontFamily: "ui-monospace,monospace",
                                      color: "#57645b",
                                    }}
                                  >
                                    <span>
                                      Matching IDs: <b>{cat.matchingIds.length > 0 ? cat.matchingIds.join(", ") : "None"}</b>
                                    </span>
                                    <span>
                                      Fresh Support IDs:{" "}
                                      <b>{cat.freshSupportIds.length > 0 ? cat.freshSupportIds.join(", ") : "None"}</b>
                                    </span>
                                    <span>
                                      Fresh Contradiction IDs:{" "}
                                      <b>
                                        {cat.freshContradictionIds.length > 0
                                          ? cat.freshContradictionIds.join(", ")
                                          : "None"}
                                      </b>
                                    </span>
                                    <span>
                                      Source Groups:{" "}
                                      <b>
                                        {cat.independentGroups.length > 0 ? cat.independentGroups.join(", ") : "None"}
                                      </b>
                                    </span>
                                  </div>
                                </div>
                              );
                            })}
                          </div>
                          <small
                            style={{
                              display: "block",
                              marginTop: 6,
                              fontSize: 9.5,
                              color: "#6e7770",
                              fontFamily: "ui-monospace,monospace",
                            }}
                          >
                            Advisory notice: Coverage tracks whether expected evidence categories are represented; it
                            does not establish causal proof, formal sufficiency, or a calibrated probability.
                          </small>
                        </div>
                      )}
                    </div>

                    {/* 5E: Uncertainty & Missing Evidence */}
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
                          <b>Evidence gap (additional evidence useful for review)</b>
                          <br />
                          {item}
                        </p>
                      </div>
                    ))}

                    {/* ── PDF Section 4C: Evidence Explorer with Expandable Details ── */}
                    <div className="evidence-heading">
                      <div>
                        <span className="section-kicker">EVIDENCE EXPLORER (CLICK TO EXPAND RECORD DETAILS)</span>
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
                      {selected.evidence.map((item, i) => {
                        const evKey = `${item.source_record_id}-${i}`;
                        const isExpanded = expandedEvidenceKey === evKey;
                        const fullRecord = records.find((r) => r.id === item.source_record_id);
                        return (
                          <div
                            className={`evidence-card ${item.stale ? "is-stale" : ""} ${
                              item.disputed ? "is-disputed" : ""
                            }`}
                            key={evKey}
                          >
                            <div className="evidence-meta">
                              <span className="source-id">{item.source_record_id}</span>
                              <span>DEPT: {item.department}</span>
                              <span>GROUP: {item.source_group ?? fullRecord?.source_group ?? "standard"}</span>
                              <span>{item.stale ? "STALE" : "FRESH"}</span>
                              <time>{new Date(item.timestamp).toLocaleString()}</time>
                              <span
                                className={`stance ${
                                  item.review_state === "UNVERIFIED" ? "unverified" : item.stance.toLowerCase()
                                }`}
                              >
                                {item.review_state === "UNVERIFIED"
                                  ? `UNVERIFIED · PROPOSED ${item.proposed_stance ?? item.stance}`
                                  : `${item.stance} (${item.review_state ?? "ACCEPTED"})`}
                              </span>
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
                                marginTop: 8,
                              }}
                            >
                              <div className="evidence-flags" style={{ marginTop: 0 }}>
                                {item.stale && <span>STALE SOURCE</span>}
                                {item.disputed && <span>DISPUTED · RETAINED FOR HUMAN REVIEW</span>}
                                {item.review_state === "UNVERIFIED" && (
                                  <span>PHRASE-CUE GUARD · NOT COUNTED AS CLAIM EVIDENCE</span>
                                )}
                              </div>
                              <button
                                type="button"
                                className="quick-fill-btn"
                                style={{ padding: "4px 8px", fontSize: 9 }}
                                onClick={() => setExpandedEvidenceKey((curr) => (curr === evKey ? null : evKey))}
                              >
                                {isExpanded ? "▲ Hide Full Source Record" : "▼ Inspect Full Source Record"}
                              </button>
                            </div>
                            {isExpanded && (
                              <div
                                style={{
                                  marginTop: 10,
                                  padding: "10px 12px",
                                  background: "#f1f0e8",
                                  border: "1px solid #d8dacf",
                                  borderRadius: 2,
                                  fontSize: 11,
                                  color: "#27322f",
                                }}
                              >
                                <div style={{ fontFamily: "ui-monospace,monospace", fontSize: 9.5, color: "#57645b" }}>
                                  ORIGINAL RECORD ID: {item.source_record_id} · TAGS:{" "}
                                  {(fullRecord?.tags ?? []).join(", ") || "none"}
                                </div>
                                <p style={{ margin: "6px 0 0", lineHeight: 1.55 }}>
                                  {fullRecord?.text ?? item.quote}
                                </p>
                              </div>
                            )}
                          </div>
                        );
                      })}
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
                                    {id} · {r.department} ({r.source_group ?? "source"})
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
                            ⚡ Auto-Fill Challenge Input
                          </button>
                        </div>
                        <small>
                          Only claims depending on this record are reevaluated. A valid challenge may update confidence
                          or evidence disposition codes even if the overall status label remains unchanged.
                        </small>
                      </form>
                    </details>
                  </article>
                )}
              </div>
            </section>

            {/* ── PDF Section 7 / P2.1: Interactive Read-Only Revision History & Snapshot Inspector ── */}
            <section id="section-history" className="history-section">
              <div className="workspace-heading">
                <div>
                  <span className="section-kicker">03 — INTERACTIVE REVISION HISTORY (CLICK REVISION TO INSPECT)</span>
                  <h2>Investigation audit trail &amp; stored before/after snapshots</h2>
                </div>
                <span className="record-count">{history.length} RECORDED VERSIONS · READ-ONLY INSPECTOR</span>
              </div>

              {inspectedHistoryEntry && (
                <div
                  role="region"
                  aria-label={`Read-only snapshot inspector for revision ${inspectedHistoryEntry.version}`}
                  style={{
                    marginBottom: 18,
                    padding: "14px 16px",
                    background: "#fbfaf6",
                    border: "1px solid #c5d9cc",
                    borderLeft: "4px solid #285f4d",
                    borderRadius: 2,
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
                        READ-ONLY STORED SNAPSHOT INSPECTOR · REVISION{" "}
                        {String(inspectedHistoryEntry.version).padStart(2, "0")}
                      </span>
                      <b style={{ fontSize: 13 }}>
                        Event: {inspectedHistoryEntry.event} ·{" "}
                        {new Date(inspectedHistoryEntry.created_at).toLocaleString()}
                      </b>
                    </div>
                    <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                      <TracePill text="READ-ONLY · NO BACKEND STATE MUTATION" tone="muted" />
                      <button
                        type="button"
                        className="quick-fill-btn"
                        style={{ padding: "5px 9px" }}
                        onClick={() => setInspectedHistoryVersion(null)}
                      >
                        ✕ Close Inspector
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
                        const statusChanged = beforeClaim && beforeClaim.status !== afterClaim.status;
                        const confChanged =
                          beforeClaim &&
                          Math.round(beforeClaim.confidence * 100) !== Math.round(afterClaim.confidence * 100);
                        return (
                          <div key={claimKey} className="challenge-snapshot-grid">
                            <div className="snapshot-box">
                              <span className="kpi-label">
                                STORED BEFORE ({HYPOTHESES[afterClaim.hypothesis_id] ?? claimKey})
                              </span>
                              {beforeClaim ? (
                                <>
                                  <strong>
                                    {beforeClaim.status} · {Math.round(beforeClaim.confidence * 100)}% est. (v
                                    {beforeClaim.version})
                                  </strong>
                                  {beforeClaim.explanation_trace?.status_rule_id && (
                                    <small>
                                      Rule: <code>{beforeClaim.explanation_trace.status_rule_id}</code>
                                    </small>
                                  )}
                                  <small>{beforeClaim.uncertainty}</small>
                                </>
                              ) : (
                                <small>No prior claim snapshot recorded.</small>
                              )}
                            </div>
                            <div className="snapshot-box after">
                              <div style={{ display: "flex", justifyContent: "space-between", flexWrap: "wrap", gap: 4 }}>
                                <span className="kpi-label">
                                  STORED AFTER ({HYPOTHESES[afterClaim.hypothesis_id] ?? claimKey})
                                </span>
                                {(statusChanged || confChanged) && (
                                  <TracePill
                                    text={
                                      statusChanged && confChanged
                                        ? "STATUS & CONFIDENCE CHANGED"
                                        : statusChanged
                                        ? "STATUS CHANGED"
                                        : "CONFIDENCE UPDATED"
                                    }
                                    tone="orange"
                                  />
                                )}
                              </div>
                              <strong>
                                {afterClaim.status} · {Math.round(afterClaim.confidence * 100)}% est. (v
                                {afterClaim.version})
                              </strong>
                              {afterClaim.explanation_trace?.status_rule_id && (
                                <small>
                                  Rule: <code>{afterClaim.explanation_trace.status_rule_id}</code>
                                </small>
                              )}
                              <small>{afterClaim.uncertainty}</small>
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  ) : (
                    <p style={{ fontSize: 11, color: "#69756b", margin: 0 }}>
                      Baseline initialization event (Revision 01). Recomputed claims:{" "}
                      {inspectedHistoryEntry.recomputed_claim_ids.map((id) => HYPOTHESES[id] ?? id).join(", ") ||
                        "Initial evaluation"}
                      . Select a challenge revision to compare stored before/after claim snapshots.
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
                            padding: "10px 12px",
                            background: isSelected ? "#e8f0eb" : "#fbfaf6",
                            border: `1px solid ${isSelected ? "#285f4d" : "#e1e0d8"}`,
                            borderRadius: 2,
                          }}
                        >
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
                                fontFamily: "ui-monospace,monospace",
                                fontSize: 9,
                                color: "#285f4d",
                                fontWeight: 600,
                              }}
                            >
                              {isSelected ? "▼ HIDE STORED SNAPSHOT" : "▶ INSPECT STORED SNAPSHOT (READ-ONLY)"}
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

        {/* ── PDF Section 8: Searchable & Filterable Evidence Library ── */}
        <section id="section-library" className="history-section">
          <div className="workspace-heading">
            <div>
              <span className="section-kicker">04 — EVIDENCE LIBRARY (BACKEND SOURCE RECORDS)</span>
              <h2>Searchable operational record corpus</h2>
            </div>
            <span className="record-count">
              SHOWING {filteredLibraryRecords.length} OF {records.length} RECORDS
            </span>
          </div>

          <div
            style={{
              display: "grid",
              gridTemplateColumns: "1fr 180px 180px",
              gap: 12,
              background: "#eeede6",
              border: "1px solid #e1e0d8",
              padding: 14,
              marginBottom: 14,
            }}
          >
            <label className="select-wrap">
              <span>SEARCH BY RECORD ID, TEXT, OR TAG</span>
              <input
                type="search"
                value={libraryQuery}
                onChange={(e) => setLibraryQuery(e.target.value)}
                placeholder="Search e.g. REC-101, checklist, latency, handover…"
                style={{
                  font: "12px Arial, sans-serif",
                  color: "var(--ink)",
                  border: "1px solid #d6d8cf",
                  background: "#fbfaf6",
                  padding: "10px 11px",
                  width: "100%",
                  borderRadius: 2,
                }}
              />
            </label>
            <label className="select-wrap">
              <span>FILTER BY DEPARTMENT</span>
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
              <span>FILTER BY SOURCE GROUP</span>
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

          {filteredLibraryRecords.length === 0 ? (
            <p className="empty">
              {records.length === 0
                ? "No records loaded from backend yet. Start the backend server at 127.0.0.1:8000 and click Retry."
                : "No source records match the active search/filter criteria."}
            </p>
          ) : (
            <div className="evidence-list">
              {filteredLibraryRecords.map((rec) => {
                const isExpanded = expandedRecordId === rec.id;
                return (
                  <div key={rec.id} className="evidence-card" style={{ background: "#fbfaf6" }}>
                    <div className="evidence-meta">
                      <span className="source-id" style={{ fontWeight: 700 }}>
                        {rec.id}
                      </span>
                      <span>DEPT: {rec.department}</span>
                      {rec.source_group && <span>SOURCE GROUP: {rec.source_group}</span>}
                      <time>{new Date(rec.timestamp).toLocaleString()}</time>
                    </div>
                    <p style={{ fontSize: 13, color: "#27322f", margin: "8px 0", lineHeight: 1.55 }}>{rec.text}</p>
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 8 }}>
                      <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                        {(rec.tags ?? []).map((t) => (
                          <TracePill key={t} text={`#${t}`} tone="muted" />
                        ))}
                      </div>
                      <button
                        type="button"
                        className="quick-fill-btn"
                        style={{ padding: "4px 8px", fontSize: 9 }}
                        onClick={() => setExpandedRecordId((curr) => (curr === rec.id ? null : rec.id))}
                      >
                        {isExpanded ? "▲ Hide Metadata" : "▼ Inspect Metadata"}
                      </button>
                    </div>
                    {isExpanded && (
                      <div
                        style={{
                          marginTop: 8,
                          padding: "8px 10px",
                          background: "#f4f3ee",
                          border: "1px solid #e1e0d8",
                          fontFamily: "ui-monospace,monospace",
                          fontSize: 10,
                          color: "#4f5a52",
                        }}
                      >
                        Record ID: {rec.id} · Department: {rec.department} · Source Group:{" "}
                        {rec.source_group ?? "unassigned"} · Timestamp: {rec.timestamp} · Character Length:{" "}
                        {rec.text.length}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </section>
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