"""Local HTTP API for the React dashboard.

    uvicorn netforecast.api:app --port 8000

Serves /api/* and, when frontend/dist exists, the built dashboard at /.
Binds to localhost by default; nothing leaves the machine.

Environment:
    NETFORECAST_PUBLIC=1        public deployment: disables retraining from the web UI
    NETFORECAST_MAX_UPLOAD_MB   largest accepted upload (default 300)
"""

from __future__ import annotations

import io
import json
import os
import threading
import uuid
from collections import OrderedDict
from pathlib import Path

import numpy as np
import pandas as pd
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .explain import FEATURE_DESCRIPTIONS, explain_forecast, summarize
from .pipeline import SCORE_NOTE, Analysis, TrainConfig, analyze, flow_evidence, load_bundle, train_pipeline
from .schema import OPTIONAL_COLUMNS, REQUIRED_COLUMNS, ValidationReport, load_flows
from .stages import mapping_table
from .windows import FEATURES

ROOT = Path(__file__).resolve().parent.parent
ARTIFACTS = ROOT / "artifacts"
DATA = ROOT / "data"
SAMPLE_DIRS = {"synthetic": DATA / "synthetic", "cic2018": DATA / "cic2018"}
DEMO_MODEL = "synthetic-demo"
DIST = ROOT / "frontend" / "dist"
MAX_CACHED_ANALYSES = 3
PUBLIC = os.environ.get("NETFORECAST_PUBLIC", "").lower() in ("1", "true", "yes")
MAX_UPLOAD_MB = float(os.environ.get("NETFORECAST_MAX_UPLOAD_MB", "300"))

app = FastAPI(title="Network Attack Forecaster API", docs_url="/api/docs", openapi_url="/api/openapi.json")

_bundles: dict[str, tuple[float, object]] = {}
_analyses: OrderedDict[str, tuple[str, Analysis]] = OrderedDict()
_lock = threading.Lock()


def _json(obj) -> JSONResponse:
    return JSONResponse(json.loads(json.dumps(obj, default=_default)))


def _default(o):
    if isinstance(o, pd.Timestamp):
        return o.isoformat()
    if isinstance(o, np.ndarray):
        return [None if (isinstance(v, float) and np.isnan(v)) else v for v in o.tolist()]
    if isinstance(o, np.generic):
        v = o.item()
        return None if isinstance(v, float) and np.isnan(v) else v
    return str(o)


def _records(df: pd.DataFrame) -> list[dict]:
    """DataFrame -> JSON records (ISO timestamps, NaN -> null, numpy -> Python)."""
    return json.loads(df.to_json(orient="records", date_format="iso"))


def _nan_list(a: np.ndarray) -> list:
    return [None if np.isnan(v) else round(float(v), 4) for v in a]


def _model_dir(name: str) -> Path:
    path = (ARTIFACTS / name).resolve()
    if path.parent != ARTIFACTS.resolve() or not (path / "config.json").exists():
        raise HTTPException(404, f"Model {name!r} not found in artifacts/.")
    return path


def _bundle(name: str):
    path = _model_dir(name)
    weights = path / "world_model.pt"
    if not weights.exists():
        raise HTTPException(409, f"Model {name!r} uses an older format; retrain it.")
    mtime = weights.stat().st_mtime
    with _lock:
        cached = _bundles.get(name)
        if cached and cached[0] == mtime:
            return cached[1]
        bundle = load_bundle(path)
        _bundles[name] = (mtime, bundle)
        return bundle


def _report_dict(report: ValidationReport) -> dict:
    return {
        "source": report.source,
        "ok": report.ok,
        "errors": report.errors,
        "warnings": report.warnings,
        "n_rows_read": report.n_rows_read,
        "n_rows_valid": report.n_rows_valid,
        "columns_found": report.columns_found,
        "optional_missing": report.optional_missing,
        "has_labels": report.has_labels,
        "data_kind": report.data_kind,
        "time_start": report.time_start.isoformat() if report.time_start is not None else None,
        "time_end": report.time_end.isoformat() if report.time_end is not None else None,
        "label_counts": report.label_counts,
    }


def _sample_path(sample_id: str) -> Path:
    kind, _, name = sample_id.partition("/")
    base = SAMPLE_DIRS.get(kind)
    if base is None:
        raise HTTPException(404, f"Unknown sample {sample_id!r}.")
    path = (base / name).resolve()
    if path.parent != base.resolve() or path.suffix.lower() != ".csv" or not path.exists():
        raise HTTPException(404, f"Sample {sample_id!r} not found.")
    return path


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


def _read_upload(file: UploadFile) -> bytes:
    """Read an upload in chunks, refusing it once it passes the size limit."""
    limit = int(MAX_UPLOAD_MB * 1e6)
    buf = io.BytesIO()
    while chunk := file.file.read(1 << 20):
        buf.write(chunk)
        if buf.tell() > limit:
            raise HTTPException(413, f"File is larger than {MAX_UPLOAD_MB:.0f} MB. Use the command line for big captures.")
    return buf.getvalue()


@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/info")
def info():
    return _json({
        "public": PUBLIC,
        "max_upload_mb": MAX_UPLOAD_MB,
        "required_columns": REQUIRED_COLUMNS,
        "optional_columns": OPTIONAL_COLUMNS,
        "stage_mapping": mapping_table(),
        "score_note": SCORE_NOTE,
        "demo_model": DEMO_MODEL,
        "n_features": len(FEATURES),
        "feature_descriptions": FEATURE_DESCRIPTIONS,
    })


@app.get("/api/models")
def models():
    out = []
    if ARTIFACTS.exists():
        for path in sorted(p for p in ARTIFACTS.iterdir() if (p / "config.json").exists()):
            cfg = json.loads((path / "config.json").read_text())
            if cfg.get("model_type") != "world_model_v1":
                continue
            metrics_path = path / "metrics.json"
            out.append({
                "name": path.name,
                **{k: cfg[k] for k in ("data_kind", "created_at", "window_seconds", "seq_len", "k",
                                       "attack_fraction_threshold", "target", "thresholds", "threshold_source", "split")},
                "stages_seen_in_training": cfg.get("stages_seen_in_training", []),
                "training_files": [Path(f).name for f in cfg.get("training_files", [])],
                "metrics": json.loads(metrics_path.read_text()) if metrics_path.exists() else None,
            })
    return _json(out)


@app.get("/api/samples")
def samples():
    """Local CSVs the dashboard can analyse without uploading them through the browser."""
    out = []
    for kind, base in SAMPLE_DIRS.items():
        for p in sorted(base.glob("*.csv")) if base.exists() else []:
            out.append({"id": f"{kind}/{p.name}", "name": p.name, "stem": p.stem,
                        "kind": "synthetic" if kind == "synthetic" else "real",
                        "size_mb": round(p.stat().st_size / 1e6, 1)})
    return _json(out)


@app.post("/api/demo/build")
def build_demo():
    """Generate synthetic CSVs (if missing) and train the demo model. Synthetic data only."""
    from .synthetic import write_synthetic

    if PUBLIC:
        raise HTTPException(403, "Training is disabled on the public deployment.")
    synth = SAMPLE_DIRS["synthetic"]
    with _lock:
        if not any(synth.glob("*.csv")):
            write_synthetic(synth)
        train_pipeline([synth], ARTIFACTS / DEMO_MODEL, TrainConfig(), log=lambda *_: None)
        _bundles.pop(DEMO_MODEL, None)
    return {"ok": True, "model": DEMO_MODEL}


@app.post("/api/analyze")
def analyze_endpoint(
    model: str = Form(...),
    file: UploadFile | None = File(None),
    sample: str | None = Form(None),
):
    bundle = _bundle(model)
    if file is not None:
        name, source = file.filename or "upload.csv", io.BytesIO(_read_upload(file))
    elif sample:
        path = _sample_path(sample)
        name, source = path.name, path
    else:
        raise HTTPException(400, "Send a CSV file or choose a sample.")

    flows, report = load_flows(source, name=name)
    rep = _report_dict(report)
    if not report.ok:
        return JSONResponse({"report": rep}, status_code=422)
    try:
        result = analyze(flows, name, bundle)
    except ValueError as exc:
        rep["errors"].append(str(exc))
        rep["ok"] = False
        return JSONResponse({"report": rep}, status_code=422)
    del flows

    analysis_id = uuid.uuid4().hex[:12]
    with _lock:
        _analyses[analysis_id] = (model, result)
        while len(_analyses) > MAX_CACHED_ANALYSES:
            _analyses.popitem(last=False)

    fc = result.forecasts.copy()
    fc.insert(0, "row", np.arange(len(fc)))
    windows = result.windows[["capture_id", "window_start", "n_flows", "is_attack", "stage", "top_label"]]
    return _json({
        "id": analysis_id,
        "model": model,
        "report": rep,
        "missing_features": result.missing_features,
        "has_labels": result.has_labels,
        "n_flows": int(len(result.flows)),
        "forecasts": _records(fc),
        "windows": _records(windows),
        "metrics": result.metrics,
    })


@app.get("/api/forecast/{analysis_id}/{row}")
def forecast_detail(analysis_id: str, row: int, top: int = 10):
    """Everything behind one forecast: the K-step simulation, Shapley attributions, timing and flows."""
    with _lock:
        entry = _analyses.get(analysis_id)
    if entry is None:
        raise HTTPException(404, "Analysis expired; run the forecast again.")
    model_name, result = entry
    bundle = _bundle(model_name)
    cfg = bundle.config
    if not 0 <= row < len(result.forecasts):
        raise HTTPException(404, "No such forecast row.")
    k = cfg["k"]
    x_seq = result.sequences.X[row]
    ex = explain_forecast(bundle.model, x_seq, cfg["features"], k)
    table = ex["table"]
    fc = result.forecasts.iloc[row]
    w = result.windows
    inp = w[(w["capture_id"] == fc["capture_id"]) & (w["window_start"] >= fc["input_start"])
            & (w["window_start"] <= fc["input_end"])].reset_index(drop=True)
    step = pd.Timedelta(seconds=cfg["window_seconds"])
    top_feats = list(table["feature"].head(3))
    return _json({
        "row": row,
        "rollout": {
            "times": [(fc["input_end"] + (j + 1) * step).isoformat() for j in range(k)],
            "world_model": _nan_list(result.steps["wm_p"][row]),
            "q10": _nan_list(result.steps["wm_q10"][row]),
            "q90": _nan_list(result.steps["wm_q90"][row]),
            "baseline": _nan_list(result.steps["lr_p"][row]),
            "actual": _nan_list(result.steps["actual"][row]),
            "step_thresholds": cfg["thresholds"]["world_model"]["steps"],
        },
        "shap": {
            "base_logodds": ex["base_logodds"],
            "pred_logodds": ex["pred_logodds"],
            "features": _records(table.head(top)),
            "groups": [{"group": g, "value": float(v)} for g, v in ex["groups"].items()],
        },
        "temporal": [
            {"window_start": t.isoformat(), "importance": float(v), "is_attack": None if pd.isna(a) else float(a),
             "n_flows": int(n)}
            for t, v, a, n in zip(inp["window_start"], ex["temporal"], inp["is_attack"], inp["n_flows"])
        ],
        "summary": summarize(table),
        "evidence": [
            {"feature": f, "description": FEATURE_DESCRIPTIONS.get(f, f),
             "points": _records(inp[["window_start", f]].rename(columns={f: "value"}))}
            for f in top_feats
        ],
        "flows": flow_evidence(result, row, cfg["window_seconds"]),
        "labels_in_input": inp["top_label"].dropna().value_counts().to_dict(),
    })


if DIST.exists():
    app.mount("/", StaticFiles(directory=DIST, html=True), name="dashboard")
