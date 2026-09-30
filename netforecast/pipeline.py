"""End-to-end training, evaluation, bundle persistence and inference for the world model."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import torch
from sklearn.preprocessing import StandardScaler

from .models import (
    HorizonBaseline, WorldModel, WorldModelConfig, any_within, binary_metrics, simulate, train_world_model, tune_threshold,
)
from .schema import ValidationReport, load_flows
from .stages import STAGES
from .windows import (
    FEATURES, SequenceSet, add_capture_id, assign_splits, build_windows, make_sequences, missing_features,
)

SCORE_NOTE = (
    "Probabilities come from the world model's forward simulation and are not calibrated against real incident "
    "rates. Treat them as a ranking of risk, not as the chance of compromise."
)
N_SAMPLES = 32  # sampled rollouts per forecast at inference


@dataclass
class TrainConfig:
    window_seconds: int = 60
    seq_len: int = 10
    k: int = 10
    attack_fraction_threshold: float = 0.05
    test_captures: list[str] = field(default_factory=list)
    val_captures: list[str] = field(default_factory=list)
    seed: int = 42
    val_block_windows: int = 0
    wm: WorldModelConfig = field(default_factory=WorldModelConfig)


@dataclass
class Bundle:
    config: dict
    model: WorldModel
    baseline: HorizonBaseline
    scaler: StandardScaler

    @property
    def is_synthetic(self) -> bool:
        return self.config.get("data_kind") == "synthetic"


def expand_paths(paths: list[str | Path]) -> list[Path]:
    out: list[Path] = []
    for p in map(Path, paths):
        if p.is_dir():
            out.extend(sorted(q for q in p.iterdir() if q.suffix.lower() == ".csv"))
        elif p.exists():
            out.append(p)
        else:
            raise FileNotFoundError(p)
    if not out:
        raise FileNotFoundError("No CSV files found in: " + ", ".join(map(str, paths)))
    return out


def load_windows(paths: list[Path], window_seconds: int, attack_fraction_threshold: float, log=print):
    """Load each file, validate it and aggregate it to windows (flows are released per file)."""
    parts, reports, missing = [], [], set()
    for path in paths:
        flows, report = load_flows(path)
        reports.append(report)
        if not report.ok:
            raise ValueError(f"{path}: " + " ".join(report.errors))
        for w in report.warnings:
            log(f"  warning [{path.name}]: {w}")
        flows = add_capture_id(flows, path.name)
        missing |= set(missing_features(flows))
        parts.append(build_windows(flows, window_seconds, attack_fraction_threshold))
        log(f"  {path.name}: {report.n_rows_valid:,} flows -> {len(parts[-1]):,} windows")
        del flows
    return pd.concat(parts, ignore_index=True), reports, sorted(missing)


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------


def eval_steps(k: int) -> list[int]:
    return sorted({1, max(1, k // 2), k})


def _stage_metrics(seqs: SequenceSet, stage_prob: np.ndarray, seen: list[str]) -> dict:
    """stage_prob: (N, K, S) from simulate(); scored on future windows with a mapped attack stage."""
    mask = seqs.FST != -100
    if not mask.any():
        return {"n": 0, "note": "no mapped attack stages among test targets"}
    allowed = np.array([s in seen for s in STAGES])
    probs = np.where(allowed, stage_prob[mask], 0.0)
    pred = probs.argmax(axis=1)
    true = seqs.FST[mask]
    counts = {STAGES[i]: int((true == i).sum()) for i in np.unique(true)}
    return {
        "n": int(mask.sum()),
        "accuracy": round(float((pred == true).mean()), 4),
        "true_stage_counts": counts,
        "stages_unseen_in_training": [s for s in counts if s not in seen],
        "note": "Future windows that are attack windows with a mapped stage (all K steps).",
    }


def evaluate_sequences(bundle_like: dict, seqs: SequenceSet, wm_out: dict, lr_out: dict) -> dict:
    """Metrics for P(attack within K), selected single steps, and attack onsets."""
    th = bundle_like["thresholds"]
    k = seqs.FY.shape[1]
    y_any = any_within(seqs.FY)
    last = seqs.last_is_attack
    res: dict = {"targets": {}, "onset": {}}

    def block(y, wm_s, lr_s, wm_th, lr_th, persist):
        keep = ~np.isnan(y)
        if keep.sum() == 0:
            return None
        pk = keep & ~np.isnan(persist)
        return {
            "world_model": binary_metrics(y[keep], wm_s[keep], wm_th),
            "logistic_regression": binary_metrics(y[keep], lr_s[keep], lr_th),
            "persistence_reference": binary_metrics(y[pk], persist[pk], 0.5) if pk.any() else None,
        }

    res["targets"]["any"] = block(y_any, wm_out["any"], lr_out["any"], th["world_model"]["any"],
                                  th["logistic_regression"]["any"], last)
    for s in eval_steps(k):
        j = s - 1
        res["targets"][f"step_{s}"] = block(seqs.FY[:, j], wm_out["p"][:, j], lr_out["p"][:, j],
                                            th["world_model"]["steps"][j], th["logistic_regression"]["steps"][j], last)
    # Onset: the context ends in a benign window, so "keep doing what you are doing" predicts nothing.
    onset = last == 0
    if onset.any():
        y_on = np.where(onset, y_any, np.nan)
        b = block(y_on, wm_out["any"], lr_out["any"], th["world_model"]["any"], th["logistic_regression"]["any"], last)
        if b:
            b.pop("persistence_reference", None)
        res["onset"]["any"] = b
    return res


def _tune_all(seqs: SequenceSet, wm_out: dict, lr_out: dict) -> tuple[dict, str]:
    y_any = any_within(seqs.FY)
    keep = ~np.isnan(y_any)
    th_wm, src = tune_threshold(y_any[keep], wm_out["any"][keep])
    th_lr, _ = tune_threshold(y_any[keep], lr_out["any"][keep])
    steps_wm, steps_lr = [], []
    for j in range(seqs.FY.shape[1]):
        y = seqs.FY[:, j]
        m = ~np.isnan(y)
        steps_wm.append(tune_threshold(y[m], wm_out["p"][m, j])[0])
        steps_lr.append(tune_threshold(y[m], lr_out["p"][m, j])[0])
    return {"world_model": {"any": th_wm, "steps": steps_wm},
            "logistic_regression": {"any": th_lr, "steps": steps_lr}}, src


# ---------------------------------------------------------------------------
# Training
# ---------------------------------------------------------------------------


def train_pipeline(paths: list[str | Path], out_dir: str | Path, cfg: TrainConfig, log=print) -> dict:
    """Train the world model + baseline on labeled CSVs, evaluate on the held-out split and save a bundle."""
    files = expand_paths(paths)
    out_dir = Path(out_dir)
    log(f"Loading {len(files)} file(s)")
    windows, reports, missing = load_windows(files, cfg.window_seconds, cfg.attack_fraction_threshold, log)
    if not all(r.has_labels for r in reports):
        raise ValueError("Training needs a Label column in every file: " +
                         ", ".join(r.source for r in reports if not r.has_labels))
    data_kind = "synthetic" if any(r.data_kind == "synthetic" for r in reports) else "external"

    windows, split = assign_splits(windows, cfg.test_captures, cfg.val_captures, seed=cfg.seed,
                                   val_block_windows=cfg.val_block_windows)
    log(f"Split ({split.method}): train={len(split.train)} val={len(split.val)} test={len(split.test)} capture(s)")

    scaler = StandardScaler().fit(windows.loc[windows["split"] == "train", FEATURES].to_numpy())
    Z = scaler.transform(windows[FEATURES].to_numpy()).astype("float32")
    Z = np.clip(Z, -10, 10)
    seqs = {}
    for name in ("train", "val", "test", "test_hours"):
        if name == "test_hours" and not (windows["split"] == name).any():
            continue
        mask = (windows["split"] == name).to_numpy()
        seqs[name] = make_sequences(windows.loc[mask], Z[mask], cfg.seq_len, cfg.k, cfg.window_seconds)
        s = seqs[name]
        log(f"  {name}: {len(s):,} sequences, {int(np.nansum(any_within(s.FY))):,} with an attack within {cfg.k} windows")
    tr, va, te = seqs["train"], seqs["val"], seqs["test"]
    if len(tr) == 0 or np.nansum(tr.FY == 1) == 0 or np.nansum(tr.FY == 0) == 0:
        raise ValueError("Training split needs both attack and benign future windows; adjust the split or data.")
    if len(te) == 0:
        raise ValueError("Test split has no sequences; captures may be shorter than seq_len + k windows.")

    log("Training world model")
    cfg.wm.seed = cfg.seed
    model, history = train_world_model(tr.arrays(), va.arrays() if len(va) else None, cfg.wm, log)
    log("Training logistic-regression baselines (one per step + 'any within K')")
    baseline = HorizonBaseline(cfg.seed).fit(tr.X, tr.FY)

    tune_set = va if len(va) else tr
    thresholds, th_src = _tune_all(tune_set, simulate(model, tune_set.X, cfg.k), baseline.predict(tune_set.X))
    if not len(va):
        th_src += " (no validation split: tuned on training data)"

    wm_test = simulate(model, te.X, cfg.k, n_samples=N_SAMPLES, seed=cfg.seed)
    lr_test = baseline.predict(te.X)
    seen = sorted({STAGES[i] for i in tr.FST[tr.FST != -100].tolist()}, key=STAGES.index)
    config = {
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "model_type": "world_model_v1",
        "data_kind": data_kind,
        "training_files": [str(f) for f in files],
        "window_seconds": cfg.window_seconds,
        "seq_len": cfg.seq_len,
        "k": cfg.k,
        "attack_fraction_threshold": cfg.attack_fraction_threshold,
        "target": (
            f"for each of the next {cfg.k} windows ({cfg.window_seconds}s each): is it an attack window "
            f"(>= {cfg.attack_fraction_threshold:.0%} malicious flows)? Headline: P(any attack window within {cfg.k})"
        ),
        "features": FEATURES,
        "features_missing_in_training": missing,
        "stages": STAGES,
        "stages_seen_in_training": seen,
        "thresholds": thresholds,
        "threshold_source": th_src,
        "split": split.as_dict(),
        "world_model": asdict(cfg.wm),
        "history": history,
    }
    metrics = {
        "data_kind": data_kind,
        "evaluated_on": "held-out test split",
        "k": cfg.k,
        **evaluate_sequences(config, te, wm_test, lr_test),
        "stage_head": _stage_metrics(te, wm_test["stage"], seen),
        **({"test_hours": {
            "evaluated_on": "unseen hours (held-out time blocks) of the training days",
            "n": len(seqs["test_hours"]),
            **evaluate_sequences(config, seqs["test_hours"], simulate(model, seqs["test_hours"].X, cfg.k, n_samples=N_SAMPLES,
                                                                        seed=cfg.seed), baseline.predict(seqs["test_hours"].X)),
        }} if "test_hours" in seqs and len(seqs["test_hours"]) else {}),
        "split": split.as_dict(),
        "sequence_counts": {k: {"n": len(v), "with_attack_within_k": int(np.nansum(any_within(v.FY)))} for k, v in seqs.items()},
        "state_model": {"val_state_nll": history[-1].get("val_state_nll") if history else None},
    }
    save_bundle(out_dir, config, model, baseline, scaler, metrics)
    log(f"Saved model bundle to {out_dir}")
    return metrics


def save_bundle(out_dir: Path, config: dict, model, baseline, scaler, metrics: dict) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    torch.save(model.state_dict(), out_dir / "world_model.pt")
    joblib.dump(baseline, out_dir / "baseline.joblib")
    joblib.dump(scaler, out_dir / "scaler.joblib")
    (out_dir / "config.json").write_text(json.dumps(config, indent=2, default=str))
    for stale in ("lstm.pt",):
        (out_dir / stale).unlink(missing_ok=True)
    write_metrics(out_dir, metrics, config)


def write_metrics(out_dir: Path, metrics: dict, config: dict, stem: str = "metrics") -> None:
    (out_dir / f"{stem}.json").write_text(json.dumps(metrics, indent=2, default=str))
    (out_dir / f"{stem}.md").write_text(metrics_markdown(metrics, config))


def metrics_markdown(metrics: dict, config: dict) -> str:
    kind = metrics.get("data_kind", config.get("data_kind"))
    k = config["k"]
    banner = (
        "> **SYNTHETIC SMOKE-TEST DATA.** These numbers only show that the pipeline runs end to end. "
        "They say nothing about performance on real traffic."
        if kind == "synthetic"
        else "> Data: CIC-IDS-2018 CSV files listed in config.json."
    )
    lines = [
        "# World-model forecast evaluation", "", banner, "",
        f"- Evaluated on: {metrics.get('evaluated_on')}",
        f"- Context: {config['seq_len']} windows × {config['window_seconds']}s; forecast: next {k} windows",
        f"- Split method: {metrics.get('split', config['split'])['method']}",
        f"- Thresholds: {config.get('threshold_source')}",
        "",
    ]
    names = {"world_model": "World model (LSTM dynamics + rollout)", "logistic_regression": "Logistic regression (baseline)",
             "persistence_reference": "Persistence reference*"}
    sections = [("any", f"Attack within the next {k} windows")]
    sections += [(f"step_{s}", f"Attack in window t+{s}") for s in eval_steps(k)]
    for key, title in sections:
        block = metrics["targets"].get(key)
        if not block:
            continue
        lines += [f"## {title}", "", "| Model | Precision | Recall | F1 | FPR | AP |", "|---|---|---|---|---|---|"]
        for mk, label in names.items():
            m = block.get(mk)
            if m:
                lines.append(f"| {label} | {m['precision']:.3f} | {m['recall']:.3f} | {m['f1']:.3f} | "
                             f"{m['false_positive_rate']:.3f} | {m['average_precision'] if m['average_precision'] is not None else '–'} |")
        lines.append("")
    onset = metrics.get("onset", {}).get("any")
    if onset:
        lines += [f"## Early warning: attack within {k} windows when the latest window is still benign", "",
                  "| Model | Precision | Recall | F1 | FPR |", "|---|---|---|---|---|"]
        for mk in ("world_model", "logistic_regression"):
            m = onset[mk]
            lines.append(f"| {names[mk]} | {m['precision']:.3f} | {m['recall']:.3f} | {m['f1']:.3f} | {m['false_positive_rate']:.3f} |")
        lines.append("")
    hours = metrics.get("test_hours")
    if hours and hours["targets"].get("any"):
        lines += [f"## Test B: unseen hours of the training days (attack within {k} windows)", "",
                  "| Model | Precision | Recall | F1 | FPR | AP |", "|---|---|---|---|---|---|"]
        for mk, label in names.items():
            m = hours["targets"]["any"].get(mk)
            if m:
                lines.append(f"| {label} | {m['precision']:.3f} | {m['recall']:.3f} | {m['f1']:.3f} | "
                             f"{m['false_positive_rate']:.3f} | {m['average_precision'] if m['average_precision'] is not None else '–'} |")
        lines.append("")
    lines += [
        "\\* Persistence predicts that the future looks like the latest window. It needs ground-truth labels, "
        "so it is a reference point, not a deployable model.",
    ]
    stage = metrics.get("stage_head")
    if stage:
        lines += ["", f"Stage head: {json.dumps(stage)}"]
    split = metrics.get("split")
    if split:
        lines += ["", "Split:", f"- train: {', '.join(split['train'])}", f"- val: {', '.join(split['val']) or '(none)'}",
                  f"- test: {', '.join(split['test'])}"]
        if split.get("note"):
            lines.append(f"- note: {split['note']}")
    return "\n".join(lines) + "\n"


def load_bundle(model_dir: str | Path) -> Bundle:
    model_dir = Path(model_dir)
    config = json.loads((model_dir / "config.json").read_text())
    if config.get("model_type") != "world_model_v1":
        raise ValueError(f"{model_dir} holds an older model format; retrain it with `python -m netforecast.cli train`.")
    wm = config["world_model"]
    model = WorldModel(len(config["features"]), wm["hidden"], wm["layers"], wm["dropout"])
    model.load_state_dict(torch.load(model_dir / "world_model.pt", map_location="cpu", weights_only=True))
    model.eval()
    return Bundle(config, model, joblib.load(model_dir / "baseline.joblib"), joblib.load(model_dir / "scaler.joblib"))


# ---------------------------------------------------------------------------
# Inference on uploaded data
# ---------------------------------------------------------------------------


@dataclass
class Analysis:
    windows: pd.DataFrame
    forecasts: pd.DataFrame
    steps: dict  # per-forecast K-step arrays: wm_p, wm_q10, wm_q90, lr_p, actual
    sequences: SequenceSet
    flows: pd.DataFrame  # compact flow table for evidence ("flagged flows")
    missing_features: list[str]
    has_labels: bool
    metrics: dict | None


def _scale(bundle: Bundle, windows: pd.DataFrame) -> np.ndarray:
    return np.clip(bundle.scaler.transform(windows[FEATURES].to_numpy()).astype("float32"), -10, 10)


FLOW_COLUMNS = ["capture_id", "Timestamp", "Dst Port", "Protocol", "Tot Fwd Pkts", "Tot Bwd Pkts",
                "TotLen Fwd Pkts", "SYN Flag Cnt", "RST Flag Cnt", "Label"]


def analyze(flows: pd.DataFrame, source_name: str, bundle: Bundle) -> Analysis:
    """Window the flows, run K-step forward simulation for every position, attach stages and labels."""
    cfg = bundle.config
    k = cfg["k"]
    flows = add_capture_id(flows, source_name)
    windows = build_windows(flows, cfg["window_seconds"], cfg["attack_fraction_threshold"])
    Z = _scale(bundle, windows)
    seqs = make_sequences(windows, Z, cfg["seq_len"], k, cfg["window_seconds"], include_future=True)
    if len(seqs) == 0:
        need = cfg["seq_len"] * cfg["window_seconds"]
        raise ValueError(
            f"Not enough data: each capture needs at least {cfg['seq_len']} windows "
            f"({need // 60} min at {cfg['window_seconds']}s windows)."
        )
    wm = simulate(bundle.model, seqs.X, k, n_samples=N_SAMPLES)
    lr = bundle.baseline.predict(seqs.X)
    th = cfg["thresholds"]
    step_th = np.array(th["world_model"]["steps"])

    seen = np.array([s in cfg.get("stages_seen_in_training", []) for s in STAGES])
    # Stage: the stage head at the future step the model thinks is most likely to be an attack.
    peak_step = wm["p"].argmax(axis=1)
    stage_at_peak = wm["stage"][np.arange(len(peak_step)), peak_step]
    masked = np.where(seen, stage_at_peak, 0.0)
    masked = masked / np.clip(masked.sum(axis=1, keepdims=True), 1e-9, None)
    best = masked.argmax(axis=1)
    best_p = masked[np.arange(len(best)), best]
    over = wm["p"] >= step_th[None, :]
    first_over = np.where(over.any(axis=1), over.argmax(axis=1) + 1, 0)

    fc = seqs.meta.copy()
    fc["wm_any"] = wm["any"]
    fc["lr_any"] = lr["any"]
    fc["wm_alert"] = wm["any"] >= th["world_model"]["any"]
    fc["lr_alert"] = lr["any"] >= th["logistic_regression"]["any"]
    fc["peak_step"] = peak_step + 1
    fc["peak_p"] = wm["p"].max(axis=1)
    fc["first_step_over_threshold"] = first_over
    fc["stage_prob"] = best_p if seen.any() else 0.0
    fc["predicted_stage"] = [
        STAGES[b] if (seen.any() and alert and p >= 0.5) else None
        for b, alert, p in zip(best, fc["wm_alert"], best_p)
    ]
    y_any = any_within(seqs.FY)
    first_attack = np.where((seqs.FY == 1).any(axis=1), (seqs.FY == 1).argmax(axis=1) + 1, 0)
    fc["actual_any"] = y_any
    fc["actual_first_attack_step"] = first_attack
    fc["actual_stage"] = [
        STAGES[fst[s - 1]] if s and fst[s - 1] != -100 else None for fst, s in zip(seqs.FST, first_attack)
    ]
    fc["now_is_attack"] = seqs.last_is_attack

    has_labels = bool(flows["is_attack"].notna().any())
    metrics = None
    if has_labels and (~np.isnan(y_any)).any():
        metrics = {"evaluated_on": "uploaded file (not held out unless you know it was excluded from training)",
                   "k": k, **evaluate_sequences(cfg, seqs, wm, lr)}
    keep_cols = [c for c in FLOW_COLUMNS if c in flows.columns]
    compact = flows[keep_cols].copy()
    compact["window_start"] = compact["Timestamp"].dt.floor(f"{cfg['window_seconds']}s")
    return Analysis(
        windows=windows,
        forecasts=fc,
        steps={"wm_p": wm["p"], "wm_q10": wm["q10"], "wm_q90": wm["q90"], "lr_p": lr["p"], "actual": seqs.FY},
        sequences=seqs,
        flows=compact,
        missing_features=missing_features(flows),
        has_labels=has_labels,
        metrics=metrics,
    )


def flow_evidence(analysis: Analysis, row: int, window_seconds: int, recent: int = 3, top: int = 8) -> list[dict]:
    """Flow groups (destination port + protocol) whose rate grew most in the latest context windows."""
    fc = analysis.forecasts.iloc[row]
    f = analysis.flows
    f = f[(f["capture_id"] == fc["capture_id"]) & (f["window_start"] >= fc["input_start"]) & (f["window_start"] <= fc["input_end"])]
    if f.empty:
        return []
    cut = fc["input_end"] - (recent - 1) * pd.Timedelta(seconds=window_seconds)
    n_ctx = int(analysis.sequences.X.shape[1])
    recent_mask = f["window_start"] >= cut
    agg = {"flows": ("Dst Port", "size")}
    if "SYN Flag Cnt" in f:
        agg["syn_share"] = ("SYN Flag Cnt", lambda s: float((s > 0).mean()))
    if "RST Flag Cnt" in f:
        agg["rst_share"] = ("RST Flag Cnt", lambda s: float((s > 0).mean()))
    agg["no_reply_share"] = ("Tot Bwd Pkts", lambda s: float((s <= 0).mean()))
    groups = f.groupby(["Dst Port", "Protocol"])
    stats = groups.agg(**agg)
    rec = f[recent_mask].groupby(["Dst Port", "Protocol"]).size().rename("recent")
    stats = stats.join(rec).fillna({"recent": 0})
    older_windows = max(n_ctx - recent, 1)
    stats["rate_recent"] = stats["recent"] / recent
    stats["rate_before"] = (stats["flows"] - stats["recent"]) / older_windows
    stats["growth"] = stats["rate_recent"] - stats["rate_before"]
    if "Label" in f:
        stats["labels"] = groups["Label"].agg(lambda s: ", ".join(f"{k} ({v})" for k, v in s.value_counts().head(2).items()))
    stats = stats.sort_values(["growth", "flows"], ascending=False).head(top).reset_index()
    stats["Dst Port"] = stats["Dst Port"].astype(int)
    stats["Protocol"] = stats["Protocol"].astype(int).map({6: "TCP", 17: "UDP", 0: "HOPOPT"}).fillna(stats["Protocol"].astype(str))
    return json.loads(stats.to_json(orient="records"))


def evaluate_files(model_dir: str | Path, paths: list[str | Path], log=print) -> dict:
    """Evaluate a saved bundle on labeled CSVs treated entirely as test data."""
    bundle = load_bundle(model_dir)
    cfg = bundle.config
    files = expand_paths(paths)
    overlap = sorted({str(f.resolve()) for f in files} & {str(Path(f).resolve()) for f in cfg["training_files"]})
    windows, reports, _ = load_windows(files, cfg["window_seconds"], cfg["attack_fraction_threshold"], log)
    if not all(r.has_labels for r in reports):
        raise ValueError("Evaluation needs labeled files.")
    seqs = make_sequences(windows, _scale(bundle, windows), cfg["seq_len"], cfg["k"], cfg["window_seconds"])
    if len(seqs) == 0:
        raise ValueError("No complete sequences in the evaluation files.")
    wm = simulate(bundle.model, seqs.X, cfg["k"], n_samples=N_SAMPLES)
    lr = bundle.baseline.predict(seqs.X)
    metrics = {
        "data_kind": "synthetic" if any(r.data_kind == "synthetic" for r in reports) else "external",
        "evaluated_on": "files: " + ", ".join(f.name for f in files),
        "k": cfg["k"],
        "note": "WARNING: some evaluation files were also used for training." if overlap else "",
        **evaluate_sequences(cfg, seqs, wm, lr),
    }
    write_metrics(Path(model_dir), metrics, cfg, stem="eval_metrics")
    return metrics


def validation_summary(report: ValidationReport) -> dict:
    return {
        "source": report.source,
        "rows read": report.n_rows_read,
        "valid rows": report.n_rows_valid,
        "time range": f"{report.time_start} → {report.time_end}" if report.time_start is not None else "–",
        "labels present": report.has_labels,
        "data kind": report.data_kind,
    }
