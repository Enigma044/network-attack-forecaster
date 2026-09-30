import numpy as np
import pandas as pd
import pytest

from netforecast.windows import FEATURES, add_capture_id, assign_splits, build_windows, make_sequences


def flows_frame(times, labels, capture="cap:2018-02-14"):
    n = len(times)
    return pd.DataFrame(
        {
            "Timestamp": pd.to_datetime(times),
            "Dst Port": [22] * n,
            "Protocol": [6] * n,
            "Flow Duration": [1000] * n,
            "Tot Fwd Pkts": [3] * n,
            "Tot Bwd Pkts": [2] * n,
            "Label": labels,
            "is_attack": [0.0 if lab == "Benign" else 1.0 for lab in labels],
            "capture_id": capture,
        }
    )


def test_windows_fill_gaps_and_label_by_fraction():
    times = ["2018-02-14 08:00:05", "2018-02-14 08:00:50", "2018-02-14 08:03:10", "2018-02-14 08:03:20"]
    labels = ["Benign", "Benign", "Benign", "SSH-Bruteforce"]
    w = build_windows(flows_frame(times, labels), window_seconds=60, attack_fraction_threshold=0.4)
    assert list(w["window_start"].dt.strftime("%H:%M")) == ["08:00", "08:01", "08:02", "08:03"]
    assert list(w["n_flows"]) == [2, 0, 0, 2]
    assert list(w["is_attack"]) == [0, 0, 0, 1]
    assert w.loc[3, "stage"] == "Initial Access"
    assert w.loc[3, "top_label"] == "SSH-Bruteforce"
    assert set(FEATURES) <= set(w.columns)
    assert not w[FEATURES].isna().any().any()


def test_attack_fraction_threshold_respected():
    times = ["2018-02-14 08:00:0%d" % i for i in range(5)]
    labels = ["Benign"] * 4 + ["Bot"]
    w = build_windows(flows_frame(times, labels), attack_fraction_threshold=0.5)
    assert w.loc[0, "is_attack"] == 0 and w.loc[0, "stage"] is None
    w = build_windows(flows_frame(times, labels), attack_fraction_threshold=0.2)
    assert w.loc[0, "is_attack"] == 1 and w.loc[0, "stage"] == "Command and Control"


def test_capture_id_per_day():
    f = flows_frame(["2018-02-14 23:59:59", "2018-02-15 00:00:01"], ["Benign", "Benign"])
    f = add_capture_id(f.drop(columns="capture_id"), "/data/Thursday-15-02-2018.csv")
    assert list(f["capture_id"]) == ["Thursday-15-02-2018:2018-02-14", "Thursday-15-02-2018:2018-02-15"]


def _grid(n_caps=2, n=20):
    rows = []
    for c in range(n_caps):
        for t in range(n):
            rows.append({"capture_id": f"c{c}", "window_start": pd.Timestamp("2018-01-01") + pd.Timedelta(minutes=t),
                         "is_attack": float(t % 5 == 0), "stage": "Initial Access" if t % 5 == 0 else None})
    w = pd.DataFrame(rows)
    feats = np.arange(len(w) * 2, dtype="float32").reshape(len(w), 2)
    return w, feats


def test_sequence_shapes_and_future_alignment():
    w, feats = _grid(n_caps=1, n=20)
    s = make_sequences(w, feats, seq_len=4, k=3, window_seconds=60)
    assert s.X.shape == (20 - 4 - 3 + 1, 4, 2)
    assert s.FS.shape == (len(s), 3, 2) and s.FY.shape == (len(s), 3) and s.CY.shape == (len(s), 4)
    # first example: context windows 0..3, future windows 4..6
    np.testing.assert_array_equal(s.X[0], feats[0:4])
    np.testing.assert_array_equal(s.FS[0], feats[4:7])
    np.testing.assert_array_equal(s.FY[0], w.loc[4:6, "is_attack"].to_numpy())
    assert s.meta.loc[0, "forecast_start"] == w.loc[4, "window_start"]
    assert (s.FST[s.FY == 1] == 1).all() and (s.FST[s.FY == 0] == -100).all()
    np.testing.assert_array_equal(s.last_is_attack, s.CY[:, -1])


def test_sequences_never_cross_captures():
    w, feats = _grid(n_caps=2, n=10)
    s = make_sequences(w, feats, seq_len=4, k=2, window_seconds=60)
    assert len(s) == 2 * (10 - 4 - 2 + 1)
    for cap, grp in s.meta.groupby("capture_id"):
        cap_w = w.loc[w.capture_id == cap, "window_start"]
        assert (grp["input_start"] >= cap_w.min()).all()
        assert (grp["forecast_start"] + pd.Timedelta(minutes=1) <= cap_w.max()).all()


def test_include_future_adds_unlabeled_forecasts():
    w, feats = _grid(n_caps=1, n=10)
    s = make_sequences(w, feats, seq_len=4, k=2, window_seconds=60, include_future=True)
    assert len(s) == 10 - 4 + 1
    assert np.isnan(s.FY[-1]).all() and np.isnan(s.FY[-2, 1]) and not np.isnan(s.FY[-2, 0])
    assert list(s.meta["n_future_in_data"].tail(3)) == [2, 1, 0]
    assert s.meta["forecast_start"].iloc[-1] == w["window_start"].iloc[-1] + pd.Timedelta(minutes=1)


def test_short_capture_yields_no_sequences():
    w, feats = _grid(n_caps=1, n=3)
    assert len(make_sequences(w, feats, seq_len=4, k=1, window_seconds=60)) == 0


def test_capture_split_is_disjoint():
    w, _ = _grid(n_caps=5, n=10)
    out, info = assign_splits(w, seed=1)
    assert set(info.train) | set(info.val) | set(info.test) == {f"c{i}" for i in range(5)}
    assert not (set(info.train) & set(info.test)) and not (set(info.val) & set(info.test))
    assert out.groupby("capture_id")["split"].nunique().max() == 1


def test_explicit_split_and_unknown_capture():
    w, _ = _grid(n_caps=3, n=10)
    out, info = assign_splits(w, test_captures=["c2"], val_captures=["c1"])
    assert info.test == ["c2"] and info.val == ["c1"] and info.train == ["c0"]
    with pytest.raises(ValueError):
        assign_splits(w, test_captures=["nope"])


def test_chronological_fallback_blocks():
    w, feats = _grid(n_caps=1, n=50)
    out, info = assign_splits(w)
    assert info.method == "chronological-within-capture"
    assert list(out["split"].iloc[[0, 29, 30, 39, 40, 49]]) == ["train", "train", "val", "val", "test", "test"]
    # block-specific capture ids keep sequences inside one block
    s = make_sequences(out, feats, seq_len=4, k=2, window_seconds=60)
    assert set(s.meta["capture_id"]) == {"c0#train", "c0#val", "c0#test"}


def test_blocked_validation_from_training_captures():
    w, feats = _grid(n_caps=4, n=50)  # attack every 5th window, so every block has attacks
    out, info = assign_splits(w, test_captures=["c3"], val_block_windows=10)
    assert info.method.endswith("blocked-val") and info.test == ["c3"]
    assert set(out.loc[out["split"] == "test", "capture_id"]) == {"c3"}
    val_ids = set(out.loc[out["split"] == "val", "capture_id"])
    assert val_ids == set(info.val) and len(val_ids) == 3  # 20% of 15 training blocks
    assert all("#block" in v for v in val_ids)
    assert not val_ids & set(out.loc[out["split"] == "train", "capture_id"])
    s = make_sequences(out, np.zeros((len(out), 2), dtype="float32"), seq_len=4, k=2, window_seconds=60)
    assert not s.meta["capture_id"].isin(["c0", "c1", "c2"]).any()


def test_blocked_split_also_reserves_unseen_hour_test_blocks():
    w, _ = _grid(n_caps=4, n=50)
    out, info = assign_splits(w, test_captures=["c3"], val_block_windows=10)
    hours = set(out.loc[out["split"] == "test_hours", "capture_id"])
    assert hours == set(info.test_hours) and len(hours) == 2  # 15% of 15 training blocks
    assert not hours & set(info.val)
    assert info.as_dict()["test_hours"] == info.test_hours
