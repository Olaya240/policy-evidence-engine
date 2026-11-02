(* Bilattice.v — the four-valued carrier B4 = P({T,F}) and its two orders.

   Coq 8.18, standard library only (no Mathlib, no extra packages).
   Build with:  coqc Bilattice.v

   Why this file.  ct3/StanceAlgebra.v §6 proves that the scalar report in
   backend/app/decision_table.py cannot be monotone in support and honest about
   a withheld verdict at the same time: `no_policy_keeps_monotonicity_and_integrity`
   forces a choice, and the shipped table chose integrity (decision_table.py
   lines 282-290, where the reported magnitude is `score(effective_s,
   effective_c)` at line 293).  That is a dilemma about a *one-dimensional*
   report.  A verdict has two independent dimensions: which direction the
   evidence certifies (truth) and how much the evidence settles
   (information).  The carrier of two independent two-valued judgements is
   Belnap's FOUR, and this file states it as a set of truth values.

   Representation.  B4 is literally P({T,F}): a value is the pair of booleans
   recording which of the two truth values the evidence assigns.  The four
   subsets are T = {T}, F = {F}, Both = {T,F}, Neither = {}.

   The two orders, stated precisely (this is the part the brief for this wave
   got wrong, and the correction is load-bearing — see Bilattice_facts.md):

     truth order  x <=t y  iff  Tr(x) c Tr(y)  and  Fa(y) c Fa(x)
                  (y is at least as true as x, i.e. x entails y)
                  Neither and Both are incomparable, F is bottom, T is top.

     information order  x <=i y  iff  Tr(x) c Tr(y)  and  Fa(x) c Fa(y)
                  (y says everything x says and possibly more)
                  T and F are incomparable, Neither is bottom, Both is top.

   So `Both` is top in information, and it is *not* top in truth: T is.  A
   value that is both true and false is maximally informed and not at all
   determinate, which is exactly the distinction the scalar `score` destroys.

   What is modelled, and what is not.  The carrier is the pair of truth
   assignments a report makes, not any evidence, phrase or score.  Nothing
   here says a report's two coordinates are correct; ct3/IntervalReport.v is
   what connects them to the arithmetic of the counts, and
   Bilattice_facts.md states the assumptions.
*)

Require Import Bool.

(* ================================================================== *)
(* 1. The carrier: a pair of decidable memberships, i.e. P({T,F})      *)
(* ================================================================== *)

Record B4 : Type := mkB4 {
  holds_T : bool;   (* is T in the subset? *)
  holds_F : bool    (* is F in the subset? *)
}.

Definition T : B4 := mkB4 true false.
Definition F : B4 := mkB4 false true.
Definition Both : B4 := mkB4 true true.
Definition Neither : B4 := mkB4 false false.

(* The four values are distinct. *)
Lemma B4_four_distinct :
  T <> F /\ T <> Both /\ T <> Neither /\
  F <> Both /\ F <> Neither /\ Both <> Neither.
Proof. repeat split; discriminate. Qed.

(* Two values are equal when they assign the same truth values.  Stated as a
   usable introduction rule rather than as functional extensionality. *)
Lemma B4_eq_intro : forall x y : B4,
  holds_T x = holds_T y -> holds_F x = holds_F y -> x = y.
Proof. intros [tx fx] [ty fy]. simpl. intros <- <-. reflexivity. Qed.

(* ================================================================== *)
(* 2. The truth order: entailment                                      *)
(* ================================================================== *)

(* x <=t y  iff  everything x calls true y calls true, and everything y calls
   false x calls false.  Informally: x's verdict is subsumed by y's. *)
Definition le_t (x y : B4) : Prop :=
  (holds_T x = true -> holds_T y = true) /\
  (holds_F y = true -> holds_F x = true).

(* The same relation as a boolean, so that every law below is a finite case
   analysis rather than a proof search. *)
Definition le_t_b (x y : B4) : bool :=
  (negb (holds_T x) || holds_T y) && (negb (holds_F y) || holds_F x).

Lemma le_t_b_spec : forall x y, le_t_b x y = true <-> le_t x y.
Proof.
  intros [tx fx] [ty fy]. unfold le_t_b, le_t. simpl.
  destruct tx, ty, fx, fy; simpl; intuition (try discriminate; try reflexivity).
Qed.

Lemma le_t_b_refl : forall x, le_t_b x x = true.
Proof. intros [tx fx]. unfold le_t_b. simpl. destruct tx, fx; reflexivity. Qed.

Lemma le_t_b_antisym :
  forall x y, le_t_b x y = true -> le_t_b y x = true -> x = y.
Proof.
  intros [tx fx] [ty fy]. unfold le_t_b. simpl.
  destruct tx, ty, fx, fy; simpl; intros H1 H2;
    try discriminate H1; try discriminate H2; reflexivity.
Qed.

Lemma le_t_b_trans :
  forall x y z,
    le_t_b x y = true -> le_t_b y z = true -> le_t_b x z = true.
Proof.
  intros [tx fx] [ty fy] [tz fz]. unfold le_t_b. simpl.
  destruct tx, ty, tz, fx, fy, fz; simpl; intros H1 H2;
    try discriminate H1; try discriminate H2; reflexivity.
Qed.

Lemma le_t_refl : forall x, le_t x x.
Proof. intro x. apply le_t_b_spec. apply le_t_b_refl. Qed.

Lemma le_t_antisym : forall x y, le_t x y -> le_t y x -> x = y.
Proof.
  intros x y Hx Hy.
  apply le_t_b_antisym with (x := x) (y := y).
  - apply le_t_b_spec; exact Hx.
  - apply le_t_b_spec; exact Hy.
Qed.

Lemma le_t_trans : forall x y z, le_t x y -> le_t y z -> le_t x z.
Proof.
  intros x y z Hxy Hyz.
  apply le_t_b_spec.
  apply (le_t_b_trans x y z); apply le_t_b_spec; assumption.
Qed.

(* ================================================================== *)
(* 3. The information order: knowledge                                 *)
(* ================================================================== *)

Definition le_i (x y : B4) : Prop :=
  (holds_T x = true -> holds_T y = true) /\
  (holds_F x = true -> holds_F y = true).

Definition le_i_b (x y : B4) : bool :=
  (negb (holds_T x) || holds_T y) && (negb (holds_F x) || holds_F y).

Lemma le_i_b_spec : forall x y, le_i_b x y = true <-> le_i x y.
Proof.
  intros [tx fx] [ty fy]. unfold le_i_b, le_i. simpl.
  destruct tx, ty, fx, fy; simpl; intuition (try discriminate; try reflexivity).
Qed.

Lemma le_i_b_refl : forall x, le_i_b x x = true.
Proof. intros [tx fx]. unfold le_i_b. simpl. destruct tx, fx; reflexivity. Qed.

Lemma le_i_b_antisym :
  forall x y, le_i_b x y = true -> le_i_b y x = true -> x = y.
Proof.
  intros [tx fx] [ty fy]. unfold le_i_b. simpl.
  destruct tx, ty, fx, fy; simpl; intros H1 H2;
    try discriminate H1; try discriminate H2; reflexivity.
Qed.

Lemma le_i_b_trans :
  forall x y z,
    le_i_b x y = true -> le_i_b y z = true -> le_i_b x z = true.
Proof.
  intros [tx fx] [ty fy] [tz fz]. unfold le_i_b. simpl.
  destruct tx, ty, tz, fx, fy, fz; simpl; intros H1 H2;
    try discriminate H1; try discriminate H2; reflexivity.
Qed.

Lemma le_i_refl : forall x, le_i x x.
Proof. intro x. apply le_i_b_spec. apply le_i_b_refl. Qed.

Lemma le_i_antisym : forall x y, le_i x y -> le_i y x -> x = y.
Proof.
  intros x y Hx Hy.
  apply le_i_b_antisym with (x := x) (y := y);
    apply le_i_b_spec; assumption.
Qed.

Lemma le_i_trans : forall x y z, le_i x y -> le_i y z -> le_i x z.
Proof.
  intros x y z Hxy Hyz. apply le_i_b_spec.
  apply (le_i_b_trans x y z); apply le_i_b_spec; assumption.
Qed.

(* ================================================================== *)
(* 4. Both orders are lattices                                        *)
(* ================================================================== *)

(* Truth order: conjunction is the meet, disjunction is the join. *)
Definition meet_t (x y : B4) : B4 :=
  mkB4 (andb (holds_T x) (holds_T y)) (orb (holds_F x) (holds_F y)).

Definition join_t (x y : B4) : B4 :=
  mkB4 (orb (holds_T x) (holds_T y)) (andb (holds_F x) (holds_F y)).

(* Information order: union of what is known is the join, agreement is the
   meet.  `compose` is the join: a second report can only add information. *)
Definition meet_i (x y : B4) : B4 :=
  mkB4 (andb (holds_T x) (holds_T y)) (andb (holds_F x) (holds_F y)).

Definition join_i (x y : B4) : B4 :=
  mkB4 (orb (holds_T x) (holds_T y)) (orb (holds_F x) (holds_F y)).

Lemma le_t_join_l : forall x y, le_t x (join_t x y).
Proof.
  intros [tx fx] [ty fy]. apply le_t_b_spec. unfold le_t_b, join_t. simpl.
  destruct tx, ty, fx, fy; reflexivity.
Qed.

Lemma le_t_join_r : forall x y, le_t y (join_t x y).
Proof.
  intros [tx fx] [ty fy]. apply le_t_b_spec. unfold le_t_b, join_t. simpl.
  destruct tx, ty, fx, fy; reflexivity.
Qed.

Lemma le_t_join_ub : forall x y z, le_t x z -> le_t y z -> le_t (join_t x y) z.
Proof.
  intros [tx fx] [ty fy] [tz fz] Hx Hy. unfold le_t, join_t in *. simpl in *.
  split.
  - intros H. apply orb_true_iff in H. destruct H as [H | H].
    + exact (proj1 Hx H).
    + exact (proj1 Hy H).
  - intros Hf. apply andb_true_iff. split.
    + exact (proj2 Hx Hf).
    + exact (proj2 Hy Hf).
Qed.

Lemma le_t_meet_l : forall x y, le_t (meet_t x y) x.
Proof.
  intros [tx fx] [ty fy]. apply le_t_b_spec. unfold le_t_b, meet_t. simpl.
  destruct tx, ty, fx, fy; reflexivity.
Qed.

Lemma le_t_meet_r : forall x y, le_t (meet_t x y) y.
Proof.
  intros [tx fx] [ty fy]. apply le_t_b_spec. unfold le_t_b, meet_t. simpl.
  destruct tx, ty, fx, fy; reflexivity.
Qed.

Lemma le_t_meet_lb : forall x y z, le_t z x -> le_t z y -> le_t z (meet_t x y).
Proof.
  intros [tx fx] [ty fy] [tz fz] Hx Hy. unfold le_t, meet_t in *. simpl in *.
  split.
  - intros Ht. apply andb_true_iff. split.
    + exact (proj1 Hx Ht).
    + exact (proj1 Hy Ht).
  - intros Hf. apply orb_true_iff in Hf. destruct Hf as [Hf | Hf].
    + exact (proj2 Hx Hf).
    + exact (proj2 Hy Hf).
Qed.

(* A lattice law bundle, so that "is a lattice" is a record rather than a
   conjunction that a tactic has to re-split. *)
Record lattice_laws (le : B4 -> B4 -> Prop)
                    (meet join : B4 -> B4 -> B4) : Prop := {
  law_refl : forall x, le x x;
  law_antisym : forall x y, le x y -> le y x -> x = y;
  law_trans : forall x y z, le x y -> le y z -> le x z;
  law_join_ub_l : forall x y, le x (join x y);
  law_join_ub_r : forall x y, le y (join x y);
  law_join_lub : forall x y z, le x z -> le y z -> le (join x y) z;
  law_meet_lb_l : forall x y, le (meet x y) x;
  law_meet_lb_r : forall x y, le (meet x y) y;
  law_meet_glb : forall x y z, le z x -> le z y -> le z (meet x y)
}.

(* `join_t` and `meet_t` are the least upper bound and greatest lower bound,
   so (B4, <=t) is a lattice. *)
Theorem truth_is_lattice : lattice_laws le_t meet_t join_t.
Proof.
  constructor.
  - apply le_t_refl.
  - apply le_t_antisym.
  - apply le_t_trans.
  - apply le_t_join_l.
  - apply le_t_join_r.
  - apply le_t_join_ub.
  - apply le_t_meet_l.
  - apply le_t_meet_r.
  - apply le_t_meet_lb.
Qed.

Lemma le_i_join_l : forall x y, le_i x (join_i x y).
Proof.
  intros [tx fx] [ty fy]. apply le_i_b_spec. unfold le_i_b, join_i. simpl.
  destruct tx, ty, fx, fy; reflexivity.
Qed.

Lemma le_i_join_r : forall x y, le_i y (join_i x y).
Proof.
  intros [tx fx] [ty fy]. apply le_i_b_spec. unfold le_i_b, join_i. simpl.
  destruct tx, ty, fx, fy; reflexivity.
Qed.

Lemma le_i_join_ub : forall x y z, le_i x z -> le_i y z -> le_i (join_i x y) z.
Proof.
  intros [tx fx] [ty fy] [tz fz] Hx Hy. unfold le_i, join_i in *. simpl in *.
  split.
  - intros H. apply orb_true_iff in H. destruct H as [H | H].
    + exact (proj1 Hx H).
    + exact (proj1 Hy H).
  - intros H. apply orb_true_iff in H. destruct H as [H | H].
    + exact (proj2 Hx H).
    + exact (proj2 Hy H).
Qed.

Lemma le_i_meet_l : forall x y, le_i (meet_i x y) x.
Proof.
  intros [tx fx] [ty fy]. apply le_i_b_spec. unfold le_i_b, meet_i. simpl.
  destruct tx, ty, fx, fy; reflexivity.
Qed.

Lemma le_i_meet_r : forall x y, le_i (meet_i x y) y.
Proof.
  intros [tx fx] [ty fy]. apply le_i_b_spec. unfold le_i_b, meet_i. simpl.
  destruct tx, ty, fx, fy; reflexivity.
Qed.

Lemma le_i_meet_lb : forall x y z, le_i z x -> le_i z y -> le_i z (meet_i x y).
Proof.
  intros [tx fx] [ty fy] [tz fz] Hx Hy. unfold le_i, meet_i in *. simpl in *.
  split.
  - intros Ht. apply andb_true_iff. split.
    + exact (proj1 Hx Ht).
    + exact (proj1 Hy Ht).
  - intros Hf. apply andb_true_iff. split.
    + exact (proj2 Hx Hf).
    + exact (proj2 Hy Hf).
Qed.

Theorem information_is_lattice : lattice_laws le_i meet_i join_i.
Proof.
  constructor.
  - apply le_i_refl.
  - apply le_i_antisym.
  - apply le_i_trans.
  - apply le_i_join_l.
  - apply le_i_join_r.
  - apply le_i_join_ub.
  - apply le_i_meet_l.
  - apply le_i_meet_r.
  - apply le_i_meet_lb.
Qed.

(* ================================================================== *)
(* 5. The interaction of the two orders                                *)
(* ================================================================== *)

(* Both is the top of the information order: a conflict knows everything the
   two sides know. *)
Theorem Both_top_information : forall x, le_i x Both.
Proof.
  intros [tx fx]. apply le_i_b_spec. unfold le_i_b, Both. simpl.
  destruct tx, fx; reflexivity.
Qed.

(* Neither is the bottom of the information order: nothing is known. *)
Theorem Neither_bottom_information : forall x, le_i Neither x.
Proof.
  intros [tx fx]. apply le_i_b_spec. unfold le_i_b, Neither. simpl.
  destruct tx, fx; reflexivity.
Qed.

(* T is the top of the truth order, F is the bottom.  Informally: the true
   entails everything true, the false is entailed by everything. *)
Theorem T_top_truth : forall x, le_t x T.
Proof.
  intros [tx fx]. apply le_t_b_spec. unfold le_t_b, T. simpl.
  destruct tx, fx; reflexivity.
Qed.

Theorem F_bottom_truth : forall x, le_t F x.
Proof.
  intros [tx fx]. apply le_t_b_spec. unfold le_t_b, F. simpl.
  destruct tx, fx; reflexivity.
Qed.

(* The correction to the brief: Both is NOT top in the truth order.  It is
   below T, and T is not below it, so the truth top is T. *)
Lemma Both_below_T_truth : le_t Both T.
Proof. apply le_t_b_spec. reflexivity. Qed.

Lemma T_not_below_Both_truth : ~ le_t T Both.
Proof.
  intro H. apply le_t_b_spec in H. vm_compute in H. discriminate H.
Qed.

Theorem Both_not_top_truth : ~ (forall x, le_t x Both).
Proof. intro H. exact (T_not_below_Both_truth (H T)). Qed.

(* And Neither is NOT the truth bottom: F is below it, not the other way. *)
Lemma F_below_Neither_truth : le_t F Neither.
Proof. apply le_t_b_spec. reflexivity. Qed.

Lemma Neither_not_below_F_truth : ~ le_t Neither F.
Proof.
  intro H. apply le_t_b_spec in H. vm_compute in H. discriminate H.
Qed.

Theorem Neither_not_bottom_truth : ~ (forall x, le_t Neither x).
Proof. intro H. exact (Neither_not_below_F_truth (H F)). Qed.

(* Both and Neither are incomparable in the truth order, and their truth
   meet/join are F/T: they are the two middle elements of the truth diamond. *)
Theorem Both_Neither_incomparable_truth :
  ~ le_t Both Neither /\ ~ le_t Neither Both.
Proof.
  split.
  - intro H. apply le_t_b_spec in H. vm_compute in H. discriminate H.
  - intro H. apply le_t_b_spec in H. vm_compute in H. discriminate H.
Qed.

Theorem belnap_truth_tables :
  meet_t Both Neither = F /\ join_t Both Neither = T.
Proof. split; reflexivity. Qed.

(* T and F are incomparable in the information order, and comparable in the
   truth order: the two orders are genuinely different. *)
Theorem T_F_incomparable_information :
  ~ le_i T F /\ ~ le_i F T.
Proof.
  split.
  - intro H. apply le_i_b_spec in H. vm_compute in H. discriminate H.
  - intro H. apply le_i_b_spec in H. vm_compute in H. discriminate H.
Qed.

Lemma F_below_T_truth : le_t F T.
Proof. apply le_t_b_spec. reflexivity. Qed.

Theorem orders_differ :
  (exists x y, le_t x y /\ ~ le_i x y) /\
  (exists x y, le_i x y /\ ~ le_t x y).
Proof.
  split.
  - exists Both, T. split; [apply Both_below_T_truth |].
    intro H. apply le_i_b_spec in H. vm_compute in H. discriminate H.
  - exists T, Both. split; [apply Both_top_information |].
    exact T_not_below_Both_truth.
Qed.

(* Composition is information join, and it is monotone in BOTH orders: adding
   evidence cannot lower a value in either. *)
Theorem join_i_monotone_information :
  forall a b c d, le_i a b -> le_i c d -> le_i (join_i a c) (join_i b d).
Proof.
  intros a b c d Ha Hc. unfold le_i, join_i in *. simpl in *.
  split.
  - intros H. apply orb_true_iff in H. destruct H as [H | H].
    + apply orb_true_iff. left. exact (proj1 Ha H).
    + apply orb_true_iff. right. exact (proj1 Hc H).
  - intros H. apply orb_true_iff in H. destruct H as [H | H].
    + apply orb_true_iff. left. exact (proj2 Ha H).
    + apply orb_true_iff. right. exact (proj2 Hc H).
Qed.

Theorem join_i_monotone_truth :
  forall a b c d, le_t a b -> le_t c d -> le_t (join_i a c) (join_i b d).
Proof.
  intros a b c d Ha Hc. unfold le_t, join_i in *. simpl in *.
  split.
  - intros H. apply orb_true_iff in H. destruct H as [H | H].
    + apply orb_true_iff. left. exact (proj1 Ha H).
    + apply orb_true_iff. right. exact (proj1 Hc H).
  - intros H. apply orb_true_iff in H. destruct H as [H | H].
    + apply orb_true_iff. left. exact (proj2 Ha H).
    + apply orb_true_iff. right. exact (proj2 Hc H).
Qed.

(* ================================================================== *)
(* 6. Negation                                                         *)
(* ================================================================== *)

(* Negation swaps the two truth values and leaves the presence/absence of
   information alone: it is the set-complement on {T,F} unioned with swap,
   which on P({T,F}) is just the swap of the two coordinates. *)
Definition neg (x : B4) : B4 := mkB4 (holds_F x) (holds_T x).

Theorem neg_involution : forall x, neg (neg x) = x.
Proof. intros [tx fx]. reflexivity. Qed.

Theorem neg_swaps : neg T = F /\ neg F = T.
Proof. split; reflexivity. Qed.

(* Paraconsistent: the value that is both true and false is its own negation. *)
Theorem neg_fixes_paraconsistent : neg Both = Both.
Proof. reflexivity. Qed.

(* Paracomplete: the value that is neither is its own negation. *)
Theorem neg_fixes_paracomplete : neg Neither = Neither.
Proof. reflexivity. Qed.

(* Negation is antitone for the truth order and an automorphism for the
   information order: it reverses the entailment verdict and preserves the
   amount of information.  Both facts are what make it `negation` rather than
   a relabelling. *)
Theorem neg_antitone_truth : forall x y, le_t x y -> le_t (neg y) (neg x).
Proof.
  intros [tx fx] [ty fy] H. unfold le_t, neg in *. simpl in *.
  split; [exact (proj2 H) | exact (proj1 H)].
Qed.

Theorem neg_monotone_information : forall x y, le_i x y -> le_i (neg x) (neg y).
Proof.
  intros [tx fx] [ty fy] H. unfold le_i, neg in *. simpl in *.
  split; [exact (proj2 H) | exact (proj1 H)].
Qed.

Theorem neg_join_i : forall x y, neg (join_i x y) = join_i (neg x) (neg y).
Proof. intros [tx fx] [ty fy]. reflexivity. Qed.

(* ================================================================== *)
(* 7. Conflict is not support                                           *)
(* ================================================================== *)

(* Truth-determinacy: the report assigns T and does not assign F. *)
Definition is_true (x : B4) : Prop := holds_T x = true /\ holds_F x = false.

Theorem T_is_true : is_true T.
Proof. split; reflexivity. Qed.

Lemma Both_not_true : ~ is_true Both.
Proof. intros [_ H]. discriminate H. Qed.

Lemma Neither_not_true : ~ is_true Neither.
Proof. intros [H _]. discriminate H. Qed.

(* The headline.  `Both` is the top of the information order — it is the most
   informed value there is, the join of the two directions — and it is still
   not a support verdict: it is not T, it is not truth-determinate, and it is
   not the truth top.  Information and truth are independent coordinates, so
   "the evidence conflicts" can never be read off as "the evidence supports". *)
Theorem conflict_is_not_support :
  (forall x, le_i x Both) /\
  ~ is_true Both /\
  Both <> T /\
  ~ (forall x, le_t x Both).
Proof.
  split; [apply Both_top_information | split; [apply Both_not_true | split]].
  - discriminate.
  - apply Both_not_top_truth.
Qed.

(* The mirror statement: the absence of any verdict is the information bottom
   and is equally not a support verdict, so neither abstention can be
   advertised as one. *)
Theorem absence_is_not_support :
  (forall x, le_i Neither x) /\ ~ is_true Neither.
Proof. split; [apply Neither_bottom_information | apply Neither_not_true]. Qed.

(* ================================================================== *)
(* 8. Assumptions audit                                                *)
(* ================================================================== *)

(* Printed at compile time so the absence of axioms is demonstrated by the
   build rather than asserted.  Every line should read
   "Closed under the global context". *)
Print Assumptions neg_involution.
Print Assumptions neg_fixes_paraconsistent.
Print Assumptions neg_fixes_paracomplete.
Print Assumptions Both_top_information.
Print Assumptions conflict_is_not_support.
Print Assumptions join_i_monotone_truth.
Print Assumptions join_i_monotone_information.
Print Assumptions truth_is_lattice.
Print Assumptions information_is_lattice.
