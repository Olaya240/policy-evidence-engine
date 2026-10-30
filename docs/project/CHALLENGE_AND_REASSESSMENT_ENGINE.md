# Challenge and reassessment engine

## Two distinct challenge flows

The demo API accepts reviewer challenges and uses `policy_evidence_demo.py` to recompute its bounded synthetic scenario assessment. Separately, `policy_challenge_propagation.py` is a generic internal planner over a validated `EvidenceDependencyGraph`. These flows must not be conflated: the planner is not routed through the demo API and does not perform reassessment itself.

## Planner input and traversal

`ChallengeRequest` identifies a challenge, comparison, target node and type, category, explanation, optional source-passage evidence references and descriptive event order. The planner validates target/type/comparison/evidence references. It traverses permitted graph relationships under limits for visited nodes, edges, path length, paths per node and total path entries.

## Impact states

The planner can classify impacts as `DIRECTLY_CHALLENGED`, `REASSESSMENT_REQUIRED`, `POTENTIALLY_AFFECTED`, `UNCHANGED`, `BLOCKED_BY_MISSING_PROVENANCE`, or `INCONCLUSIVE`. It returns paths, blockers, traversal completeness, and limitations. `AFFECTS` indicates that reassessment may be needed; it does not mean a claim is false.

`UNCHANGED` means no supported path was found in a complete bounded search over the declared scope. It is not proof of global independence or semantic non-impact. An incomplete search cannot treat unexplored nodes as unchanged.

## Workflow status

The intended workflow is: receive challenge, validate source/provenance, analyze dependent nodes, identify reassessment candidates and blockers, recompute only supported affected conclusions, and present changes for human review. The generic planner implements bounded impact planning only. It does not create a `ChallengeEvent`, alter graph state, invoke a model, persist a plan, or recalculate conclusions. Demo-specific recomputation is implemented for its synthetic scenarios; generalized integration remains incomplete. No standalone planner HTTP endpoint is present in the route inventory.
