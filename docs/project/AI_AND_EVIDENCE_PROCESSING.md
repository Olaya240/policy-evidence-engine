# AI and evidence processing

## Current provider roles

There are separate provider boundaries:

1. The handover `AssessmentEngine` defaults to `MockProvider` behind `MandatoryProviderBoundary`. Meta Muse Spark is an optional backend provider, activated explicitly with `ENABLE_META` and the backend credential/budget environment variables documented in `backend/META_PROVIDER.md`. The allowed proposal contains a source record ID, exact quote, stance and rationale. The application validates source membership, unrestricted status, exact-substring quotation, allowed stance and nonblank rationale. Provider proposals do not author final status, dependencies, versions or history. Provider attribution is captured from the invoked instance; validated response IDs and token usage are optional, and legacy records without attribution resolve to `unknown`.
2. The isolated policy comparison API constructs a `FakePolicyCandidateAdapter` response. It cites bounded excerpts and abstains from semantic assessment; API results remain proposal-only and `INCONCLUSIVE`.

Meta support applies only to the handover assessment workflow. The standalone policy-comparison API uses `FakePolicyCandidateAdapter`, and the React Policy Demo uses synthetic scenarios; neither calls Meta. No HR policy Q&A, HR-document retrieval, employee-account system, or production deployment is implemented. The prior one-request assessment remains **INCONCLUSIVE** as to provider because it predates persisted attribution.

## Processing and evidence limits

`policy_compare.py` validates synthetic policy pairs, derives passages and validates citations using source text/offsets/digests. The policy graph represents claims and evidence dependencies. No embedding model, vector index, general RAG pipeline or external policy-document ingestion service was identified in the inspected source.

Exact quote matching establishes local provenance, not semantic entailment. Stance and rationale are proposals for review. The demo deliberately withholds definitive applicability conclusions when department grounding is missing. Confidence-like values in the legacy handover prototype are deterministic review heuristics, not calibrated probabilities.

## Controls and limitations

Provider boundary checks include restricted-record exclusion, strict proposal validation, bounded transport design, fixed failure handling, and tests described in source/docs. The project documents limitations of phrase-cue guards, prompt-injection evaluation, and in-process Python boundaries: these are not general semantic validation or security sandboxes. No tests were run during this documentation task.
