# StanceAlgebra — proved, assumed, not modelled
`ct3/StanceAlgebra.v`, Coq 8.18, standard library only. No `Admitted`, no `Axiom`, no
`Parameter`. Build: `cd ct3 && coqc StanceAlgebra.v`. Its 20 trailing `Print
Assumptions` commands all print `Closed under the global context` (control: the same
command on a `classic` lemma prints `Axioms: ...`).

## Proved

- **§1 Polarity and scope.** `neg_involution : neg (neg p) = p`. `act_compose :
  act (xorb a b) p = act a (act b p)` — the monoid `(bool, xorb, false)` acts on
  polarity. Also `act_depends_on_parity_only`, `act_inj`, `act_surjective`,
  `neg_n_add`.
- **§2 Carrier and composition.** `compose` is a commutative idempotent band:
  `compose_assoc`, `compose_comm`, `compose_idem`, `compose_unit_l/r`. Both
  abstentions absorb (`compose_absorbs_noinfo_l/r`, `unreadable_outranks_conflict`,
  `compose_conflict_with_direction`) and are *different elements*:
  `abstain_provenances_distinct : NoClause <> NoInfo /\ NoInfo <> Conflict /\
  NoClause <> Conflict`, while `abstain_provenances_collapse` shows all three
  project to `PAbstain`. The consequence is a theorem: `no_public_composition : ~
  (exists op, forall a b, public (compose a b) = op (public a) (public b))`. Also
  `public_not_injective`, `two_sections_disagree`.
- **§3 Negation on a clause.** `flip_involution`; `flip_compose : flip (compose a b)
  = compose (flip a) (flip b)` (automorphism of the band); `flip_fixes_abstention`
  (negation cannot manufacture content); `polarity_of_flip`; `flip_n_two`.
- **§3/§4 Order.** `compose_all_perm : Permutation l1 l2 -> compose_all l1 =
  compose_all l2`, by induction over `perm_swap` from associativity and
  commutativity; plus `compose_all_app`, `compose_all_batch_order`.
- **§5 Abstention soundness.** `compose_all_noinfo : compose_all l = NoInfo <->
  In NoInfo l` — both directions, so unreadability is neither lost nor invented.
  Hence `unreadable_absorbs`, `no_direction_from_unreadable` (not `Supports`, not
  `Contradicts`, public value `PAbstain`), `direction_excludes_unreadable`,
  `abstention_provenance_matters` (nine cases where the provenances diverge).
- **§6 The signed report.** `status_depends_on_dispute`, `reported_at_switch` (0.50,
  0.25, 0.667), `reported_status_at_switch`, `shipped_report_not_monotone : reported
  2 1 < reported 1 1`, `no_policy_keeps_monotonicity_and_integrity`,
  `boundary_collision`.

## The statement that turned out false
I intended `public_compose_hom : forall a b, public (compose a b) = pub_compose
(public a) (public b)`; it is false: `compose NoClause Supports = Supports` so
`public = PSupports`, but `compose NoInfo Supports = NoInfo` so `public = PAbstain`,
while `public NoClause = public NoInfo = PAbstain` — any `op` must answer both the
same. Kept as `Example public_composition_counterexample` and `pub_compose_not_hom`,
generalised to `no_public_composition`: not "the verdict is a quotient" but
"collapsing the abstentions costs composing".

## Assumptions connecting to the Python

- **A1.** `label` is `backend/app/decision_table.py:221 _label` under
  `POLICY_SIGNED_MARGIN` only (`min_support_groups=2`, `imbalance_per_group=3`,
  `contest_blocks_decisive=False` by the default at line 74, not overridden at
  78-81). Under `contest_blocks_decisive=True` the `s > 0 and c > 0` branch at line
  223 would need modelling and `(4,1)` in `boundary_collision` would stop being
  `Supported`.
- **A2.** `reported` is `decide(s, 0, disputed_contradiction=d)`: the magnitude is
  `score(effective_s, effective_c)` (line 293), where `effective_*` is `(s, c)`
  (line 271) unless the downgrade at line 275 fires, then `(s+ds, c+dc)` (line 290).
  That disjunction is the fidelity hypothesis `f 2 1 = quarter \/ f 2 1 =
  two_thirds` in the impossibility theorem.
- **A3.** `Supports`/`Contradicts` are `reviewed_relation_details` returning
  `relation = Some(...)`; `Conflict` is `relation = None` with
  `AMBIGUOUS_CUE_RELATIONS`; `NoInfo` is `relation = None` from a rejection reason
  or no matched cue. The last two are the same Python value `None` — the collapse §2
  proves, now with its cost attached.
- **A4.** `NoClause` has no Python counterpart: the guard never says "no clause was
  considered", it returns a relation or `None`, so absence and unreadability are
  already merged in the artifact. `NoClause` models only the fold's identity.
- **A5.** `NoInfo` above `Conflict` is my choice, not a fact about the Python (its
  `rejected_reasons` does record rejected cues). The algebra needs an order.
- **A6.** Scope parity (§1, §3) is a design the guard does *not* have:
  `semantic_guard.py` rejects a cue with a negation suffix instead of flipping a
  stance, so `flip` has no Python caller today.

## Not modelled

The phrase inventory — cue lists, regexes, tokenisation, whether any cue is adequate.
Hedges, conditionals, quantifiers, "later contrast" appear only as a verdict.
`engine.py`'s per-item ACCEPTED/UNVERIFIED mapping, and any consumer reading
`score` alone. Floating point: `Q` is exact, `score` returns `float`, so 0.50/0.25
is proved in exact arithmetic, not in binary floating point.
