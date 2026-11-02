# Conformal stance sets — a guarantee instead of a magnitude

Workstream: Prediction-set validity (replaces the unjustifiable read of
`Decision.confidence`). Question in one sentence: **can the system return, instead of a
number that looks like a probability, a set of stances with a coverage guarantee at a stated
level — and what exactly would that guarantee be conditional on?**

Files: `backend/app/calibration.py` (new), `backend/tests/test_calibration.py` (new, the
executed harness), this document. Nothing in `app/decision_table.py` or `app/models.py` was
changed; the new module does not import either.

Run, verbatim:

```
cd /home/alex/policy-evidence-fix/backend && PYTHONPATH=. /home/alex/policy-evidence-latest/.venv/bin/python -m pytest -q -s tests/test_calibration.py
..
  rows: pool=3000 fit=2000 held_out=1000
  alpha=0.05  n_cal=1000  n_eval=1000  coverage=0.9500 target=0.95 mean_set=2.189 max_set=3 quantile=0.8642
  alpha=0.1   n_cal=1000  n_eval=1000  coverage=0.8940 target=0.90 mean_set=1.794 max_set=3 quantile=0.8000
  alpha=0.2   n_cal=1000  n_eval=1000  coverage=0.8220 target=0.80 mean_set=1.430 max_set=3 quantile=0.7145
..
  alpha=0.02  mean_set=2.461
  alpha=0.05  mean_set=2.189
  alpha=0.1   mean_set=1.794
  alpha=0.2   mean_set=1.430
  alpha=0.5   mean_set=1.000
............
16 passed in 4.37s
```

## The method, in ten lines

1. Label space: `STANCE_LABELS = ("SUPPORTS", "CONTRADICTS", "NEUTRAL")`, pinned to
   `app.models.Stance` by `test_label_space_matches_the_stance_enum`.
2. `fit(rows)` takes `(features, true_label)` rows and splits them with a fixed seed: half
   train the score function, half calibrate.
3. The score function is a multinomial logistic regression — standardise features, softmax
   over `W x + b`, full-batch gradient descent, zero init, no RNG, 400 iterations.
4. Nonconformity `A(x, y) = 1 - p(y | x)`: how badly the model likes the true label, in
   `[0, 1 - 1/K]`, lower is better.
5. One nonconformity per calibration row, giving `n` scores.
6. Threshold `q̂` is the `k`-th smallest score, `k = ceil((n + 1)(1 - alpha))` — the
   finite-sample correction that pays for the test point not being in the calibration sample.
7. Prediction set is `{ y : A(x, y) <= q̂ }`, union the argmax label, so it is never empty.
8. If `k > n`, `q̂ = +inf` and the set is the whole label space: `n` cannot certify the level.
9. Guarantee: `P(true label ∈ set) >= 1 - alpha`, over the joint draw of calibration and test
   data, for any score function — including a bad one.
10. The score function only sets the *size* of the set. Coverage is a property of the
    construction, not of the model's accuracy. That is the whole reason to prefer it to a
    hand-tuned threshold on `confidence`.

## Achieved coverage

Held-out rows only: 1000 rows that neither trained the score function nor calibrated the
quantile. Generator: 3000 i.i.d. rows (seed 20260601), split 2000 / 1000 with `split_rows`
(seed 17); the fitting 2000 split again 1000 / 1000.

| alpha | target `1 - alpha` | calibration `n` | evaluated `n` | achieved coverage | mean set size | max set size | `q̂` |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 0.05 | 0.95 | 1000 | 1000 | **0.9500** | 2.189 | 3 | 0.8642 |
| 0.10 | 0.90 | 1000 | 1000 | **0.8940** | 1.794 | 3 | 0.8000 |
| 0.20 | 0.80 | 1000 | 1000 | **0.8220** | 1.430 | 3 | 0.7145 |

The 0.10 row is 0.006 below its target. That is not a bug and not a rounding of the result:
the guarantee is **marginal in expectation** over the draw of calibration and test data, not
a promise about one realised draw. With 1000 evaluation rows the standard error of a 0.90
proportion is about 0.0095, so a single draw landing 0.6 standard errors low is ordinary.The test asserts the bound with a tolerance of 0.02 — between two and three standard errors
across the three levels — rather than asserting the exact target, which would be a test of the
seed, not of the method.

Set size falls as `alpha` rises, exactly as it must: at `alpha = 0.5` the mean set is a single
label, and at `alpha = 0.02` it is 2.461 of 3. The generator is deliberately overlapping
(Bayes accuracy is around 0.55), so the sets are not decorative: a 95% guarantee on this
problem genuinely does cost more than two labels on average. A larger, real feature set would
buy smaller sets; nothing in the method changes.

## The assumptions, exactly

1. **Exchangeability.** The calibration rows and the test row are exchangeable: their joint
   distribution is invariant under permutation. In practice: i.i.d. from one distribution.
2. **The calibration sample is disjoint from the score function's training sample**, and from
   the evaluation sample. `fit` enforces the first by splitting internally; `evaluate`
   enforces the second by raising `CalibrationLeakageError` on any row `fit` was given.
3. **The score function is fixed before the test point is scored.** It is: `fit` is the only
   thing that changes it, and it never sees a test row.
4. **Labels are the true labels of the distribution being covered.** Whose truth is circular
   here, and the next section says so.
5. **`0 < alpha < 1`**, and `n >= ceil(1/alpha) - 1` for the level to be certifiable at all.
   Below that the answer is the full label space, not a crash and not a guess.

No independence between features and labels beyond exchangeability; no distributional
assumption at all; no assumption that the model is correct. Those are the method's real
virtues and they survive contact with an adversarial domain, unlike a Gaussian error bar.

## What this does not give you

**Exchangeability is not testable from one sample.** You have one review set. Any test of
exchangeability either assumes a distribution you do not have, or compares two samples drawn
from a process that may already have drifted. So the assumption is *asserted* here, and if it
is false the coverage number is false with no observable warning: the method does not complain
when its premise fails, it just quietly stops covering. Evidence routed by hypothesis priority,
by date, or by which reviewer was on shift is not exchangeable, and neither is a corpus that
grew while the labelling policy changed mid-stream. This is the one failure mode the audit
cannot rule out, and it is the one that matters.

**The labels in this system are agent-written.** `p(y | x)` is trained against labels the
engine produced, and the conformal quantile is calibrated against the same provenance. So the
guarantee is: *the set contains the agent's own label with probability >= 1 - alpha*. That is
close to worthless as evidence about the domain — it certifies self-consistency, not
correctness. A real guarantee needs a human-labelled, exchangeable calibration set with
documented labelling policy, and it needs it to be disjoint from anything the model or the
prompt was tuned on. Until that exists, this module is machinery with no certificate attached.

**Coverage on synthetic data proves the implementation, not the domain.** The generator in
`test_calibration.py` is i.i.d. by construction, which is exactly why its coverage lands on
`1 - alpha`. It is a unit test of the quantile, the split, the leakage guard and the
non-emptiness fallback — and it would keep passing on evidence where the assumption is false.
Do not quote the table above as a property of the engine.

**The set can be the full label space**, and at small `n` it will be. That is the method
reporting that it cannot certify the level, which is the correct answer and an unusable one
for a UI that expects a label. Any caller that maps "3 of 3 labels" back to one stance
reintroduces the exact problem this module was built to remove.

**Marginal, not conditional.** `1 - alpha` is the average over test points. On the hard points
— the ones where the evidence is genuinely split — coverage can be far below `1 - alpha` while
the average holds. If the decision needs per-point reliability (does *this* claim's set cover?),
that is a conditional guarantee, and split conformal does not provide one.

**No help with the harder half.** A valid set is not a defensible claim. Coverage says the
set contains the truth at a stated rate; it says nothing about whether the feature vector is
the right representation of the evidence, whether the labels are the ones a reviewer would
choose, or whether `p(y | x)` being accurate on the training distribution survives a shift in
what evidence gets submitted.
