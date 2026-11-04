(* Refinement bridge: the shipped Python decision table, computed in Coq.

   `ct3/DecisionTable.v` proves properties of a *model* of the table. This file
   closes the other half: it computes the model's decision on the whole finite
   domain the Python implementation is tested over, and writes it out, so that
   `backend/tests/test_decision_table_refinement.py` can assert row-by-row
   equality against `app.decision_table.decide`. A proved function whose Python
   counterpart is a different function is proved about nothing.

   Build (from this directory; `..` is `ct3/`, bound to the empty logical prefix
   so `Require Import DecisionTable` resolves to the existing `ct3/DecisionTable.vo`):

       coqc -Q .. "" generate_table.v

   That writes `decision-table.out` and `legend.out` next to this file. (Coq's
   `Redirect` appends `.out` to whatever name it is given, so the target below
   is `"decision-table"`.)

   What is modelled
   ----------------
   * the score, as an exact rational: numerator s - c, denominator s + c + 1,
     kept as two integers so no float rounding appears anywhere in Coq;
   * `_label` from `backend/app/decision_table.py` under the default policy
     `POLICY_SIGNED_MARGIN` (min_support_groups = 2, imbalance_per_group = 3,
     contest_blocks_decisive = False), including which status rule fired;
   * the dispute rule: label the evidence, then label it again *as if* the
     challenged groups counted; if the two disagree the verdict is withheld
     (PARTIAL, RDisputeRelevant) and the reported score is re-priced to the
     challenged configuration, otherwise the undisputed label and score stand.

   What is deliberately not modelled
   ---------------------------------
   * `confidence_rule_id` (a function of `s = c = 0` only, no arithmetic);
   * `contested`, `disputed_groups`, the `Decision` dataclass and the grouping
     of raw records into source groups (`_count_groups`, `group_key`);
   * the other two policies. They are unproved by construction, so ranking them
     here would pin behaviour nobody ratified.

   The grid is (s, c) in 0..6 x 0..6 and (ds, dc) in 0..2 x 0..2: 441 rows. That
   is exhaustive over the modelled domain and says nothing about counts outside
   it; see `ct3/audit/REFINEMENT-PROOF.md`.
*)

From Coq Require Import Arith ZArith Lia List Bool.
Require Import DecisionTable.

Import ListNotations.
Open Scope Z_scope.

(* ================================================================== *)
(* The status the Python code returns, and the rule that chose it      *)
(* ================================================================== *)

(* Same four labels as `Status` in `backend/app/models.py`. Named with a T
   prefix so they cannot be confused with `status` in `DecisionTable.v`, whose
   `Mixed` is this file's `TPartial`. *)
Inductive tstatus : Type :=
  | TSupported
  | TPartial
  | TContradicted
  | TInsufficient.

Definition tstatus_code (x : tstatus) : nat :=
  match x with
  | TSupported => 0
  | TPartial => 1
  | TContradicted => 2
  | TInsufficient => 3
  end.

(* The `status_rule_id` values in `_label`, plus the dispute rule. Numbers, not
   strings: Coq 8.18 core has no integer-to-string conversion, so names are
   attached on the Python side and the legend emitted below is what proves the
   two orders agree. *)
Inductive trule : Type :=
  | RSupported
  | RContradicted
  | RNoEvidence
  | RBalanced
  | RDisputeRelevant.

Definition trule_code (r : trule) : nat :=
  match r with
  | RSupported => 0
  | RContradicted => 1
  | RNoEvidence => 2
  | RBalanced => 3
  | RDisputeRelevant => 4
  end.

(* Translation from the proved model's status type. This is the only place the
   two files are joined, and `label_matches_v2` below is what makes it a proof
   obligation rather than a comment. *)
Definition of_v2 (st : status) : tstatus :=
  match st with
  | Supported => TSupported
  | Mixed => TPartial
  | Contradicted => TContradicted
  | Insufficient => TInsufficient
  end.

(* ================================================================== *)
(* `_label`, with its rule id                                          *)
(* ================================================================== *)

(* The arms are `_label`'s arms, in `_label`'s order. The predicates are
   `supported_b` / `contradicted_b` from `DecisionTable.v`, i.e. the same
   `s >= 2 /\ s >= 3c+1` and `c >= 3s+1` the theorems there are about. *)
Definition label (s c : nat) : tstatus * trule :=
  if supported_b s c then (TSupported, RSupported)
  else if contradicted_b s c then (TContradicted, RContradicted)
  else if andb (Nat.eqb s 0) (Nat.eqb c 0) then (TInsufficient, RNoEvidence)
  else (TPartial, RBalanced).

Definition label_status (s c : nat) : tstatus := fst (label s c).
Definition label_rule (s c : nat) : trule := snd (label s c).

(* The refinement link: this file's label is the proved model's `v2_status`,
   translated. If either file's threshold were edited alone, this stops
   compiling. *)
Theorem label_matches_v2 : forall s c, label_status s c = of_v2 (v2_status s c).
Proof.
  intros s c. unfold label_status, label, v2_status, of_v2.
  destruct (supported_b s c); [reflexivity |].
  destruct (contradicted_b s c); [reflexivity |].
  destruct (andb (Nat.eqb s 0) (Nat.eqb c 0)); reflexivity.
Qed.

(* ================================================================== *)
(* The score, as a rational                                            *)
(* ================================================================== *)

Definition score_num_t (s c : nat) : Z := Z.of_nat s - Z.of_nat c.
Definition score_den_t (s c : nat) : Z := Z.of_nat s + Z.of_nat c + 1.

(* Mirror symmetry, cross-multiplied so the statement is linear and the
   denominator's positivity need not be carried: the same identity z3 is asked
   to refute the negation of in `refinement/antisymmetry.smt2`. *)
Theorem score_antisymmetric :
  forall s c, score_num_t s c * score_den_t c s = - (score_num_t c s * score_den_t s c).
Proof.
  intros s c. unfold score_num_t, score_den_t. ring.
Qed.

(* The denominator is strictly positive, which is what makes the cross-multiplied
   comparisons above and below order-preserving rather than merely algebraic. *)
Theorem score_den_positive : forall s c, (0 < score_den_t s c)%Z.
Proof.
  intros s c. unfold score_den_t. lia.
Qed.

(* ================================================================== *)
(* `decide`: one cell                                                 *)
(* ================================================================== *)

Record cell : Type := mkCell {
  cell_s : nat;
  cell_c : nat;
  cell_ds : nat;
  cell_dc : nat;
  cell_eff_s : nat;   (* the counts the reported score is computed from *)
  cell_eff_c : nat;
  cell_num : Z;
  cell_den : Z;
  cell_status : tstatus;
  cell_rule : trule
}.

(* The condition `decide` calls `if challenged_status is not status`, in the order
   the code evaluates it: nothing is challenged, or the challenged configuration
   labels the claim the same way, and the verdict stands. *)
Definition dispute_relevant (s c ds dc : nat) : bool :=
  andb (negb (Nat.eqb (ds + dc) 0))
       (negb (Nat.eqb (tstatus_code (label_status s c))
                      (tstatus_code (label_status (s + ds) (c + dc))))).

(* `decide` from `backend/app/decision_table.py`, minus the fields listed as not
   modelled in the header. The verdict is downgraded only when the challenged
   configuration changes the label, and only then is the number re-priced. *)
Definition decide_cell (s c ds dc : nat) : cell :=
  if dispute_relevant s c ds dc then
    mkCell s c ds dc (s + ds) (c + dc)
           (score_num_t (s + ds) (c + dc)) (score_den_t (s + ds) (c + dc))
           TPartial RDisputeRelevant
  else
    mkCell s c ds dc s c (score_num_t s c) (score_den_t s c)
           (label_status s c) (label_rule s c).

(* `_label` never returns the dispute rule, which is what lets the branch above
   be read as "the undisputed label stands". *)
Lemma label_rule_not_dispute : forall s c, label_rule s c <> RDisputeRelevant.
Proof.
  intros s c. unfold label_rule, label.
  (* One `destruct` per condition, with no `cbn` in between: `cbn` would unfold
     `contradicted_b` into `Nat.leb` and leave the next `destruct` abstracting a
     term that no longer occurs. *)
  destruct (supported_b s c).
  - cbn. discriminate 1.
  - destruct (contradicted_b s c).
    + cbn. discriminate 1.
    + destruct (andb (Nat.eqb s 0) (Nat.eqb c 0)); cbn; discriminate 1.
Qed.

(* A decision-relevant challenge withholds the verdict: no disputed row is ever
   decisive. This is the property the re-pricing exists to keep. *)
Theorem dispute_relevant_is_partial :
  forall s c ds dc,
    cell_rule (decide_cell s c ds dc) = RDisputeRelevant ->
    cell_status (decide_cell s c ds dc) = TPartial.
Proof.
  intros s c ds dc. unfold decide_cell.
  destruct (dispute_relevant s c ds dc).
  - intros _. reflexivity.
  - cbn. intro H. destruct (label_rule_not_dispute s c H).
Qed.

(* The status is always either the undisputed label or PARTIAL, so the dispute
   rule can never *promote* a verdict. *)
Theorem status_is_label_or_partial :
  forall s c ds dc,
    cell_status (decide_cell s c ds dc) = label_status s c \/
    cell_status (decide_cell s c ds dc) = TPartial.
Proof.
  intros s c ds dc. unfold decide_cell.
  destruct (dispute_relevant s c ds dc); cbn; [right | left]; reflexivity.
Qed.

(* With nothing challenged, the cell is the label and the score is the formula. *)
Theorem undisputed_cell_is_the_label :
  forall s c,
    cell_status (decide_cell s c 0 0) = label_status s c /\
    cell_num (decide_cell s c 0 0) = score_num_t s c /\
    cell_den (decide_cell s c 0 0) = score_den_t s c /\
    cell_eff_s (decide_cell s c 0 0) = s /\
    cell_eff_c (decide_cell s c 0 0) = c.
Proof.
  intros s c. unfold decide_cell, dispute_relevant.
  simpl. repeat split; reflexivity.
Qed.

(* ================================================================== *)
(* The grid, and the table it emits                                    *)
(* ================================================================== *)

Definition grid_axis : list nat := [0; 1; 2; 3; 4; 5; 6]%nat.
Definition dispute_axis : list nat := [0; 1; 2]%nat.

Definition grid : list (nat * nat * nat * nat) :=
  flat_map (fun s =>
    flat_map (fun c =>
      flat_map (fun ds =>
        map (fun dc => (s, c, ds, dc)) dispute_axis) dispute_axis) grid_axis)
    grid_axis.

Definition cells : list cell :=
  map (fun p => let '(s, c, ds, dc) := p in decide_cell s c ds dc) grid.

(* One row, as non-negative integers only: `vm_compute` prints these as plain
   decimals, so the extractor needs no sign handling. The numerator is biased by
   8 (its range on this grid is -8..8, since s + ds <= 8), which the Python side
   subtracts back off. *)
Definition emit_cell (x : cell) : list nat :=
  [ cell_s x; cell_c x; cell_ds x; cell_dc x;
    cell_eff_s x; cell_eff_c x;
    Z.to_nat (cell_num x + 8); Z.to_nat (cell_den x);
    tstatus_code (cell_status x); trule_code (cell_rule x) ].

Definition table : list (list nat) := map emit_cell cells.

(* The code-to-name legend, emitted in constructor order so the Python side can
   check it invented no numbering of its own. *)
Definition status_codes : list nat :=
  map tstatus_code [TSupported; TPartial; TContradicted; TInsufficient].

Definition rule_codes : list nat :=
  map trule_code [RSupported; RContradicted; RNoEvidence; RBalanced; RDisputeRelevant].

Redirect "decision-table" Eval vm_compute in table.
Redirect "legend" Eval vm_compute in (status_codes, rule_codes).

(* ---- The grid is the whole modelled domain, checked by computation ---- *)

Theorem grid_size : length grid = 441%nat.
Proof. vm_compute. reflexivity. Qed.

Theorem table_size : length table = 441%nat.
Proof. vm_compute. reflexivity. Qed.

(* Exhaustive, not sampled: the coordinates `decide_cell` was run on are exactly
   the 441 points of 0..6 x 0..6 x 0..2 x 0..2, in that nesting order. A row
   dropped, duplicated or reordered by an edit to `grid` breaks this. *)
Theorem grid_is_the_full_product :
  map (fun x => (cell_s x, cell_c x, cell_ds x, cell_dc x)) cells = grid.
Proof. vm_compute. reflexivity. Qed.

(* ================================================================== *)
(* The switch point, proved here as well as discharged by z3           *)
(* ================================================================== *)

(* `decide(2, 0, disputed_contradiction=1)` reports a *lower* score than
   `decide(1, 0, disputed_contradiction=1)`: one more supporting group, a smaller
   number. Cross-multiplied by the (positive) denominators. *)
Theorem switch_point_is_not_monotone :
  (cell_num (decide_cell 2 0 0 1) * cell_den (decide_cell 1 0 0 1)
   < cell_num (decide_cell 1 0 0 1) * cell_den (decide_cell 2 0 0 1))%Z.
(* `<` on Z reduces to `(x ?= y) = Lt`, so the closed instance computes to
   `Lt = Lt`; if the numbers were the other way round it would compute to
   `Gt = Lt` and `reflexivity` would fail. *)
Proof. vm_compute. reflexivity. Qed.

(* And the two rows the switch point is made of, stated as numbers. *)
Theorem switch_point_values :
  (cell_status (decide_cell 1 0 0 1) = TPartial /\
   cell_num (decide_cell 1 0 0 1) = 1%Z /\
   cell_den (decide_cell 1 0 0 1) = 2%Z) /\
  (cell_status (decide_cell 2 0 0 1) = TPartial /\
   cell_rule (decide_cell 2 0 0 1) = RDisputeRelevant /\
   cell_num (decide_cell 2 0 0 1) = 1%Z /\
   cell_den (decide_cell 2 0 0 1) = 4%Z).
Proof. vm_compute. repeat split; reflexivity. Qed.
