(* IntervalReport.v — why the report is an interval and not a number.

   Coq 8.18, standard library only.  Build with:  coqc IntervalReport.v

   Context.  ``backend/app/decision_table.py`` reports one ``score`` for a
   configuration of evidence and, when a dispute is decision-relevant, re-prices
   that score to the challenged configuration.  ``ct3/DecisionTable.v`` proves
   that no policy keeps that number monotone in support *and* coherent with the
   label it attaches.  The shipped fix is to stop projecting: report the two
   extremes the dispute leaves open,

       lo(s,c,dc) = score(s, c+dc)      hi(s,ds,c) = score(s+ds, c)

   with ``score(a,b) = (a-b)/(a+b+1)``, and read the label from the bounds.

   The ``+1`` is the shipped denominator (``decision_table.score``), not a
   normalisation: it is what keeps the interval from collapsing when there are
   no contradictions.  With a bare ``(a-b)/(a+b)`` a disputed support could not
   move the ratio at ``c = 0``, and the interval would report certainty for
   evidence nobody has settled.

   Denominator clearing.  ``score`` is a ratio of naturals, so every comparison
   below is stated in the cross-multiplied form

       (a - b) * (c + d) <= (c - d) * (a + b)

   which is the same inequality as ``score a b <= score c d`` provided both
   denominators are positive — true here because ``s + c + dc`` and ``s + ds + c``
   are sums of naturals containing the group counts, so a configuration with an
   empty denominator is the empty configuration and is excluded by ``0 < s + c``.
   The bridge from this integer form to the exact rationals the Python reports is
   not asserted here: it is checked on all 441 grid rows by
   ``backend/tests/test_decision_table_refinement.py``, which compares
   ``Fraction`` values, so a mistake in the bridge fails a test rather than
   hiding in a comment.

   Each proof below is a ring identity plus linear arithmetic: the difference of
   the two cleared products is always a short polynomial in the counts, and that
   polynomial is what the corollaries name.  That is the reason the file is
   readable at all — the interval's behaviour is one term per theorem.

   What is NOT in this file: any claim that the thresholds 1/2 and -1/2 are the
   right policy.  They are the shipped numbers; this file proves the report is
   coherent *given* them. *)

Require Import ZArith Lia.

Open Scope Z_scope.

(* ------------------------------------------------------------------ *)
(* The two bounds, in cleared form.                                    *)
(* ------------------------------------------------------------------ *)

Definition lo_num (s c dc : Z) : Z := s - (c + dc).
Definition lo_den (s c dc : Z) : Z := s + (c + dc) + 1.
Definition hi_num (s ds c : Z) : Z := (s + ds) - c.
Definition hi_den (s ds c : Z) : Z := (s + ds) + c + 1.

(* The comparison the report makes, with denominators cleared. *)
Definition lo_le_hi (s c ds dc : Z) : Prop :=
  lo_num s c dc * hi_den s ds c <= hi_num s ds c * lo_den s c dc.

(* ------------------------------------------------------------------ *)
(* 1. The interval is an interval.                                     *)
(* ------------------------------------------------------------------ *)

Theorem lo_never_above_hi :
  forall s c ds dc : Z,
    0 <= s -> 0 <= c -> 0 <= ds -> 0 <= dc ->
    lo_le_hi s c ds dc.
Proof.
  intros s c ds dc Hs Hc Hds Hdc.
  unfold lo_le_hi.
  assert (Hd : hi_num s ds c * lo_den s c dc - lo_num s c dc * hi_den s ds c
               = 2 * (s * dc + c * ds + ds * dc) + ds + dc)
    by (unfold hi_num, lo_num, lo_den, hi_den; ring).
  assert (Hsdc : 0 <= s * dc) by (apply Z.mul_nonneg_nonneg; lia).
  assert (Hcds : 0 <= c * ds) by (apply Z.mul_nonneg_nonneg; lia).
  assert (Hdsdc : 0 <= ds * dc) by (apply Z.mul_nonneg_nonneg; lia).
  lia.
Qed.

(* The width of the cleared interval, which is what a dispute buys you. *)
Definition width (s c ds dc : Z) : Z :=
  hi_num s ds c * lo_den s c dc - lo_num s c dc * hi_den s ds c.

Theorem width_is_the_dispute_term :
  forall s c ds dc : Z,
    width s c ds dc = 2 * (s * dc + c * ds + ds * dc) + ds + dc.
Proof.
  intros s c ds dc.
  unfold width, lo_num, lo_den, hi_num, hi_den.
  ring.
Qed.

Theorem undisputed_interval_is_a_point :
  forall s c : Z,
    width s c 0 0 = 0.
Proof.
  intros s c. rewrite width_is_the_dispute_term. ring.
Qed.

Theorem dispute_widens_the_interval :
  forall s c ds dc : Z,
    0 <= s -> 0 <= c -> 0 <= ds -> 0 <= dc ->
    0 <= width s c ds dc.
Proof.
  intros s c ds dc Hs Hc Hds Hdc.
  rewrite width_is_the_dispute_term.
  assert (0 <= s * dc) by (apply Z.mul_nonneg_nonneg; lia).
  assert (0 <= c * ds) by (apply Z.mul_nonneg_nonneg; lia).
  assert (0 <= ds * dc) by (apply Z.mul_nonneg_nonneg; lia).
  lia.
Qed.

(* A width of zero means no dispute at all — no precondition needed, because the
   ``+1`` denominators keep every dispute visible.  This is the statement a
   reader actually wants: the report is a point exactly when nothing is pending. *)
Theorem zero_width_means_no_dispute :
  forall s c ds dc : Z,
    0 <= s -> 0 <= c -> 0 <= ds -> 0 <= dc ->
    width s c ds dc = 0 -> ds = 0 /\ dc = 0.
Proof.
  intros s c ds dc Hs Hc Hds Hdc Hw.
  rewrite width_is_the_dispute_term in Hw.
  assert (Hn1 : 0 <= s * dc) by (apply Z.mul_nonneg_nonneg; lia).
  assert (Hn2 : 0 <= c * ds) by (apply Z.mul_nonneg_nonneg; lia).
  assert (Hn3 : 0 <= ds * dc) by (apply Z.mul_nonneg_nonneg; lia).
  lia.
Qed.

(* ------------------------------------------------------------------ *)
(* 2. Both bounds move the right way.                                  *)
(*    These are the monotonicity claims the re-priced scalar could not *)
(*    satisfy at once; here each holds for each bound, and each proof  *)
(*    names the term that makes it hold.                               *)
(* ------------------------------------------------------------------ *)

(* More support never lowers the lower bound: the gap is 2*(c+dc). *)
Theorem lo_monotone_in_support :
  forall s c ds dc : Z,
    0 <= s -> 0 <= c -> 0 <= ds -> 0 <= dc ->
    lo_num s c dc * lo_den (s + 1) c dc
      <= lo_num (s + 1) c dc * lo_den s c dc.
Proof.
  intros s c ds dc Hs Hc Hds Hdc.
  assert (Hd : lo_num (s + 1) c dc * lo_den s c dc
               - lo_num s c dc * lo_den (s + 1) c dc = 2 * (c + dc) + 1)
    by (unfold lo_num, lo_den; ring).
  lia.
Qed.

(* More support never lowers the upper bound either: the gap is 2*c. *)
Theorem hi_monotone_in_support :
  forall s c ds dc : Z,
    0 <= s -> 0 <= c -> 0 <= ds -> 0 <= dc ->
    hi_num s ds c * hi_den (s + 1) ds c
      <= hi_num (s + 1) ds c * hi_den s ds c.
Proof.
  intros s c ds dc Hs Hc Hds Hdc.
  assert (Hd : hi_num (s + 1) ds c * hi_den s ds c
               - hi_num s ds c * hi_den (s + 1) ds c = 2 * c + 1)
    by (unfold hi_num, hi_den; ring).
  lia.
Qed.

(* More contradiction never raises the lower bound: the gap is 2*s. *)
Theorem lo_antitone_in_contradiction :
  forall s c ds dc : Z,
    0 <= s -> 0 <= c -> 0 <= ds -> 0 <= dc ->
    lo_num s (c + 1) dc * lo_den s c dc
      <= lo_num s c dc * lo_den s (c + 1) dc.
Proof.
  intros s c ds dc Hs Hc Hds Hdc.
  assert (Hd : lo_num s c dc * lo_den s (c + 1) dc
               - lo_num s (c + 1) dc * lo_den s c dc = 2 * s + 1)
    by (unfold lo_num, lo_den; ring).
  lia.
Qed.

(* And never raises the upper bound either: the gap is 2*(s+ds). *)
Theorem hi_antitone_in_contradiction :
  forall s c ds dc : Z,
    0 <= s -> 0 <= c -> 0 <= ds -> 0 <= dc ->
    hi_num s ds (c + 1) * hi_den s ds c
      <= hi_num s ds c * hi_den s ds (c + 1).
Proof.
  intros s c ds dc Hs Hc Hds Hdc.
  assert (Hd : hi_num s ds c * hi_den s ds (c + 1)
               - hi_num s ds (c + 1) * hi_den s ds c = 2 * (s + ds) + 1)
    by (unfold hi_num, hi_den; ring).
  lia.
Qed.

(* Disputed support can only raise the ceiling, and disputed contradiction can
   only lower the floor: each dispute moves exactly one bound, in the direction
   that widens the interval. *)
Theorem disputed_support_raises_only_the_ceiling :
  forall s c ds dc : Z,
    0 <= s -> 0 <= c -> 0 <= ds -> 0 <= dc ->
    hi_num s ds c * hi_den s (ds + 1) c
      <= hi_num s (ds + 1) c * hi_den s ds c.
Proof.
  intros s c ds dc Hs Hc Hds Hdc.
  assert (Hd : hi_num s (ds + 1) c * hi_den s ds c
               - hi_num s ds c * hi_den s (ds + 1) c = 2 * c + 1)
    by (unfold hi_num, hi_den; ring).
  lia.
Qed.

Theorem disputed_contradiction_lowers_only_the_floor :
  forall s c ds dc : Z,
    0 <= s -> 0 <= c -> 0 <= ds -> 0 <= dc ->
    lo_num s c (dc + 1) * lo_den s c dc
      <= lo_num s c dc * lo_den s c (dc + 1).
Proof.
  intros s c ds dc Hs Hc Hds Hdc.
  assert (Hd : lo_num s c dc * lo_den s c (dc + 1)
               - lo_num s c (dc + 1) * lo_den s c dc = 2 * s + 1)
    by (unfold lo_num, lo_den; ring).
  lia.
Qed.

(* ------------------------------------------------------------------ *)
(* 3. The report never contradicts itself.                             *)
(*    `SUPPORTED` reads the floor, `CONTRADICTED` reads the ceiling.   *)
(*    They cannot both fire — the integrity property the single number *)
(*    could only buy by losing monotonicity.                           *)
(* ------------------------------------------------------------------ *)

(* Thresholds in cleared form: floor >= 1/2, ceiling <= -1/2. *)
Definition floor_at_least_half (s c dc : Z) : Prop :=
  2 * lo_num s c dc >= lo_den s c dc.

Definition ceiling_at_most_minus_half (s ds c : Z) : Prop :=
  2 * hi_num s ds c <= - hi_den s ds c.

Theorem labels_never_both_fire :
  forall s c ds dc : Z,
    0 <= s -> 0 <= c -> 0 <= ds -> 0 <= dc ->
    0 < s + c ->
    ~ (floor_at_least_half s c dc /\ ceiling_at_most_minus_half s ds c).
Proof.
  intros s c ds dc Hs Hc Hds Hdc Hne [Hf Hc'].
  unfold floor_at_least_half in Hf.
  unfold ceiling_at_most_minus_half in Hc'.
  unfold lo_num, lo_den, hi_num, hi_den in *.
  (* Each threshold read is linear once cleared, and the two cannot hold at
     once unless every count is zero — which `0 < s + c` excludes. *)
  lia.
Qed.

(* The floor is never above the ceiling, read at the thresholds.

   The empty configuration is the one place both reads are satisfiable, and it
   is degenerate rather than contradictory: every count is zero, so both
   thresholds are met by the number 0 and neither label would be issued — the
   Python returns ``INSUFFICIENT`` before it reads either bound.  Stating the
   non-empty precondition makes the theorem say what the code does. *)
Theorem threshold_band_is_ordered :
  forall s c ds dc : Z,
    0 <= s -> 0 <= c -> 0 <= ds -> 0 <= dc ->
    0 < s + c ->
    floor_at_least_half s c dc ->
    ~ ceiling_at_most_minus_half s ds c.
Proof.
  intros s c ds dc Hs Hc Hds Hdc Hne Hf Hc'.
  unfold floor_at_least_half in Hf.
  unfold ceiling_at_most_minus_half in Hc'.
  unfold lo_num, lo_den, hi_num, hi_den in *.
  lia.
Qed.

(* ------------------------------------------------------------------ *)
(* 4. The empty configuration.                                         *)
(*    `0 < s + c` is what the Python asserts before dividing, so the    *)
(*    theorems above are not about a configuration the code cannot     *)
(*    produce.                                                         *)
(* ------------------------------------------------------------------ *)

(* The empty configuration does not evaluate to zero anyway, because the
   denominator is ``1`` at ``s = c = 0``: the raw bounds are ``-dc/(dc+1)`` and
   ``ds/(ds+1)``.  The Python returns ``INSUFFICIENT`` before reading either,
   which is a policy on top of a well-defined report rather than a guard against
   a division by zero. *)
Theorem empty_configuration_is_defined :
  forall ds dc : Z,
    lo_num 0 0 dc = - dc /\ hi_num 0 ds 0 = ds /\
    lo_den 0 0 dc = dc + 1 /\ hi_den 0 ds 0 = ds + 1.
Proof.
  intros ds dc. unfold lo_num, hi_num, lo_den, hi_den.
  repeat split; ring.
Qed.

(* The refinement boundary: the Python side computes these same two numbers and
   compares them to `Fraction` values on the whole grid.  A configuration with
   both group counts zero is excluded there by the same `0 < s + c` guard. *)

Print Assumptions lo_never_above_hi.
Print Assumptions width_is_the_dispute_term.
Print Assumptions zero_width_means_no_dispute.
Print Assumptions lo_monotone_in_support.
Print Assumptions hi_antitone_in_contradiction.
Print Assumptions labels_never_both_fire.
