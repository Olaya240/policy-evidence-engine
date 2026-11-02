; Antisymmetry of the signed-margin score, discharged by z3.
;
; The arithmetic core of `backend/app/decision_table.py::score`:
;
;     f(s, c) = (s - c) / (s + c + 1)
;
; over integer counts s, c >= 0. The Python code returns a float, which is a
; rounded image of this rational; the identity below is stated over the reals
; and therefore holds of the exact value the float approximates, not of the
; float itself. That distinction is the trust base (`ct3/audit/REFINEMENT-PROOF.md`).
;
; The query is the NEGATION of the claim. `unsat` means no counterexample exists.
;
;   z3 ct3/refinement/antisymmetry.smt2
;
(set-logic ALL)

(define-fun f ((s Int) (c Int)) Real
  (/ (- (to_real s) (to_real c))
     (+ (to_real s) (to_real c) 1.0)))

; Swapping the two directions negates the score: the sign is the direction and
; the magnitude is the strength, so a mirror image cannot read as a different
; strength.
(assert (not
  (forall ((s Int) (c Int))
    (=> (and (>= s 0) (>= c 0))
        (= (f s c) (- (f c s)))))))

(check-sat)
