from datetime import datetime, timedelta

import pytest

from netforecast.synthetic import generate_capture


@pytest.fixture(scope="session")
def synthetic_dir(tmp_path_factory):
    """Five short synthetic captures (smoke-test data only)."""
    out = tmp_path_factory.mktemp("synthetic")
    for i in range(5):
        day = datetime(2026, 1, 5, 9, 0) + timedelta(days=i)
        generate_capture(day, seed=100 + i, hours=3.0).to_csv(out / f"synthetic_{day:%Y-%m-%d}.csv", index=False)
    return out


@pytest.fixture(scope="session")
def trained_bundle(synthetic_dir, tmp_path_factory):
    from netforecast.models import WorldModelConfig
    from netforecast.pipeline import TrainConfig, load_bundle, train_pipeline

    out = tmp_path_factory.mktemp("model")
    cfg = TrainConfig(seq_len=6, k=3, wm=WorldModelConfig(epochs=3, hidden=8))
    metrics = train_pipeline([synthetic_dir], out, cfg, log=lambda *_: None)
    return out, load_bundle(out), metrics
