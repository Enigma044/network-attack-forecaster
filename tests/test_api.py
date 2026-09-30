import io
import shutil

import pytest
from fastapi.testclient import TestClient

import netforecast.api as api_mod


@pytest.fixture()
def client(trained_bundle, synthetic_dir, tmp_path, monkeypatch):
    model_dir, _, _ = trained_bundle
    artifacts = tmp_path / "artifacts"
    shutil.copytree(model_dir, artifacts / "test-model")
    monkeypatch.setattr(api_mod, "ARTIFACTS", artifacts)
    monkeypatch.setattr(api_mod, "SAMPLE_DIRS", {"synthetic": synthetic_dir, "cic2018": tmp_path / "none"})
    api_mod._bundles.clear()
    api_mod._analyses.clear()
    return TestClient(api_mod.app)


def test_models_and_samples(client, synthetic_dir):
    models = client.get("/api/models").json()
    assert [m["name"] for m in models] == ["test-model"]
    assert models[0]["data_kind"] == "synthetic" and models[0]["k"] == 3
    assert models[0]["metrics"]["targets"]["any"]["world_model"]["f1"] is not None
    samples = client.get("/api/samples").json()
    assert [s["name"] for s in samples] == sorted(p.name for p in synthetic_dir.glob("*.csv"))
    assert {s["kind"] for s in samples} == {"synthetic"}


def test_analyze_demo_file_and_explain(client, synthetic_dir):
    name = sorted(synthetic_dir.glob("*.csv"))[0].name
    res = client.post("/api/analyze", data={"model": "test-model", "sample": f"synthetic/{name}"})
    assert res.status_code == 200
    body = res.json()
    assert body["report"]["ok"] and body["report"]["data_kind"] == "synthetic"
    fc = body["forecasts"]
    assert fc and {"row", "input_end", "forecast_start", "wm_any", "lr_any", "predicted_stage"} <= set(fc[0])
    assert all(0 <= f["wm_any"] <= 1 for f in fc)
    assert body["metrics"]["targets"]["any"]["world_model"]["n"] > 0

    d = client.get(f"/api/forecast/{body['id']}/5").json()
    assert len(d["rollout"]["world_model"]) == 3 == len(d["rollout"]["q90"]) == len(d["rollout"]["times"])
    assert len(d["shap"]["features"]) == 10 and d["shap"]["groups"]
    assert len(d["temporal"]) == 6 and len(d["evidence"]) == 3 and d["flows"]
    assert client.get(f"/api/forecast/{body['id']}/999999").status_code == 404
    assert client.get("/api/forecast/unknown/0").status_code == 404


def test_upload_validation_error_returns_report(client):
    csv = io.BytesIO(b"Dst Port,Protocol\n22,6\n")
    res = client.post("/api/analyze", data={"model": "test-model"}, files={"file": ("bad.csv", csv, "text/csv")})
    assert res.status_code == 422
    report = res.json()["report"]
    assert not report["ok"] and "Missing required column" in report["errors"][0]


def test_path_traversal_rejected(client):
    assert client.post("/api/analyze", data={"model": "../artifacts/test-model", "sample": "synthetic/x.csv"}).status_code == 404
    assert client.post("/api/analyze", data={"model": "test-model", "sample": "synthetic/../../etc/passwd"}).status_code == 404
    assert client.post("/api/analyze", data={"model": "test-model", "sample": "other/x.csv"}).status_code == 404


def test_health_and_upload_limit(client, monkeypatch):
    assert client.get("/api/health").json() == {"ok": True}
    monkeypatch.setattr(api_mod, "MAX_UPLOAD_MB", 0.001)  # 1 kB
    big = io.BytesIO(b"x" * 5000)
    res = client.post("/api/analyze", data={"model": "test-model"}, files={"file": ("big.csv", big, "text/csv")})
    assert res.status_code == 413


def test_public_mode_blocks_training(client, monkeypatch):
    monkeypatch.setattr(api_mod, "PUBLIC", True)
    assert client.post("/api/demo/build").status_code == 403
    assert client.get("/api/info").json()["public"] is True


def test_uploads_are_streamed_to_disk_and_cleaned_up(client, synthetic_dir, tmp_path, monkeypatch):
    import tempfile
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    path = sorted(synthetic_dir.glob("*.csv"))[0]
    with open(path, "rb") as fh:
        res = client.post("/api/analyze", data={"model": "test-model"}, files={"file": (path.name, fh, "text/csv")})
    assert res.status_code == 200 and res.json()["report"]["ok"]
    assert not list(tmp_path.glob("netforecast-*.csv"))  # temp copy removed after analysis
