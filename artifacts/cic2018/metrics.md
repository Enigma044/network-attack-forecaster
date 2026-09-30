# World-model forecast evaluation

> Data: CIC-IDS-2018 CSV files listed in config.json.

- Evaluated on: held-out test split
- Context: 10 windows × 60s; forecast: next 10 windows
- Split method: by-capture+blocked-val
- Thresholds: max F1 on validation split

## Attack within the next 10 windows

| Model | Precision | Recall | F1 | FPR | AP |
|---|---|---|---|---|---|
| World model (LSTM dynamics + rollout) | 0.077 | 0.012 | 0.020 | 0.026 | 0.2868 |
| Logistic regression (baseline) | 1.000 | 0.092 | 0.169 | 0.000 | 0.3611 |
| Persistence reference* | 0.987 | 0.884 | 0.933 | 0.002 | 0.8914 |

## Attack in window t+1

| Model | Precision | Recall | F1 | FPR | AP |
|---|---|---|---|---|---|
| World model (LSTM dynamics + rollout) | 0.130 | 0.019 | 0.034 | 0.021 | 0.2548 |
| Logistic regression (baseline) | 0.875 | 0.045 | 0.086 | 0.001 | 0.3916 |
| Persistence reference* | 0.987 | 0.987 | 0.987 | 0.002 | 0.9762 |

## Attack in window t+5

| Model | Precision | Recall | F1 | FPR | AP |
|---|---|---|---|---|---|
| World model (LSTM dynamics + rollout) | 0.037 | 0.006 | 0.011 | 0.028 | 0.2855 |
| Logistic regression (baseline) | 0.636 | 0.045 | 0.084 | 0.004 | 0.2467 |
| Persistence reference* | 0.935 | 0.935 | 0.935 | 0.011 | 0.8843 |

## Attack in window t+10

| Model | Precision | Recall | F1 | FPR | AP |
|---|---|---|---|---|---|
| World model (LSTM dynamics + rollout) | 0.037 | 0.006 | 0.011 | 0.028 | 0.3011 |
| Logistic regression (baseline) | 0.000 | 0.000 | 0.000 | 0.005 | 0.1395 |
| Persistence reference* | 0.871 | 0.871 | 0.871 | 0.021 | 0.777 |

## Early warning: attack within 10 windows when the latest window is still benign

| Model | Precision | Recall | F1 | FPR |
|---|---|---|---|---|
| World model (LSTM dynamics + rollout) | 0.000 | 0.000 | 0.000 | 0.026 |
| Logistic regression (baseline) | 0.000 | 0.000 | 0.000 | 0.000 |

## Test B: unseen hours of the training days (attack within 10 windows)

| Model | Precision | Recall | F1 | FPR | AP |
|---|---|---|---|---|---|
| World model (LSTM dynamics + rollout) | 0.462 | 0.218 | 0.296 | 0.034 | 0.3009 |
| Logistic regression (baseline) | 0.933 | 0.255 | 0.400 | 0.002 | 0.4724 |
| Persistence reference* | 1.000 | 0.564 | 0.721 | 0.000 | 0.6149 |

\* Persistence predicts that the future looks like the latest window. It needs ground-truth labels, so it is a reference point, not a deployable model.

Stage head: {"n": 1550, "accuracy": 0.2374, "true_stage_counts": {"Lateral Movement": 1550}, "stages_unseen_in_training": [], "note": "Future windows that are attack windows with a mapped stage (all K steps)."}

Split:
- train: Friday-02-03-2018_TrafficForML_CICFlowMeter:2018-03-02, Friday-16-02-2018_TrafficForML_CICFlowMeter:2018-02-16, Thursday-15-02-2018_TrafficForML_CICFlowMeter:2018-02-15, Thursday-22-02-2018_TrafficForML_CICFlowMeter:2018-02-22, Wednesday-14-02-2018_TrafficForML_CICFlowMeter:2018-02-14, Wednesday-21-02-2018_TrafficForML_CICFlowMeter:2018-02-21, Wednesday-28-02-2018_TrafficForML_CICFlowMeter:2018-02-28
- val: Thursday-15-02-2018_TrafficForML_CICFlowMeter:2018-02-15#block0, Wednesday-14-02-2018_TrafficForML_CICFlowMeter:2018-02-14#block0, Wednesday-14-02-2018_TrafficForML_CICFlowMeter:2018-02-14#block1, Wednesday-21-02-2018_TrafficForML_CICFlowMeter:2018-02-21#block2, Wednesday-28-02-2018_TrafficForML_CICFlowMeter:2018-02-28#block0, Wednesday-28-02-2018_TrafficForML_CICFlowMeter:2018-02-28#block2, Wednesday-28-02-2018_TrafficForML_CICFlowMeter:2018-02-28#block4
- test: Friday-23-02-2018_TrafficForML_CICFlowMeter:2018-02-23, Thursday-01-03-2018_TrafficForML_CICFlowMeter:2018-03-01
- note: explicit capture lists; validation = 7 and test_hours = 5 blocks of 120 windows drawn (stratified by attack presence, seed=42) from the training captures; blocks never share a sequence; test captures are entire unseen days
