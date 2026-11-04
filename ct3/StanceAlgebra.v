(* StanceAlgebra.v — the semantic layer as an algebra, machine-checked.

   Coq 8.18, standard library only (no Mathlib, no MathComp, no extra packages).
   Build with:  coqc StanceAlgebra.v

   Why this file.  backend/app/semantic_guard.py decides a clause's direction
   from a fixed phrase inventory, and every later rule is one more way a cue can
   fail to mean what it says: a negation suffix, a negated frame ("it is not true
   that"), a quantified negation ("nobody"), a hedged cue, a conditional cue, a
   cue inside a question, a later contrast.  Each of those rules was derived
   separately, and what they were each approximating is the algebra below:
   a carrier with a composition, a negation acting on it, an order-independence
   law, and an abstention law.  Stating the algebra once makes the rules
   instances of it rather than a list of cases.

   Then section 6 proves the impossibility that
   backend/app/decision_table.py:282-289 asserts only in prose: a magnitude that
   is monotone in support cannot also report, for a withheld verdict, a number no
   decisive verdict attains.

   What is modelled, and what is not.  The carrier here is the *verdict* a clause
   yields, not the clause text: no phrase list, no regex, no grammar, no question
   of English meaning is modelled, so nothing here says the inventory is
   adequate.  What is proved is that the composition around it is associative,
   commutative, order-independent, and that its two abstentions are different
   facts.  ct3/StanceAlgebra_facts.md states the assumptions that connect this
   file to the Python, and the parts of the Python that are outside the model.
*)

Require Import List Arith Bool ZArith Lia QArith Lqa.
Require Import Coq.Sorting.Permutation.
Import ListNotations.

(* QArith leaves its notation scope open, which would make every bare numeral
   in this file a candidate rational.  Close it: the carrier of the algebra is
   inductive, and only section 6 talks about numbers. *)
Close Scope Q_scope.

(* ================================================================== *)
(* 1. Polarity, and scope as a monoid acting on it                     *)
(* ================================================================== *)

(* A clause's direction before anything is said about whether it could be read.
   Two elements, and they are opposite rather than ranked. *)
Inductive polarity : Type := For | Against.

Definition neg (p : polarity) : polarity :=
  match p with For => Against | Against => For end.

(* Requirement: negation is an involution on polarity. *)
Theorem neg_involution : forall p, neg (neg p) = p.
Proof. destruct p; reflexivity. Qed.

(* Non-vacuity: the involution is not the identity, so "negation leaves the
   direction alone" is not an available reading of this model. *)
Lemma neg_swaps : neg For = Against /\ neg Against = For.
Proof. split; reflexivity. Qed.

Lemma neg_not_identity : exists p, neg p <> p.
Proof. exists For. discriminate. Qed.

(* A scope is the parity of the negations in force over a clause: false when the
   clause is read in the affirmative position.  Parity rather than a count is a
   modelling claim — see StanceAlgebra_facts.md, assumption A2. *)
Definition scope : Type := bool.

Definition act (sc : scope) (p : polarity) : polarity :=
  if sc then neg p else p.

Lemma act_unit : forall p, act false p = p.
Proof. reflexivity. Qed.

(* The action law: applying clause 1's scope and then clause 2's scope is the
   action of their product scope.  This is the statement the per-rule suffix
   guards each approximate for one scope shape. *)
Theorem act_compose : forall a b p, act (xorb a b) p = act a (act b p).
Proof. intros a b p. destruct a, b, p; reflexivity. Qed.

(* Determinism stated as content rather than as "a function is a function":
   two scopes that differ by an even number of negations act identically, so the
   result is a function of parity alone. *)
Lemma act_depends_on_parity_only :
  forall a b p, xorb a b = false -> act a p = act b p.
Proof.
  intros a b p H. destruct a, b; simpl in *; try discriminate; reflexivity.
Qed.

(* The action is injective at each scope: negation never merges the two
   directions.  Every "flip the cue" shortcut needs this. *)
Lemma act_inj : forall sc p q, act sc p = act sc q -> p = q.
Proof.
  intros sc p q H. destruct sc, p, q; simpl in *; try discriminate; reflexivity.
Qed.

Lemma act_surjective : forall p, exists q, act true q = p.
Proof. intros [|]; [exists Against | exists For]; reflexivity. Qed.

(* Iterated scope: the natural numbers act by repetition, for nested scopes
   ("it is not true that the checklist was not unavailable"). *)
Fixpoint neg_n (n : nat) (p : polarity) : polarity :=
  match n with O => p | S k => neg (neg_n k p) end.

Lemma neg_n_add : forall n m p, neg_n (n + m) p = neg_n n (neg_n m p).
Proof.
  intros n. induction n as [| n IH]; intros m p; simpl.
  - reflexivity.
  - rewrite IH. reflexivity.
Qed.

Lemma neg_n_two : forall p, neg_n 2 p = p.
Proof. intros p. simpl. destruct p; reflexivity. Qed.

(* ================================================================== *)
(* 2. The stance carrier                                               *)
(* ================================================================== *)

(* Five elements, not three.  The three the phrase matcher can express are
   SUPPORTS, CONTRADICTS and "no relation"; the last is a merge of three
   situations that composition must not confuse:

     NoClause   nothing was said                (identity of composition)
     NoInfo     something was said and could not be read   (top: poisons)
     Conflict   both directions were read      (join of the two directions)

   Abstaining because the clause was unreadable and abstaining because two read
   clauses disagree are different facts about the evidence.  The matcher's
   carrier conflates them; this one keeps them apart and section 2 shows what the
   conflation costs. *)
Inductive stance : Type :=
  | NoClause
  | Supports
  | Contradicts
  | Conflict
  | NoInfo.

(* Composition as the join of the lattice

        NoInfo          (top: unreadable outranks everything)
          |
       Conflict
        /    \
   Supports  Contradicts
        \    /
      NoClause          (bottom: nothing was said)

   read as "information is added, and both abstentions sit above the
   directions".  Unreadability outranks conflict: a clause nobody could read is
   not evidence that two other clauses disagree. *)
Definition compose (a b : stance) : stance :=
  match a with
  | NoInfo => NoInfo
  | Conflict => match b with NoInfo => NoInfo | _ => Conflict end
  | Supports =>
      match b with
      | NoInfo => NoInfo
      | Conflict => Conflict
      | Supports => Supports
      | Contradicts => Conflict
      | NoClause => Supports
      end
  | Contradicts =>
      match b with
      | NoInfo => NoInfo
      | Conflict => Conflict
      | Supports => Conflict
      | Contradicts => Contradicts
      | NoClause => Contradicts
      end
  | NoClause => b
  end.

(* ---- The band laws ---- *)

Lemma compose_unit_l : forall a, compose NoClause a = a.
Proof. reflexivity. Qed.

Lemma compose_unit_r : forall a, compose a NoClause = a.
Proof. intros []; reflexivity. Qed.

Lemma compose_idem : forall a, compose a a = a.
Proof. intros []; reflexivity. Qed.

Lemma compose_comm : forall a b, compose a b = compose b a.
Proof. intros [] []; reflexivity. Qed.

(* Composition is associative, so a batch of clauses can be composed in any
   grouping — which is what lets section 4 fold a list instead of a tree. *)
Theorem compose_assoc :
  forall a b c, compose (compose a b) c = compose a (compose b c).
Proof. intros [] [] []; reflexivity. Qed.

(* ---- The two abstentions are absorbing, and they are not the same element ---- *)

Lemma compose_absorbs_noinfo_l : forall b, compose NoInfo b = NoInfo.
Proof. reflexivity. Qed.

Lemma compose_absorbs_noinfo_r : forall a, compose a NoInfo = NoInfo.
Proof. intros []; reflexivity. Qed.

(* Unreadability is above conflict: composing them gives unreadability, in
   either order.  This is the only place the two abstentions interact, and the
   direction is a modelling choice — see assumption A4. *)
Lemma unreadable_outranks_conflict :
  compose NoInfo Conflict = NoInfo /\ compose Conflict NoInfo = NoInfo.
Proof. split; reflexivity. Qed.

(* Conflict absorbs a direction: more evidence in one direction does not resolve
   a contradiction that was read. *)
Lemma compose_conflict_with_direction :
  compose Conflict Supports = Conflict /\ compose Conflict Contradicts = Conflict /\
  compose Supports Conflict = Conflict /\ compose Contradicts Conflict = Conflict.
Proof. repeat split; reflexivity. Qed.

(* ---- The public carrier the phrase matcher actually uses ---- *)

Inductive pub : Type := PSupports | PContradicts | PAbstain.

Definition public (s : stance) : pub :=
  match s with
  | Supports => PSupports
  | Contradicts => PContradicts
  | _ => PAbstain
  end.

(* The join one would write on the three-element carrier, wanting Abstain to
   absorb.  The lemmas below are about what this candidate cannot do. *)
Definition pub_compose (x y : pub) : pub :=
  match x, y with
  | PSupports, PSupports => PSupports
  | PContradicts, PContradicts => PContradicts
  | _, _ => PAbstain
  end.

(* Abstain is absorbing here, which is why the candidate is attractive.  The
   absorption is not the problem; the quotient is. *)
Lemma pub_abstain_absorbing_l : forall x, pub_compose PAbstain x = PAbstain.
Proof. intros []; reflexivity. Qed.

Lemma pub_abstain_absorbing_r : forall x, pub_compose x PAbstain = PAbstain.
Proof. intros []; reflexivity. Qed.

(* It is not a homomorphism, and the counterexample is the whole point:
   composing absence with a direction yields the direction, composing
   unreadability with a direction yields an abstention, and both start from the
   same public value. *)
Theorem pub_compose_not_hom :
  exists a b, public (compose a b) <> pub_compose (public a) (public b).
Proof. exists NoClause, Supports. vm_compute. discriminate. Qed.

(* The counterexample, computed rather than asserted: the candidate public
   operation maps (PAbstain, PSupports) to PAbstain, while the true composition
   of the two inner values that project to those public values does not. *)
Example public_composition_counterexample :
     public (compose NoClause Supports) = PSupports
  /\ public (compose NoInfo Supports) = PAbstain
  /\ pub_compose (public NoClause) (public Supports) = PAbstain.
Proof. repeat split; reflexivity. Qed.

(* The general form: no operation on the three-element carrier makes the
   projection a homomorphism.  This is not a defect of `pub_compose`; it is
   impossible, because two elements with the same public value compose to
   different public values.  Losing which abstention you had costs you the
   ability to compose at all. *)
Theorem no_public_composition :
  ~ (exists op : pub -> pub -> pub,
        forall a b, public (compose a b) = op (public a) (public b)).
Proof.
  intros [op Hop].
  pose proof (Hop NoClause Supports) as H1.
  pose proof (Hop NoInfo Supports) as H2.
  cbv in H1, H2.
  rewrite <- H1 in H2. discriminate H2.
Qed.

(* The same failure, stated as a single computable pair. *)
Theorem public_loses_compositionality :
  public NoClause = public NoInfo /\
  public (compose NoClause Supports) <> public (compose NoInfo Supports).
Proof. split; vm_compute; reflexivity || discriminate. Qed.

(* The three provenances of Abstain, pairwise distinct as elements ... *)
Lemma abstain_provenances_distinct :
  NoClause <> NoInfo /\ NoInfo <> Conflict /\ NoClause <> Conflict.
Proof. repeat split; discriminate. Qed.

(* ... and identical under the projection. *)
Lemma abstain_provenances_collapse :
  public NoClause = PAbstain /\ public NoInfo = PAbstain /\ public Conflict = PAbstain.
Proof. repeat split; reflexivity. Qed.

(* The defect stated as a theorem rather than a remark: the public value does
   not determine the inner one, and the inner one is what composition sees. *)
Theorem public_not_injective : exists a b, a <> b /\ public a = public b.
Proof. exists NoInfo, Conflict. split; [discriminate | reflexivity]. Qed.

(* Two right inverses of `public`.  A section exists but is not unique, so the
   choice of section carries information `public` does not: no consumer of the
   public value can tell an unreadable clause from a contradicted pair. *)
Definition sec_unreadable (x : pub) : stance :=
  match x with
  | PSupports => Supports
  | PContradicts => Contradicts
  | PAbstain => NoInfo
  end.

Definition sec_conflict (x : pub) : stance :=
  match x with
  | PSupports => Supports
  | PContradicts => Contradicts
  | PAbstain => Conflict
  end.

Theorem two_sections_disagree :
  (forall x, public (sec_unreadable x) = x) /\
  (forall x, public (sec_conflict x) = x) /\
  sec_unreadable PAbstain <> sec_conflict PAbstain.
Proof.
  split.
  - intros []; reflexivity.
  - split.
    + intros []; reflexivity.
    + discriminate.
Qed.

(* ================================================================== *)
(* 3. Negation acting on a whole clause                                *)
(* ================================================================== *)

Definition flip (s : stance) : stance :=
  match s with Supports => Contradicts | Contradicts => Supports | _ => s end.

Lemma flip_involution : forall s, flip (flip s) = s.
Proof. intros []; reflexivity. Qed.

Lemma flip_nontrivial : flip Supports <> Supports.
Proof. discriminate. Qed.

(* Negation cannot manufacture content: it fixes every abstention.  This is why
   the guard abstains on a negated frame instead of flipping it — flipping a
   verdict it did not establish would be an inference, and this lemma says the
   algebra gives it nothing to flip. *)
Lemma flip_fixes_abstention :
  flip NoClause = NoClause /\ flip NoInfo = NoInfo /\ flip Conflict = Conflict.
Proof. repeat split; reflexivity. Qed.

(* Negation is an automorphism of the composition: flipping the composed verdict
   equals composing the flipped verdicts.  Scope therefore acts on the algebra,
   not on the text. *)
Theorem flip_compose : forall a b, flip (compose a b) = compose (flip a) (flip b).
Proof. intros [] []; reflexivity. Qed.

(* The bridge to section 1: the stance-level flip and the polarity-level
   negation are the same action. *)
Definition polarity_of (s : stance) : option polarity :=
  match s with Supports => Some For | Contradicts => Some Against | _ => None end.

Theorem polarity_of_flip :
  forall s p, polarity_of s = Some p -> polarity_of (flip s) = Some (neg p).
Proof.
  intros s p H. destruct s; simpl in *; try discriminate; injection H as <-;
  reflexivity.
Qed.

(* Negation on a clause distributes over the polarity action of section 1:
   acting on the composed stance is acting on its polarity. *)
Theorem polarity_of_act :
  forall s p, polarity_of s = Some p -> polarity_of (flip s) = Some (act true p).
Proof.
  intros s p H. apply polarity_of_flip in H. rewrite H. reflexivity.
Qed.

Fixpoint flip_n (n : nat) (s : stance) : stance :=
  match n with O => s | S k => flip (flip_n k s) end.

Lemma flip_n_add : forall n m s, flip_n (n + m) s = flip_n n (flip_n m s).
Proof.
  intros n. induction n as [| n IH]; intros m s; simpl.
  - reflexivity.
  - rewrite IH. reflexivity.
Qed.

Lemma flip_n_two : forall s, flip_n 2 s = s.
Proof. intros s. simpl. rewrite flip_involution. reflexivity. Qed.

(* ================================================================== *)
(* 4. Composition over a list of clause verdicts                       *)
(* ================================================================== *)

Definition compose_all (l : list stance) : stance := fold_right compose NoClause l.

Lemma compose_all_nil : compose_all [] = NoClause.
Proof. reflexivity. Qed.

Lemma compose_all_cons : forall a l, compose_all (a :: l) = compose a (compose_all l).
Proof. reflexivity. Qed.

(* Batching: reading two batches and composing is composing the batches. *)
Theorem compose_all_app :
  forall l1 l2, compose_all (l1 ++ l2) = compose (compose_all l1) (compose_all l2).
Proof.
  intros l1. induction l1 as [| a l1 IH]; intros l2; simpl.
  - reflexivity.
  - rewrite IH, compose_assoc. reflexivity.
Qed.

(* Requirement 3: the composed verdict is invariant under permutation of the
   clauses.  Proved against the standard library's Permutation, so the statement
   is about the same relation a reviewer would reach for. *)
Theorem compose_all_perm :
  forall l1 l2, Permutation l1 l2 -> compose_all l1 = compose_all l2.
Proof.
  intros l1 l2 H.
  induction H as [| x l l' Hp IH | x y l | l l' l'' H1 IH1 H2 IH2].
  - reflexivity.
  - simpl. rewrite IH. reflexivity.
  - simpl. rewrite <- compose_assoc, <- compose_assoc.
    rewrite (compose_comm y x). reflexivity.
  - transitivity (compose_all l'); [exact IH1 | exact IH2].
Qed.

(* The batching case of order independence, as a corollary: which batch a clause
   arrived in cannot matter. *)
Corollary compose_all_batch_order :
  forall l1 l2, compose_all (l1 ++ l2) = compose_all (l2 ++ l1).
Proof.
  intros l1 l2. rewrite compose_all_app, compose_all_app.
  rewrite compose_comm. reflexivity.
Qed.

(* ================================================================== *)
(* 5. Soundness of abstention                                          *)
(* ================================================================== *)

Lemma compose_noinfo_spec :
  forall a b, compose a b = NoInfo <-> a = NoInfo \/ b = NoInfo.
Proof. intros a b. destruct a, b; simpl; intuition discriminate. Qed.

(* Requirement 4, the local form, restated where the fold proof uses it:
   unreadability survives composition in either position. *)
(* (see compose_absorbs_noinfo_l / compose_absorbs_noinfo_r, section 2) *)

(* Requirement 4, the fold form: a batch is unreadable exactly when some clause
   in it was unreadable.  Nothing else produces it, so unreadability cannot be
   manufactured by composing readings that all succeeded. *)
Theorem compose_all_noinfo : forall l, compose_all l = NoInfo <-> In NoInfo l.
Proof.
  intros l. induction l as [| a l IH]; simpl.
  - split.
    + discriminate.
    + intros [].
  - rewrite compose_noinfo_spec, IH. simpl. intuition congruence.
Qed.

(* The headline of section 5: if any clause was unreadable, the composed verdict
   is not a direction and the public reading is Abstain.  This is the property
   the individual negation/hedge/conditional rules were each approximating. *)
Theorem unreadable_absorbs : forall l, In NoInfo l -> compose_all l = NoInfo.
Proof. intros l H. apply compose_all_noinfo. exact H. Qed.

Theorem no_direction_from_unreadable :
  forall l, In NoInfo l ->
    compose_all l <> Supports /\ compose_all l <> Contradicts /\
    public (compose_all l) = PAbstain.
Proof.
  intros l H. rewrite (unreadable_absorbs l H). repeat split; discriminate || reflexivity.
Qed.

Corollary direction_excludes_unreadable :
  forall l, (compose_all l = Supports \/ compose_all l = Contradicts) ->
    ~ In NoInfo l.
Proof.
  intros l [H | H] Hin.
  - exact (proj1 (no_direction_from_unreadable l Hin) H).
  - exact (proj1 (proj2 (no_direction_from_unreadable l Hin)) H).
Qed.

(* And the honest converse boundary: a *read* abstention is not a barrier.  An
   empty batch composes to NoClause, so adding nothing changes nothing — which is
   why the absence of directional cues alone must not be reported as a neutral
   finding. *)
Theorem absence_is_not_abstention :
  forall l, compose_all l = NoClause -> public (compose_all l) = PAbstain.
Proof. intros l H. rewrite H. reflexivity. Qed.

(* Requirement 1, behaviourally: the three provenances react differently to the
   same directional evidence, so no two of them are interchangeable. *)
Theorem abstention_provenance_matters :
     compose_all [NoClause; Supports] = Supports
  /\ compose_all [NoClause; Contradicts] = Contradicts
  /\ compose_all [NoInfo; Supports] = NoInfo
  /\ compose_all [Supports; NoInfo] = NoInfo
  /\ compose_all [Conflict; Supports] = Conflict
  /\ compose_all [Supports; Contradicts] = Conflict
  /\ compose_all [NoInfo; Conflict] = NoInfo
  /\ compose_all [Conflict; NoInfo] = NoInfo
  /\ compose_all [NoClause] = NoClause.
Proof. repeat split; reflexivity. Qed.

(* ================================================================== *)
(* 6. The signed table: monotonicity versus status integrity           *)
(* ================================================================== *)

Inductive status5 : Type := Supported | Contradicted | Partial | NoDirection.

(* The three magnitudes the table's own comment quotes. *)
Definition half : Q := 1#2.
Definition quarter : Q := 1#4.
Definition two_thirds : Q := 2#3.

(* Exactly backend/app/decision_table.py::score:  (s - c) / (s + c + 1). *)
Definition base_score (s c : nat) : Q :=
  Qmake (Z.of_nat s - Z.of_nat c) (Pos.of_succ_nat (s + c)).

(* backend/app/decision_table.py::_label under POLICY_SIGNED_MARGIN:
     SUPPORTED     s >= 2  and  s >= 3*c + 1
     CONTRADICTED  c >= 3*s + 1
     INSUFFICIENT  s = 0 and c = 0
     otherwise     PARTIAL                                            *)
Definition supports_b (s c : nat) : bool :=
  andb (Nat.leb 2 s) (Nat.leb (3 * c + 1) s).

Definition contradicts_b (s c : nat) : bool := Nat.leb (3 * s + 1) c.

Definition label (s c : nat) : status5 :=
  if supports_b s c then Supported
  else if contradicts_b s c then Contradicted
  else if andb (Nat.eqb s 0) (Nat.eqb c 0) then NoDirection
  else Partial.

Definition status_eqb (a b : status5) : bool :=
  match a, b with
  | Supported, Supported => true
  | Contradicted, Contradicted => true
  | Partial, Partial => true
  | NoDirection, NoDirection => true
  | _, _ => false
  end.

(* decide(s, 0, disputed_contradiction = d).  Two configurations are evaluated:
   the undisputed one (line 271, ``effective_s, effective_c = s, c``) and, when
   the labels differ, the challenged one (line 290).  Line 293 reports
   ``score(effective_s, effective_c)``, so the reported magnitude is the base
   score of whichever configuration is current — that is the fidelity clause of
   the theorem below, and lines 282-289 are the prose it makes precise. *)
Definition reported (s d : nat) : Q :=
  if status_eqb (label s d) (label s 0) then base_score s 0 else base_score s d.

Definition reported_status (s d : nat) : status5 :=
  if status_eqb (label s d) (label s 0) then label s 0 else Partial.

(* "Given that status depends on the disputed configuration": one disputed
   contradiction group withholds a verdict the undisputed evidence already
   earned.  This is line 290 firing, and it is what makes the two numbers below
   different configurations. *)
Theorem status_depends_on_dispute :
  label 2 0 = Supported /\ label 2 1 = Partial /\ label 2 0 <> label 2 1.
Proof. vm_compute. repeat split; try reflexivity. intro H. discriminate H. Qed.

(* The two numbers the table can report at the switch, computed: 0.50 for the
   undisputed one-group configuration, 0.25 for the challenged one — the pair
   quoted in the comment at decision_table.py:287. *)
Theorem reported_at_switch :
  reported 1 1 = half /\ reported 2 1 = quarter /\ reported 2 0 = two_thirds.
Proof. repeat split; vm_compute; reflexivity. Qed.

(* The status half of the same switch: the downgrade at line 275 fires for two
   support groups and not for one, so the status of identical undisputed
   evidence is decided by the disputed configuration. *)
Theorem reported_status_at_switch :
  reported_status 2 1 = Partial /\ reported_status 2 0 = Supported.
Proof. repeat split; vm_compute; reflexivity. Qed.

Lemma not_half_le_quarter : ~ (half <= quarter)%Q.
Proof. unfold half, quarter. lra. Qed.

(* The defect the comment admits, machine-checked: adding an undisputed support
   group lowers the reported magnitude. *)
Theorem shipped_report_not_monotone : (reported 2 1 < reported 1 1)%Q.
Proof.
  rewrite (proj1 (proj2 reported_at_switch)), (proj1 reported_at_switch).
  unfold quarter, half. lra.
Qed.

(* The same fact as a refutation, which is the form the theorem below uses.  The
   code comment at decision_table.py:282-286 states this cost explicitly. *)
Corollary monotonicity_fails_shipping :
  ~ (forall s s', (s <= s')%nat -> (reported s 1 <= reported s' 1)%Q).
Proof.
  intros H.
  pose proof (H 1%nat 2%nat ltac:(lia)) as Hle.
  pose proof shipped_report_not_monotone as Hlt.
  lra.
Qed.

(* The impossibility theorem.

   No scoring function f (support groups, disputed contradiction groups -> Q) and
   status function st can satisfy both:
     (a) monotone non-decreasing in support, and
     (b) a PARTIAL verdict's magnitude is never attained (indeed never reached)
         by any SUPPORTED verdict,
   once the status is allowed to depend on the disputed configuration, because
   then the table has two magnitudes to choose between and each choice breaks one
   of the two.

   The formalisation is the smallest one that is not vacuous: hypothesis levels
   are (i) the two configurations the table evaluates, (ii) their two labels,
   (iii) their two numbers, and (iv) the disjunction that the report is one of
   them.  (iv) is the fidelity clause — it is satisfied by the shipped code at
   lines 293 and 290 — and it is what makes the disjunction exhaustive rather
   than a guess. *)
Theorem no_policy_keeps_monotonicity_and_integrity :
  forall (f : nat -> nat -> Q) (st : nat -> nat -> status5),
    st 2 0 = Supported ->
    st 2 1 = Partial ->
    f 1 1 = half ->
    f 2 0 = two_thirds ->
    (f 2 1 = quarter \/ f 2 1 = two_thirds) ->
    ~ ( (forall s s' d, (s <= s')%nat -> (f s d <= f s' d)%Q)
        /\ (forall s d s' d', st s d = Partial -> st s' d' = Supported ->
              (f s d <> f s' d')%Q) ).
Proof.
  intros f st Hs0 Hs1 Hf1 Hf0 [Hv | Hv] [Hmono Hsep].
  - (* reporting the challenged magnitude: monotonicity dies at 1 -> 2 *)
    pose proof (Hmono 1%nat 2%nat 1%nat ltac:(lia)) as Hle.
    rewrite Hf1, Hv in Hle.
    exact (not_half_le_quarter Hle).
  - (* reporting the undisputed magnitude: integrity dies, because 2/3 is also
       the magnitude of the SUPPORTED configuration (2, 0) *)
    pose proof (Hsep 2%nat 1%nat 2%nat 0%nat Hs1 Hs0) as Hne.
    rewrite Hv, Hf0 in Hne.
    exact (Hne eq_refl).
Qed.

(* The shipped table takes the first branch, so it violates (a) — computed
   above.  What it does *not* do is satisfy (b) either, and that is independent
   of the dispute machinery: the base score attains 1/2 at both (1, 0), which is
   PARTIAL, and (4, 1), which is SUPPORTED.  A magnitude alone cannot identify a
   status, in this table or in any table whose score is continuous and whose
   label is defined by a threshold. *)
Theorem boundary_collision :
  (base_score 1 0 == base_score 4 1)%Q /\ label 1 0 <> label 4 1.
Proof.
  split.
  - vm_compute. reflexivity.
  - vm_compute. intro H. discriminate H.
Qed.

(* Non-vacuity of the collision: both numbers are reachable, and the statuses
   really do differ in the direction claimed. *)
Theorem boundary_collision_statuses :
  label 1 0 = Partial /\ label 4 1 = Supported.
Proof. repeat split; vm_compute; reflexivity. Qed.

(* ================================================================== *)
(* 7. Assumptions audit                                                *)
(* ================================================================== *)

(* Printed at compile time so the absence of axioms is demonstrated by the build
   rather than asserted here.  Every line should read "Closed under the global
   context". *)
Print Assumptions neg_involution.
Print Assumptions act_compose.
Print Assumptions compose_assoc.
Print Assumptions compose_comm.
Print Assumptions compose_all_perm.
Print Assumptions compose_all_app.
Print Assumptions flip_compose.
Print Assumptions polarity_of_flip.
Print Assumptions no_public_composition.
Print Assumptions two_sections_disagree.
Print Assumptions compose_all_noinfo.
Print Assumptions unreadable_absorbs.
Print Assumptions no_direction_from_unreadable.
Print Assumptions abstention_provenance_matters.
Print Assumptions status_depends_on_dispute.
Print Assumptions reported_at_switch.
Print Assumptions shipped_report_not_monotone.
Print Assumptions monotonicity_fails_shipping.
Print Assumptions no_policy_keeps_monotonicity_and_integrity.
Print Assumptions boundary_collision.
