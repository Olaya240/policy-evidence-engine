(* DecisionTable.v — machine-checked comparison of the shipped claim decision
   table (v1) and the proposed replacement (v2).

   Coq 8.18, standard library only (no Mathlib, no extra packages).
   Build with:  coqc DecisionTable.v

   Why Coq and not Lean: the Lean 4.35 toolchain on this machine has no Mathlib,
   and core Lean has no `ring`/`nlinarith`, so the polynomial identities that
   carry monotonicity cannot be proved there. Coq ships `ring` + `lia`.

   Model.  A claim's directional evidence reduces to two counts:
     s = independent source groups holding a fresh, accepted, undisputed record
         whose stance SUPPORTS the hypothesis
     c = the same for stance CONTRADICTS

   Stale, unverified, restricted, neutral and disputed records are excluded from
   the counts and carried as text. That is what makes staleness and input order
   provable rather than asserted: the score's domain does not contain them.

   v1 is transcribed from backend/app/engine.py::_summarize_status_decision at
   commit 8c1b808, restricted to the branches reachable from (s, c):
      s>0 /\ c>0        -> Mixed         52
      s>0 /\ c=0 /\ s>=2-> Supported     68   (78 when departments differ)
      s>0 /\ c=0 /\ s=1 -> Mixed         55
      s=0 /\ c>=2       -> Contradicted  68
      s=0 /\ c=1        -> Contradicted  58
      s=0 /\ c=0        -> Insufficient  20 / 25 / 30
   Stale accepted support is a separate arm evaluated *before* the Supported arm;
   that ordering is the mechanism of the third defect.
*)

Require Import ZArith Lia List Bool.
Import ListNotations.

Open Scope Z_scope.

Inductive status : Type := Supported | Mixed | Contradicted | Insufficient.

(* ================================================================== *)
(* v1, the shipped table                                              *)
(* ================================================================== *)

Definition v1_status (s c : nat) : status :=
  if andb (Nat.ltb 0 s) (Nat.ltb 0 c) then Mixed
  else if Nat.ltb 0 s then (if Nat.leb 2 s then Supported else Mixed)
  else if Nat.ltb 0 c then Contradicted
  else Insufficient.

Definition v1_score (s c : nat) : Z :=
  if andb (Nat.ltb 0 s) (Nat.ltb 0 c) then 52
  else if Nat.ltb 0 s then (if Nat.leb 2 s then 68 else 55)
  else if Nat.ltb 0 c then (if Nat.leb 2 c then 68 else 58)
  else 20.

(* v1 with one stale accepted support present: STATUS.FRESH_WITH_STALE_CONTEXT
   fires before the Supported arm and pins 54. *)
Definition v1_score_with_stale (s c : nat) : Z :=
  if orb (Nat.ltb 0 s) (Nat.ltb 0 c) then 54 else v1_score s c.

(* ---- Defect 1: one number, two opposite meanings ---- *)

Theorem v1_collision :
  v1_score 2 0 = v1_score 0 2 /\ v1_status 2 0 <> v1_status 0 2.
Proof.
  split. vm_compute; reflexivity. vm_compute; discriminate.
Qed.

(* The collision is structural, not an artefact of the two-group row. *)
Theorem v1_collision_is_structural :
  forall s c, (2 <= s)%nat -> (c = 0)%nat -> v1_score s c = 68.
Proof.
  intros s c hs hc. subst c.
  unfold v1_score.
  replace (Nat.ltb 0 s) with true by (symmetry; apply Nat.ltb_lt; lia).
  replace (andb true (Nat.ltb 0 0)) with false by reflexivity.
  replace (Nat.leb 2 s) with true by (symmetry; apply Nat.leb_le; lia).
  reflexivity.
Qed.

(* ---- Defect 2: adding a supporting group lowers the number ---- *)

Theorem v1_inversion :
  v1_score 0 1 = 58 /\ v1_score 1 1 = 52 /\ v1_score 1 1 < v1_score 0 1.
Proof.
  split. vm_compute; reflexivity.
  split. vm_compute; reflexivity.
  vm_compute; auto.
Qed.

(* ---- Defect 3: a stale record demotes fresh corroboration ---- *)

Theorem v1_stale_demotion :
  v1_score 2 0 = 68 /\ v1_score_with_stale 2 0 = 54.
Proof.
  split. vm_compute; reflexivity. vm_compute; reflexivity.
Qed.

(* The drag does not weaken with more fresh corroboration: it is pinned at 54. *)
Theorem v1_stale_demotion_is_flat :
  forall s, (1 <= s)%nat -> v1_score_with_stale s 0 = 54.
Proof.
  intros s hs. unfold v1_score_with_stale.
  replace (Nat.ltb 0 s) with true by (symmetry; apply Nat.ltb_lt; lia).
  reflexivity.
Qed.

(* ================================================================== *)
(* v2, the proposed table                                             *)
(* ================================================================== *)

(*   score(s, c) = (s - c) / (s + c + 1),  range (-1, 1).
     A single source can never exceed 1/2 in magnitude.
     Numerator and denominator stay separate so every comparison is
     cross-multiplication and every proof can be linear. *)

Definition score_num (s c : nat) : Z := Z.of_nat s - Z.of_nat c.
Definition score_den (s c : nat) : Z := Z.of_nat s + Z.of_nat c + 1.

(* score >= 1/2  <=>  2(s-c) >= s+c+1  <=>  s >= 3c+1 *)
Definition supported (s c : nat) : Prop := (2 <= s)%nat /\ (3 * c + 1 <= s)%nat.
(* score <= -1/2  <=>  2(c-s) >= s+c+1  <=>  c >= 3s+1 *)
Definition contradicted (s c : nat) : Prop := (3 * s + 1 <= c)%nat.
(* Directional evidence on both sides. Reported as its own field so a contested
   claim is never silent, whatever label its weight earns. *)
Definition contested (s c : nat) : Prop := (0 < s)%nat /\ (0 < c)%nat.

Definition supported_b (s c : nat) : bool :=
  andb (Nat.leb 2 s) (Nat.leb (3 * c + 1) s).
Definition contradicted_b (s c : nat) : bool := Nat.leb (3 * s + 1) c.

Definition v2_status (s c : nat) : status :=
  if supported_b s c then Supported
  else if contradicted_b s c then Contradicted
  else if andb (Nat.eqb s 0) (Nat.eqb c 0) then Insufficient
  else Mixed.

Lemma supported_b_spec : forall s c, supported_b s c = true <-> supported s c.
Proof.
  intros s c. unfold supported_b, supported.
  rewrite andb_true_iff, !Nat.leb_le. lia.
Qed.

Lemma contradicted_b_spec : forall s c, contradicted_b s c = true <-> contradicted s c.
Proof.
  intros s c. unfold contradicted_b, contradicted.
  rewrite Nat.leb_le. lia.
Qed.

(* ---- Property 1: the labels are mutually exclusive ---- *)

Theorem v2_states_exclusive : forall s c, ~ (supported s c /\ contradicted s c).
Proof. intros s c [Hs Hc]. unfold supported in Hs. unfold contradicted in Hc. lia. Qed.

Theorem v2_status_single :
  forall s c, supported s c -> ~ contradicted s c.
Proof. intros s c Hs Hc. exact (v2_states_exclusive s c (conj Hs Hc)). Qed.

(* The sign invariant: a decisive label always carries evidence in its own
   direction. This is the mechanism the collision fix rests on, so it is
   proved rather than asserted. Note what is NOT modelled: disputed evidence
   and the decision-relevance downgrade have no counterpart in this file. *)
Theorem v2_supported_positive :
  forall s c, supported s c -> (0 < score_num s c)%Z.
Proof.
  intros s c [_ H]. unfold score_num.
  assert (Hc : (Z.of_nat c < Z.of_nat s)%Z) by (apply Nat2Z.inj_lt; lia).
  lia.
Qed.

Theorem v2_contradicted_negative :
  forall s c, contradicted s c -> (score_num s c < 0)%Z.
Proof.
  intros s c H. unfold score_num, contradicted in *.
  assert (Hc : (Z.of_nat s < Z.of_nat c)%Z) by (apply Nat2Z.inj_lt; lia).
  lia.
Qed.

(* ---- Property 2: a single source is never decisive ---- *)

Theorem v2_single_source_is_partial : forall c, ~ supported 1 c.
Proof. intros c [H _]. unfold supported in H. lia. Qed.

(* A contested claim can only be Supported on a large imbalance: at least three
   contradiction groups plus one support group per contradicting group. Conflict
   is never hidden, it is priced. *)
Theorem v2_contested_needs_imbalance :
  forall s c, supported s c -> (0 < c)%nat -> (3 * c + 1 <= s)%nat.
Proof. intros s c [_ H] _. exact H. Qed.

(* ---- Property 3: the score is monotone in both directions ---- *)

(* Adding one support group changes the cross-multiplied comparison by exactly
   2c+1, whose sign cannot depend on the counts. *)
Lemma add_support_identity :
  forall s c, (Z.of_nat (S s) - Z.of_nat c) * (Z.of_nat s + Z.of_nat c + 1)
            - (Z.of_nat s - Z.of_nat c) * (Z.of_nat (S s) + Z.of_nat c + 1)
            = 2 * Z.of_nat c + 1.
Proof. intros s c. rewrite Nat2Z.inj_succ. ring. Qed.

Lemma add_contradiction_identity :
  forall s c, (Z.of_nat s - Z.of_nat c) * (Z.of_nat s + Z.of_nat (S c) + 1)
            - (Z.of_nat s - Z.of_nat (S c)) * (Z.of_nat s + Z.of_nat c + 1)
            = 2 * Z.of_nat s + 1.
Proof. intros s c. rewrite Nat2Z.inj_succ. ring. Qed.

(* Monotone support: one more independent supporting group strictly raises the
   score, for every fixed contradiction count. *)
Theorem v2_support_raises :
  forall s c, (score_num s c * score_den (S s) c
              < score_num (S s) c * score_den s c)%Z.
Proof.
  intros s c. unfold score_num, score_den.
  pose proof (add_support_identity s c) as H.
  assert (Hp : (0 < 2 * Z.of_nat c + 1)%Z) by lia.
  lia.
Qed.

(* Monotone contradiction: one more independent contradicting group strictly
   lowers the score, for every fixed support count. *)
Theorem v2_contradiction_lowers :
  forall s c, (score_num s (S c) * score_den s c
              < score_num s c * score_den s (S c))%Z.
Proof.
  intros s c. unfold score_num, score_den.
  pose proof (add_contradiction_identity s c) as H.
  assert (Hp : (0 < 2 * Z.of_nat s + 1)%Z) by lia.
  lia.
Qed.

(* The reported inversion, re-run against v2: adding the support moves the score
   up. Cross-multiplied comparison of (0,1) against (1,1). *)
Theorem v2_inversion_fixed :
  (score_num 0 1 * score_den 1 1 < score_num 1 1 * score_den 0 1)%Z.
Proof. vm_compute; auto. Qed.

(* The reported collision, re-run against v2: the labels cannot both apply and
   the equal-magnitude cases now differ in sign. *)
Theorem v2_collision_fixed :
  v2_status 2 0 = Supported /\ v2_status 0 2 = Contradicted /\
  (0 < score_num 2 0)%Z /\ (score_num 0 2 < 0)%Z.
Proof.
  repeat split; vm_compute; auto.
Qed.

(* ---- Property 4: staleness and order cannot move the number ---- *)

Record item : Type := mkItem {
  stance : bool;    (* true = SUPPORTS, false = CONTRADICTS *)
  stale  : bool;
  group  : nat
}.

(* Count fresh items per direction. `stale` is matched and discarded, so no
   stale record can reach the arithmetic. *)
Definition is_fresh_support (i : item) : bool := andb (stance i) (negb (stale i)).
Definition is_fresh_contradiction (i : item) : bool :=
  andb (negb (stance i)) (negb (stale i)).

Definition counts (l : list item) : nat * nat :=
  (length (filter is_fresh_support l), length (filter is_fresh_contradiction l)).

(* Stale invariance: appending a stale record of either stance leaves both
   counts, hence the score and the status, unchanged. This is the exact step v1
   takes at v1_stale_demotion. *)
Lemma filter_app_single :
  forall (f : item -> bool) l i, f i = false -> filter f (l ++ [i]) = filter f l.
Proof.
  intros f l i H. rewrite filter_app. simpl. rewrite H. simpl.
  rewrite app_nil_r. reflexivity.
Qed.

Theorem v2_stale_ignored :
  forall l i, stale i = true -> counts (l ++ [i]) = counts l.
Proof.
  intros l i Hs. unfold counts.
  assert (H1 : is_fresh_support i = false)
    by (unfold is_fresh_support; rewrite Hs; simpl; apply andb_false_r).
  assert (H2 : is_fresh_contradiction i = false)
    by (unfold is_fresh_contradiction; rewrite Hs; simpl; apply andb_false_r).
  rewrite (filter_app_single _ _ _ H1), (filter_app_single _ _ _ H2).
  reflexivity.
Qed.

(* Order invariance: interleaving two batches gives the same counts, so the
   emitted pair does not depend on the order evidence arrived in. *)
Theorem v2_order_irrelevant :
  forall a b, counts (a ++ b) = counts (b ++ a).
Proof.
  intros a b. unfold counts.
  rewrite !filter_app. simpl.
  rewrite !app_length.
  f_equal; lia.
Qed.

(* ---- Property 5: determinism, stated non-vacuously ---- *)

Theorem v2_deterministic :
  forall l1 l2, counts l1 = counts l2 ->
    v2_status (fst (counts l1)) (snd (counts l1))
    = v2_status (fst (counts l2)) (snd (counts l2)).
Proof. intros l1 l2 H. rewrite H. reflexivity. Qed.
