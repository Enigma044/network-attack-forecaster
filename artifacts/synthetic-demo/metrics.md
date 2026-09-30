# World-model forecast evaluation

> **SYNTHETIC SMOKE-TEST DATA.** These numbers only show that the pipeline runs end to end. They say nothing about performance on real traffic.

- Evaluated on: held-out test split
- Context: 10 windows × 60s; forecast: next 10 windows
- Split method: by-capture
- Thresholds: max F1 on validation split

## Attack within the next 10 windows

| Model | Precision | Recall | F1 | FPR | AP |
|---|---|---|---|---|---|
| World model (LSTM dynamics + rollout) | 0.974 | 0.895 | 0.933 | 0.021 | 0.9487 |
| Logistic regression (baseline) | 0.988 | 0.766 | 0.863 | 0.009 | 0.9468 |
| Persistence reference* | 0.989 | 0.876 | 0.929 | 0.009 | 0.925 |

## Attack in window t+1

| Model | Precision | Recall | F1 | FPR | AP |
|---|---|---|---|---|---|
| World model (LSTM dynamics + rollout) | 0.972 | 0.935 | 0.953 | 0.019 | 0.986 |
| Logistic regression (baseline) | 0.981 | 0.816 | 0.891 | 0.012 | 0.9656 |
| Persistence reference* | 0.978 | 0.978 | 0.978 | 0.016 | 0.9663 |

## Attack in window t+5

| Model | Precision | Recall | F1 | FPR | AP |
|---|---|---|---|---|---|
| World model (LSTM dynamics + rollout) | 0.911 | 0.941 | 0.925 | 0.066 | 0.9017 |
| Logistic regression (baseline) | 0.865 | 0.724 | 0.788 | 0.082 | 0.8708 |
| Persistence reference* | 0.919 | 0.919 | 0.919 | 0.058 | 0.8783 |

## Attack in window t+10

| Model | Precision | Recall | F1 | FPR | AP |
|---|---|---|---|---|---|
| World model (LSTM dynamics + rollout) | 0.870 | 0.832 | 0.851 | 0.089 | 0.7375 |
| Logistic regression (baseline) | 0.771 | 0.546 | 0.639 | 0.117 | 0.7697 |
| Persistence reference* | 0.881 | 0.881 | 0.881 | 0.086 | 0.8261 |

## Early warning: attack within 10 windows when the latest window is still benign

| Model | Precision | Recall | F1 | FPR |
|---|---|---|---|---|
| World model (LSTM dynamics + rollout) | 0.667 | 0.231 | 0.343 | 0.013 |
| Logistic regression (baseline) | 0.000 | 0.000 | 0.000 | 0.004 |

\* Persistence predicts that the future looks like the latest window. It needs ground-truth labels, so it is a reference point, not a deployable model.

Stage head: {"n": 1770, "accuracy": 0.6571, "true_stage_counts": {"Reconnaissance": 180, "Initial Access": 780, "Lateral Movement": 210, "Command and Control": 600}, "stages_unseen_in_training": [], "note": "Future windows that are attack windows with a mapped stage (all K steps)."}

Split:
- train: synthetic_2026-01-06:2026-01-06, synthetic_2026-01-07:2026-01-07, synthetic_2026-01-08:2026-01-08, synthetic_2026-01-09:2026-01-09, synthetic_2026-01-13:2026-01-13, synthetic_2026-01-14:2026-01-14
- val: synthetic_2026-01-05:2026-01-05, synthetic_2026-01-12:2026-01-12
- test: synthetic_2026-01-10:2026-01-10, synthetic_2026-01-11:2026-01-11
- note: random capture split, seed=42
