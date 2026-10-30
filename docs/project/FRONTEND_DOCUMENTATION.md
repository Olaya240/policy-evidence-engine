# Frontend documentation

## Stack and entry points

The frontend is a Vite application using React 19 and TypeScript (see `frontend/package.json`). `src/main.tsx` mounts `App` with React strict mode and imports `styles.css`. There is no router library: `App.tsx` watches `window.location.hash`; `#/demo` displays `PolicyDemoPage`, while the default view is the handover investigation page.

## Pages and workflows

| View | Evidence-backed capabilities | API path |
|---|---|---|
| Handover investigation | Choose a synthetic question, run an investigation, inspect five hypotheses/evidence/uncertainty, challenge a source quote, inspect recomputation and history. | `/api/...` |
| Policy demo | Choose one of three scenarios, compare versions/citations, create a session, challenge department applicability, inspect recomputation and audit events, reset/start a session. | `/demo-api/...` |

The product presentation includes synthetic-data and human-review notices. The handover UI describes confidence as a review estimate; it is not a calibrated probability.

## State and API communication

State is managed with React hooks (`useState`, `useEffect`, `useMemo`, `useCallback`). The handover page fetches records, investigation, and history and posts challenge requests. The policy demo page fetches scenario metadata/details and calls session/challenge/reset routes. Vite runs on loopback port 5174; README documents proxies to 8081 (`/api`) and 8083 (`/demo-api`). The policy comparison API on 8082 is not included in this proxy.

## Limitations

The UI is a local prototype, not an authenticated production application. The policy demo session is server-memory-only and lost on server restart. The handover page and policy demo share a frontend shell but use distinct backend models and workflows. UI text must not be mistaken for proof of real deployment, source ingestion, semantic understanding, or persisted policy-graph state.
