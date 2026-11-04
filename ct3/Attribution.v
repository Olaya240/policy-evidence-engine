(* Attribution.v — the force of a matrix clause, and how forces compose.

   Coq 8.18, standard library only.  Build with:  coqc Attribution.v

   Context.  ``backend/app/evidence_frames.py`` reads the scaffolding around a
   proposition — who reports it, in which direction, with what quantifier — and
   answers one question: does any matrix clause withhold it?  Before that module
   the guard answered the question with regexes over the text before the cue, and
   the regexes could see ``not`` but not ``no one``, so ``"No one confirmed that
   the checklist was unavailable"`` certified the complement while
   ``"The auditor did not confirm …"`` abstained.  Same construction, two
   verdicts, decided by which word did the negating.

   This file is about the *typed* version of that decision, not about English:

     Frame = (class, polarity, quantifier)
     effective_negation = polarity is negative, or the quantifier is "none"
     force f = Withholds   when the frame is effectively negated
              = Asserts     otherwise

   The class is on the frame record but plays no part in the rule: a denied
   speech act withholds exactly as a denied evidential does.  (Until 2026-11-02
   this file modelled a narrower rule that withheld only the evidential class
   and let a denied speech act certify; the shipped reader never made that
   split, so the model now states the rule the code actually computes. The old
   split is preserved in git history, not here.)

   and composition is the meet of the forces of a prefix, with ``Asserts`` as the
   identity.  The two-element carrier is ordered ``Withholds <= Asserts``: less
   information is the bottom.  Everything below is proved about that algebra.

   What is *not* proved, and must not be read into it: which English shapes get
   a frame at all.  The file proves the algebra over the typed frames is sound;
   the recognition lives in ``evidence_frames.py`` and in the corpus, and the
   falsification corpus still counts the rows the policy gets wrong. *)

Require Import List.
Import ListNotations.

(* ------------------------------------------------------------------ *)
(* The carrier and the frame.                                          *)
(* ------------------------------------------------------------------ *)

Inductive Force : Type := Withholds | Asserts.

Inductive Class : Type := Evidential | SpeechAct.

Inductive Polarity : Type := Affirmative | Negative.

Inductive Quantifier : Type := All | Some_ | None_.

Record Frame : Type := {
  cls : Class;
  pol : Polarity;
  quant : Quantifier;
}.

(* A quantifier over the subject negates the frame just as ``not`` does:
   "No one confirmed …" and "The auditor did not confirm …" are one rule. *)
Definition effective_negation (f : Frame) : bool :=
  match pol f with
  | Negative => true
  | Affirmative =>
      match quant f with
      | None_ => true
      | _ => false
      end
  end.

Definition force (f : Frame) : Force :=
  if effective_negation f then Withholds else Asserts.

(* Information order: ``Withholds`` is the bottom. *)
Definition le_force (x y : Force) : Prop :=
  match x, y with
  | Withholds, _ => True
  | Asserts, Asserts => True
  | Asserts, Withholds => False
  end.

Definition meet (x y : Force) : Force :=
  match x with
  | Withholds => Withholds
  | Asserts => y
  end.

(* ------------------------------------------------------------------ *)
(* 1. The rule, stated as an equation.                                 *)
(* ------------------------------------------------------------------ *)

Theorem force_withholds_iff :
  forall f : Frame,
    force f = Withholds <-> effective_negation f = true.
Proof.
  intros [c p q]. destruct p, q; simpl; intuition discriminate.
Qed.

Theorem force_asserts_iff :
  forall f : Frame,
    force f = Asserts <-> effective_negation f = false.
Proof.
  intros [c p q]. destruct p, q; simpl; intuition discriminate.
Qed.

(* The class is inert: two frames that differ only in class have the same force.
   This is what the shipped reader implements for denied speech acts. *)
Theorem class_is_inert :
  forall p : Polarity, forall u : Quantifier,
    force {| cls := Evidential; pol := p; quant := u |} =
    force {| cls := SpeechAct;  pol := p; quant := u |}.
Proof. intros p u. reflexivity. Qed.

(* The point of the type: the force is a function of one field, so two frames
   that agree on the effective negation have the same force, whatever the agent
   says or however the quantifier is spelled. *)
Theorem force_extensional :
  forall f g : Frame,
    effective_negation f = effective_negation g ->
    force f = force g.
Proof.
  intros f g Hn. unfold force. rewrite Hn. reflexivity.
Qed.

(* Quantifier and polarity are two spellings of one thing: negating either way
   reaches ``Withholds``, on any class. *)
Theorem quantifier_and_polarity_agree :
  forall c : Class,
    force {| cls := c; pol := Negative; quant := All |} =
    force {| cls := c; pol := Affirmative; quant := None_ |}.
Proof.
  intros c. destruct c; reflexivity.
Qed.

(* ------------------------------------------------------------------ *)
(* 2. Composition: the meet over a prefix.                             *)
(* ------------------------------------------------------------------ *)

Definition compose (l : list Frame) : Force :=
  fold_right (fun f acc => meet (force f) acc) Asserts l.

Theorem meet_assoc : forall x y z : Force, meet (meet x y) z = meet x (meet y z).
Proof. intros x y z. destruct x, y, z; reflexivity. Qed.

Theorem meet_comm : forall x y : Force, meet x y = meet y x.
Proof. intros x y. destruct x, y; reflexivity. Qed.

Theorem meet_idem : forall x : Force, meet x x = x.
Proof. intros x. destruct x; reflexivity. Qed.

(* ``Asserts`` is the identity, which is why an empty prefix composes to it. *)
Theorem compose_nil : compose [] = Asserts.
Proof. reflexivity. Qed.

Theorem meet_identity_r : forall x : Force, meet x Asserts = x.
Proof. intros x. destruct x; reflexivity. Qed.

(* The homomorphism law: a prefix splits into two prefixes whose forces meet.
   This is the law the Python `compose_forces` relies on when it does not scan the
   whole sentence at once. *)
Theorem compose_app :
  forall l1 l2 : list Frame,
    compose (l1 ++ l2) = meet (compose l1) (compose l2).
Proof.
  intros l1. induction l1 as [| f rest IH]; intros l2.
  - simpl. reflexivity.
  - simpl. rewrite IH. rewrite meet_assoc. reflexivity.
Qed.

(* One withholding frame anywhere in the prefix withholds the proposition. *)
Theorem compose_withholds_iff :
  forall l : list Frame,
    compose l = Withholds <-> exists f, In f l /\ force f = Withholds.
Proof.
  intros l. induction l as [| f rest IH].
  - simpl. split.
    + intro H. discriminate.
    + intros [f [Hin _]]. inversion Hin.
  - simpl. destruct (force f) eqn:Ef.
    + (* f withholds: the meet is Withholds regardless of the rest. *)
      split.
      * intros _. exists f. split; [left; reflexivity | assumption].
      * intros _. reflexivity.
    + (* f asserts: the meet is the rest's force. *)
      simpl. split.
      * intros H. rewrite IH in H. destruct H as [g [Hin Hg]].
        exists g. split; [right; assumption | assumption].
      * intros [g [Hin Hg]]. rewrite IH.
        destruct Hin as [-> | Hin].
        -- rewrite Ef in Hg. discriminate.
        -- exists g. split; assumption.
Qed.

(* Adding clauses can only lose force, never gain it: the composition is monotone
   in the information order. *)
Theorem compose_is_monotone :
  forall l1 l2 : list Frame,
    le_force (compose (l1 ++ l2)) (compose l1).
Proof.
  intros l1 l2.
  rewrite compose_app.
  destruct (compose l1), (compose l2); simpl; trivial.
Qed.

(* A known withholding frame cannot be rescued by anything appended after it — the
   fail-closed property: one bad attribution is enough. *)
Theorem withholding_is_not_rescuable :
  forall f rest, force f = Withholds -> compose (f :: rest) = Withholds.
Proof.
  intros f rest Hf. simpl. rewrite Hf. reflexivity.
Qed.

(* ------------------------------------------------------------------ *)
(* 3. Unrecognised is not withheld.                                     *)
(*    Python returns ``None`` when no frame was recognised, and the     *)
(*    caller then falls back to its lexical reading. Conflating that   *)
(*    with ``Withholds`` would abstain on every sentence whose          *)
(*    scaffolding the reader does not recognise — the opposite failure  *)
(*    from certifying, and just as wrong.                              *)
(* ------------------------------------------------------------------ *)

Definition compose_opt (l : list Frame) : option Force :=
  match l with
  | [] => None
  | _ => Some (compose l)
  end.

Theorem no_frame_is_not_withheld :
  compose_opt [] = None.
Proof. reflexivity. Qed.

Theorem withdrawn_requires_a_frame :
  forall l : list Frame,
    compose_opt l = Some Withholds -> l <> [].
Proof.
  intros l H. destruct l as [| f rest].
  - simpl in H. discriminate.
  - discriminate.
Qed.

(* ------------------------------------------------------------------ *)
(* 4. Non-vacuity: both outcomes are reachable, so the rule can matter. *)
(* ------------------------------------------------------------------ *)

Definition denied_evidential : Frame :=
  {| cls := Evidential; pol := Negative; quant := All |}.

Definition denied_speech_act : Frame :=
  {| cls := SpeechAct; pol := Negative; quant := All |}.

Definition affirmative_evidential : Frame :=
  {| cls := Evidential; pol := Affirmative; quant := All |}.

Theorem a_withholding_frame_exists : force denied_evidential = Withholds.
Proof. reflexivity. Qed.

Theorem an_asserting_frame_exists : force affirmative_evidential = Asserts.
Proof. reflexivity. Qed.

(* The shipped policy, stated on the two classes: a denied speech act withholds
   exactly as a denied evidential does, and an affirmative frame of either kind
   certifies. Both outcomes stay reachable, so the rule can matter. *)
Theorem denied_speech_act_withholds : force denied_speech_act = Withholds.
Proof. reflexivity. Qed.

Theorem the_policy_split_is_reachable :
  force denied_speech_act = Withholds /\ force affirmative_evidential = Asserts.
Proof. split; reflexivity. Qed.

(* The two classes do not diverge: the old class split is unreachable. *)
Theorem the_class_split_is_unreachable :
  force denied_evidential = force denied_speech_act.
Proof. reflexivity. Qed.

Theorem a_prefix_can_change_its_mind :
  compose [affirmative_evidential] = Asserts /\
  compose [affirmative_evidential; denied_evidential] = Withholds.
Proof. split; reflexivity. Qed.

(* ------------------------------------------------------------------ *)
(* 5. The order is a lattice order, not a hack.                        *)
(* ------------------------------------------------------------------ *)

Theorem le_force_refl : forall x : Force, le_force x x.
Proof. intros x. destruct x; simpl; trivial. Qed.

Theorem le_force_antisym :
  forall x y : Force, le_force x y -> le_force y x -> x = y.
Proof. intros x y. destruct x, y; simpl; intros; try contradiction; reflexivity. Qed.

Theorem le_force_trans :
  forall x y z : Force, le_force x y -> le_force y z -> le_force x z.
Proof. intros x y z. destruct x, y, z; simpl; intros; try contradiction; trivial. Qed.

(* The meet is the greatest lower bound: below both, and above anything else that
   is below both. *)
Theorem meet_is_glb :
  forall x y : Force,
    le_force (meet x y) x /\ le_force (meet x y) y /\
    forall z, le_force z x -> le_force z y -> le_force z (meet x y).
Proof.
  intros x y. destruct x, y; simpl; intuition.
Qed.

Print Assumptions force_withholds_iff.
Print Assumptions force_extensional.
Print Assumptions compose_app.
Print Assumptions compose_withholds_iff.
Print Assumptions withholding_is_not_rescuable.
Print Assumptions meet_is_glb.
