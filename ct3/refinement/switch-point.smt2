; The reported score is not monotone in the undisputed support at a status
; switch. Discharged by z3: `sat` with a model, which is the counterexample.
;
; `decide` in `backend/app/decision_table.py` labels the evidence, then labels it
; again *as if* the challenged groups counted. When the two labels differ the
; verdict is withheld and the reported score is re-priced to the challenged
; configuration. So on one side of the switch the number is `f(s, c)` and on the
; other it is `f(s+ds, c+dc)`, computed from a different pair of counts.
;
; Encoded here: the label arms of `_label` under the default policy
; `POLICY_SIGNED_MARGIN` (min_support_groups = 2, imbalance_per_group = 3,
; contest_blocks_decisive = False), the same arms `ct3/DecisionTable.v` proves
; properties of, plus the re-pricing rule. `gap` is declared only so that z3
; prints the size of the inversion in its model rather than just `sat`.
;
;   z3 ct3/refinement/switch-point.smt2
;
(set-logic ALL)

; 0 = SUPPORTED, 1 = PARTIAL, 2 = CONTRADICTED, 3 = INSUFFICIENT. The order is
; irrelevant to the query (only equality of labels is used); it matches
; `tstatus_code` in `ct3/refinement/generate_table.v`.
(define-fun label ((s Int) (c Int)) Int
  (ite (and (>= s 2) (>= s (+ (* 3 c) 1))) 0
    (ite (>= c (+ (* 3 s) 1)) 2
      (ite (and (= s 0) (= c 0)) 3 1))))

(define-fun f ((s Int) (c Int)) Real
  (/ (- (to_real s) (to_real c))
     (+ (to_real s) (to_real c) 1.0)))

; The number `decide` reports: the undisputed score when nothing is challenged
; or the challenge cannot change the label, otherwise the challenged score.
(define-fun reported ((s Int) (c Int) (ds Int) (dc Int)) Real
  (ite (= 0 (+ ds dc))
       (f s c)
       (ite (= (label s c) (label (+ s ds) (+ c dc)))
            (f s c)
            (f (+ s ds) (+ c dc)))))

(declare-const gap Real)

; The two rows the switch point is made of: one more supporting group, a lower
; reported number.
(assert (< (reported 2 0 0 1) (reported 1 0 0 1)))

; Recorded so the model carries the size of the inversion.
(assert (= gap (- (reported 1 0 0 1) (reported 2 0 0 1))))

(check-sat)
(get-model)
