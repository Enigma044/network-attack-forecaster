"""Command line: make-synthetic, train, evaluate, analyze.

    python -m netforecast.cli make-synthetic --out data/synthetic
    python -m netforecast.cli train --data data/synthetic --out artifacts/synthetic-demo
    python -m netforecast.cli evaluate --model artifacts/synthetic-demo --data data/synthetic/synthetic_2026-01-14.csv
    python -m netforecast.cli analyze --model artifacts/synthetic-demo --data some.csv --out forecasts.csv
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .models import WorldModelConfig


def _print_metrics(metrics: dict) -> None:
    if metrics.get("data_kind") == "synthetic":
        print("\n*** SYNTHETIC DATA: smoke-test numbers only, not a benchmark ***")
    print(f"Evaluated on: {metrics['evaluated_on']}")
    blocks = [(f"attack within next {metrics['k']} windows", metrics["targets"].get("any"))]
    blocks += [(f"attack in window t+{k.split('_')[1]}", v) for k, v in metrics["targets"].items() if k != "any"]
    if metrics.get("onset", {}).get("any"):
        blocks.append(("early warning (latest window benign)", metrics["onset"]["any"]))
    if metrics.get("test_hours", {}).get("targets", {}).get("any"):
        blocks.append((f"TEST B - unseen hours of training days: attack within next {metrics['k']} windows",
                       metrics["test_hours"]["targets"]["any"]))
    for title, block in blocks:
        if not block:
            continue
        print(f"\n{title}")
        print(f"  {'model':24s} {'prec':>6s} {'recall':>6s} {'f1':>6s} {'fpr':>6s}")
        for key in ("world_model", "logistic_regression", "persistence_reference"):
            m = block.get(key)
            if m:
                print(f"  {key:24s} {m['precision']:6.3f} {m['recall']:6.3f} {m['f1']:6.3f} {m['false_positive_rate']:6.3f}")
    if metrics.get("note"):
        print(metrics["note"])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="netforecast", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("make-synthetic", help="write synthetic CIC-IDS-2018-format CSVs (smoke tests / demo only)")
    p.add_argument("--out", default="data/synthetic")
    p.add_argument("--days", type=int, default=10)
    p.add_argument("--hours", type=float, default=4.0)
    p.add_argument("--seed", type=int, default=0)

    p = sub.add_parser("train", help="train the world model + logistic-regression baselines and evaluate on a held-out capture split")
    p.add_argument("--data", nargs="+", required=True, help="CSV files and/or directories of CSVs")
    p.add_argument("--out", required=True, help="output model directory, e.g. artifacts/cic2018")
    p.add_argument("--window", type=int, default=60, help="window size in seconds (default 60)")
    p.add_argument("--seq-len", type=int, default=10, help="input windows per sequence (default 10)")
    p.add_argument("--k", type=int, default=10, help="windows to forward-simulate (default 10)")
    p.add_argument("--attack-threshold", type=float, default=0.05,
                   help="min fraction of malicious flows for an attack window (default 0.05)")
    p.add_argument("--test-captures", nargs="*", default=[], help="capture ids / file stems for the test split")
    p.add_argument("--val-captures", nargs="*", default=[], help="capture ids / file stems for the validation split")
    p.add_argument("--val-blocks", type=int, default=0,
                   help="with no --val-captures: take every 5th block of this many windows from the training "
                        "captures as validation (e.g. 120)")
    p.add_argument("--epochs", type=int, default=40)
    p.add_argument("--hidden", type=int, default=64)
    p.add_argument("--seed", type=int, default=42)

    p = sub.add_parser("evaluate", help="evaluate a saved model on labeled CSVs")
    p.add_argument("--model", required=True)
    p.add_argument("--data", nargs="+", required=True)

    p = sub.add_parser("analyze", help="write per-window forecasts for one CSV")
    p.add_argument("--model", required=True)
    p.add_argument("--data", required=True)
    p.add_argument("--out", default="forecasts.csv")

    args = parser.parse_args(argv)
    try:
        if args.cmd == "make-synthetic":
            from .synthetic import write_synthetic

            for path in write_synthetic(args.out, args.days, args.hours, args.seed):
                print(path)
            print("Synthetic data written. It is for smoke tests and demo mode only.")
        elif args.cmd == "train":
            from .pipeline import TrainConfig, train_pipeline

            cfg = TrainConfig(
                window_seconds=args.window, seq_len=args.seq_len, k=args.k,
                attack_fraction_threshold=args.attack_threshold, test_captures=args.test_captures,
                val_captures=args.val_captures, seed=args.seed, val_block_windows=args.val_blocks,
                wm=WorldModelConfig(epochs=args.epochs, hidden=args.hidden),
            )
            _print_metrics(train_pipeline(args.data, args.out, cfg))
            print(f"\nMetrics: {Path(args.out) / 'metrics.md'}")
        elif args.cmd == "evaluate":
            from .pipeline import evaluate_files

            _print_metrics(evaluate_files(args.model, args.data))
            print(f"\nMetrics: {Path(args.model) / 'eval_metrics.md'}")
        elif args.cmd == "analyze":
            from .pipeline import analyze, load_bundle
            from .schema import load_flows

            flows, report = load_flows(args.data)
            if not report.ok:
                print("Invalid input: " + " ".join(report.errors), file=sys.stderr)
                return 2
            bundle = load_bundle(args.model)
            result = analyze(flows, Path(args.data).name, bundle)
            result.forecasts.to_csv(args.out, index=False)
            print(f"Wrote {len(result.forecasts)} forecasts to {args.out}")
            if result.metrics:
                print(json.dumps({k: v for k, v in result.metrics.items() if k != "evaluated_on"}, indent=2))
    except (ValueError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
