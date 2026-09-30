import json

import numpy as np
import pytest
import torch

from netforecast.explain import explain_forecast, shapley_features, summarize, temporal_importance
from netforecast.models import (
    HorizonBaseline, WorldModel, WorldModelConfig, any_within, binary_metrics, simulate, train_world_model, tune_threshold,
    world_model_loss,
)
from netforecast.pipeline import analyze, evaluate_files, flow_evidence
from netforecast.schema import load_flows
from netforecast.stages import STAGES
from netforecast.windows import FEATURES


def test_world_model_heads_and_rollout_shapes():
    model = WorldModel(n_features=7, hidden=8)
    mu, logvar, a, s = model(torch.zeros(4, 10, 7))
    assert mu.shape == logvar.shape == (4, 10, 7) and a.shape == (4, 10) and s.shape == (4, 10, len(STAGES))
    logits, stages, states = model.rollout(torch.zeros(4, 10, 7), k=5)
    assert logits.shape == (4, 5) and stages.shape == (4, 5, len(STAGES)) and states.shape == (4, 5, 7)


def test_simulate_outputs_and_sampling_band():
    model = WorldModel(n_features=5, hidden=8)
    out = simulate(model, np.random.default_rng(0).normal(size=(6, 4, 5)).astype("float32"), k=3, n_samples=8)
    assert out["p"].shape == (6, 3) and out["stage"].shape == (6, 3, len(STAGES)) and out["any"].shape == (6,)
    assert ((out["q10"] <= out["q90"] + 1e-6)).all()
    assert ((out["any"] >= 0) & (out["any"] <= 1)).all()
    np.testing.assert_allclose(out["stage"].sum(-1), 1.0, rtol=1e-5)


def test_loss_is_finite_and_trains():
    rng = np.random.default_rng(0)
    n, L, K, F = 40, 4, 3, 5
    data = {
        "X": rng.normal(size=(n, L, F)).astype("float32"),
        "FS": rng.normal(size=(n, K, F)).astype("float32"),
        "FY": (rng.random((n, K)) < 0.3).astype("float32"),
        "FST": np.full((n, K), -100, dtype=np.int64),
        "CY": (rng.random((n, L)) < 0.3).astype("float32"),
        "CST": np.full((n, L), -100, dtype=np.int64),
    }
    data["FY"][0, 0] = np.nan  # unknown labels are masked
    model, history = train_world_model(data, None, WorldModelConfig(epochs=2, hidden=8), log=lambda *_: None)
    assert len(history) == 2 and all(np.isfinite(h["train_loss"]) for h in history)
    loss, nll = world_model_loss(model, {k: torch.from_numpy(v) for k, v in data.items()}, WorldModelConfig(), torch.tensor(1.0))
    assert torch.isfinite(loss) and np.isfinite(nll)


def test_any_within_and_baseline():
    FY = np.array([[0, 0, 1], [0, 0, 0], [np.nan, 0, 0], [np.nan, 1, 0]], dtype="float32")
    np.testing.assert_array_equal(np.isnan(any_within(FY)), [False, False, True, False])
    assert list(np.nan_to_num(any_within(FY), nan=-1)) == [1, 0, -1, 1]
    rng = np.random.default_rng(1)
    X = rng.normal(size=(30, 3, 4)).astype("float32")
    FYb = (rng.random((30, 2)) < 0.5).astype("float32")
    out = HorizonBaseline().fit(X, FYb).predict(X)
    assert out["p"].shape == (30, 2) and out["any"].shape == (30,)


def test_metrics_and_threshold():
    y = np.array([0, 0, 1, 1])
    m = binary_metrics(y, np.array([0.1, 0.6, 0.7, 0.2]), 0.5)
    assert (m["tp"], m["fp"], m["tn"], m["fn"]) == (1, 1, 1, 1)
    assert m["false_positive_rate"] == 0.5 and m["precision"] == 0.5
    th, _ = tune_threshold(y, np.array([0.1, 0.2, 0.8, 0.9]))
    assert 0.2 < th <= 0.8
    assert tune_threshold(np.zeros(4), np.zeros(4))[0] == 0.5


def test_shapley_values_sum_to_prediction_minus_baseline():
    torch.manual_seed(0)
    model = WorldModel(n_features=6, hidden=8).eval()
    x = np.random.default_rng(2).normal(size=(5, 6)).astype("float32")
    phi, pred, base = shapley_features(model, x, k=3, n_permutations=6)
    assert phi.shape == (6,)
    assert phi.sum() == pytest.approx(pred - base, abs=1e-4)
    assert temporal_importance(model, x, k=3).shape == (5,)


def test_training_writes_bundle_and_metrics(trained_bundle):
    out, bundle, metrics = trained_bundle
    for name in ("world_model.pt", "baseline.joblib", "scaler.joblib", "config.json", "metrics.json", "metrics.md"):
        assert (out / name).exists()
    assert metrics["data_kind"] == "synthetic"
    assert "SYNTHETIC" in (out / "metrics.md").read_text()
    block = metrics["targets"]["any"]
    for key in ("world_model", "logistic_regression", "persistence_reference"):
        assert {"precision", "recall", "f1", "false_positive_rate"} <= set(block[key])
    assert set(metrics["targets"]) == {"any", "step_1", "step_3"}
    assert not set(metrics["split"]["train"]) & set(metrics["split"]["test"])
    cfg = json.loads((out / "config.json").read_text())
    assert cfg["features"] == FEATURES and cfg["seq_len"] == 6 and cfg["k"] == 3
    assert len(cfg["thresholds"]["world_model"]["steps"]) == 3


def test_analyze_produces_forecasts_and_explanation(trained_bundle, synthetic_dir):
    _, bundle, _ = trained_bundle
    path = sorted(synthetic_dir.glob("*.csv"))[0]
    flows, _ = load_flows(path)
    result = analyze(flows, path.name, bundle)
    fc = result.forecasts
    assert len(fc) == len(result.windows) - bundle.config["seq_len"] + 1
    assert fc["wm_any"].between(0, 1).all() and fc["lr_any"].between(0, 1).all()
    assert result.steps["wm_p"].shape == (len(fc), bundle.config["k"])
    assert (fc["n_future_in_data"] == 0).sum() == 1
    assert fc.loc[~fc["wm_alert"], "predicted_stage"].isna().all()
    assert result.metrics is not None and "any" in result.metrics["targets"]

    ex = explain_forecast(bundle.model, result.sequences.X[0], FEATURES, bundle.config["k"], n_permutations=4)
    assert len(ex["table"]) == len(FEATURES)
    assert ex["table"]["shap_logodds"].sum() == pytest.approx(ex["pred_logodds"] - ex["base_logodds"], abs=1e-3)
    assert isinstance(summarize(ex["table"]), list)
    rows = flow_evidence(result, len(fc) // 2, bundle.config["window_seconds"])
    assert rows and {"Dst Port", "Protocol", "flows", "growth"} <= set(rows[0])


def test_analyze_rejects_too_short_input(trained_bundle, synthetic_dir):
    _, bundle, _ = trained_bundle
    flows, _ = load_flows(sorted(synthetic_dir.glob("*.csv"))[0])
    short = flows[flows["Timestamp"] < flows["Timestamp"].iloc[0] + np.timedelta64(3, "m")]
    with pytest.raises(ValueError, match="Not enough data"):
        analyze(short, "short.csv", bundle)


def test_evaluate_flags_training_overlap(trained_bundle, synthetic_dir):
    out, _, _ = trained_bundle
    metrics = evaluate_files(out, [sorted(synthetic_dir.glob("*.csv"))[0]], log=lambda *_: None)
    assert "WARNING" in metrics["note"]
    assert (out / "eval_metrics.md").exists()
