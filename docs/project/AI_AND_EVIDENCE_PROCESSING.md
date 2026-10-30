# AI and evidence processing

## Current provider roles

There are two separate provider boundaries:

1. The legacy handover `AssessmentEngine` defaults to `MockProvider` behind `MandatoryProviderBoundary`. The allowed mock proposal contains a source record ID, exact quote, stance and rationale. The application validates source membership, unrestricted status, exact-substring quotation, allowed stance and nonblank rationale. Provider proposals do not author final status, dependencies, versions or history.
2. The isolated policy comparison API constructs a `FakePolicyCandidateAdapter` response. It cites bounded excerpts and abstains from semantic assessment; API results remain proposal-only and `INCONCLUSIVE`.

An HTTPX bounded transport adapter exists in legacy provider code for offline fake-transport verification, but runtime selection remains mock-only. No credential is configured or loaded. A real Meta Model or other external AI provider is not connected.

## Processing and evidence limits

`policy_compare.py` validates synthetic policy pairs, derives passages and validates citations using source text/offsets/digests. The policy graph represents claims and evidence dependencies. No embedding model, vector index, general RAG pipeline or external policy-document ingestion service was identified in the inspected source.

Exact quote matching establishes local provenance, not semantic entailment. Stance and rationale are proposals for review. The demo deliberately withholds definitive applicability conclusions when department grounding is missing. Confidence-like values in the legacy handover prototype are deterministic review heuristics, not calibrated probabilities.

## Controls and limitations

Provider boundary checks include restricted-record exclusion, strict proposal validation, bounded transport design, fixed failure handling, and tests described in source/docs. The project documents limitations of phrase-cue guards, prompt-injection evaluation, and in-process Python boundaries: these are not general semantic validation or security sandboxes. No tests were run during this documentation task.
