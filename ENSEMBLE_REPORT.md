# Stacking Ensemble Report

Evaluation date: 2026-07-05. All numbers below come from executions on
this machine during this audit; nothing is projected or assumed.

## 1. Is the ensemble wired in?

**Code wiring: yes.** Verified by reading and executing the paths:

- `predictor.run_prediction` and `predictor.ml_signal` both load
  `stacking_meta_<TICKER>.pkl` (+ scaler, meta_cols, top10_idx) when
  present, add the stacking prediction to the model vote, and use it as
  the primary prediction.
- The accuracy engine grades whatever `run_prediction` emits (rows in
  `prediction_history` are checked into `prediction_accuracy`), so a
  stacking-driven prediction is automatically gradeable.
- The paper trader's `ml_ensemble` strategy consumes `ml_signal`, so a
  stacking-driven signal is automatically tradeable on paper.

**Deployment: no.** There are no valid stacking artifacts in
`Saved Models/`. The trainer (`stacking_ensemble.py`) consumes the
21-column `Data/<TICKER>_featured.csv` files, while the live models are
trained on a 70+ column feature builder. Artifacts trained from the CSVs
are incompatible with the live inference path (`top10_idx` would index
the wrong feature matrix), so after the evaluation below the trained
files were deliberately NOT deployed and the production models were
restored. Deploying stacking requires regenerating the featured datasets
through the live feature pipeline first.

## 2. Trainer defects found while producing this report

The stacking trainer had never completed a real run. Executing it
surfaced and fixed:

1. `build_stacking_ensemble` crashed with a shape mismatch (1458 vs
   1462): the close-price array was re-derived with a different dropna
   row set than the training split. Fixed by exporting split-aligned
   `close_train`/`close_val` from `load_data`.
2. The final test evaluation crashed (`'Ridge' object has no attribute
   'transform'`): the meta-learner and scaler were loaded into swapped
   variables. Fixed.

## 3. Results: chronological holdout (last 10% of data, never seen in training)

Training used 80/10/10 chronological splits with 5-fold CV out-of-fold
meta-features (no shuffle leakage into the test window).

### AAPL (1,828 rows, 2019-02 to 2026-06; test n=183)

| Model | MAE ($) | RMSE ($) | R2 | Direction accuracy |
|-------|---------|----------|----|--------------------|
| Linear Regression | **2.70** | **3.71** | 0.9457 | 52.7% |
| Random Forest | 2.72 | 3.71 | 0.9457 | 53.8% |
| XGBoost | 2.86 | 3.86 | 0.9413 | **57.7%** |
| LightGBM | 3.12 | 4.10 | 0.9336 | 52.2% |
| **Stacking (Ridge meta)** | 2.73 | 3.75 | 0.9446 | 56.0% |

### QQQ (test n=183)

| Model | MAE ($) | RMSE ($) | R2 | Direction accuracy |
|-------|---------|----------|----|--------------------|
| Linear Regression | **4.53** | **6.30** | 0.9948 | 51.2% |
| Random Forest | 5.12 | 6.95 | 0.9936 | 51.5% |
| XGBoost | 5.11 | 7.00 | 0.9935 | **52.3%** |
| LightGBM | 4.96 | 7.00 | 0.9935 | 52.1% |
| **Stacking (Ridge meta)** | 4.65 | 6.39 | 0.9946 | 51.1% |

## 4. Verdict, stated plainly

**The stacking ensemble does not beat the best single base model on
either ticker.**

- On price error (MAE), Linear Regression wins both tickers; stacking is
  second on AAPL (2.73 vs 2.70) and second on QQQ (4.65 vs 4.53).
- On direction accuracy, the metric a trading strategy actually monetizes,
  XGBoost wins both tickers (57.7% and 52.3%); stacking is second on AAPL
  (56.0%) and last on QQQ (51.1%).

What can honestly be claimed: stacking is competitive and more balanced
than any single weak learner (it never finishes worse than second on
AAPL), but on this data it is an averaging device, not an edge. If one
model had to be deployed per ticker today, the evidence supports XGBoost
for direction or LR for price level, not the stack.

Also for honesty: direction accuracies of 51-58% on daily bars are thin
edges. The AAPL 57.7% (XGBoost, n=183) is the only figure that looks
meaningfully better than a coin flip, and it has not been validated
across regimes by true walk-forward (see next section).

## 5. Walk-forward status

`walk_forward.py` was executed for AAPL with 5 purged/embargoed folds in
`ml`, `fused`, and `tech` modes. All three produced byte-identical
results (100 trades, avg profit factor 2.22, avg Sharpe -0.62,
`is_robust: false`), which proved the per-fold backtest runs a fixed
SMA20/50 crossover and ignores the mode: **per-fold model training is
not implemented**. The function now logs a warning stating exactly this,
so its output cannot be mistaken for a model evaluation. A true
walk-forward of the ensemble remains future work and is a prerequisite
for any claim that these models are robust across regimes.

## 6. What a panel can be shown today

- The stacking trainer running end to end and printing the honest
  comparison table above (`python stacking_ensemble.py --ticker AAPL`).
- The live product predicting with LR+RF (+LSTM on AAPL), graded by the
  accuracy engine, and trading on paper.
- This report, including the negative result. A defensible statement is:
  "We built and evaluated a stacking ensemble; on held-out data it did
  not outperform the best single model, so it is not deployed."
