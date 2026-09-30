"""Synthetic CIC-IDS-2018-format flows for smoke tests and the labeled demo mode.

This is NOT a benchmark. Traffic statistics are invented to exercise the
pipeline: benign background plus scripted campaigns (sparse port scan ->
SSH/FTP brute force -> botnet C2 beacons, occasionally followed by internal
scanning), unrelated DoS bursts, isolated scans with no follow-up and benign
backup bursts as distractors. Every row carries ``Synthetic = 1`` so the loader
marks the data as synthetic everywhere downstream.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

COLUMNS = [
    "Src IP", "Dst IP", "Dst Port", "Protocol", "Timestamp", "Flow Duration", "Tot Fwd Pkts", "Tot Bwd Pkts",
    "TotLen Fwd Pkts", "TotLen Bwd Pkts", "Flow IAT Mean", "FIN Flag Cnt", "SYN Flag Cnt", "RST Flag Cnt",
    "PSH Flag Cnt", "ACK Flag Cnt", "URG Flag Cnt", "Label", "Synthetic",
]

INTERNAL = [f"172.31.64.{i}" for i in range(10, 60)]
EXTERNAL = [f"203.0.113.{i}" for i in range(1, 120)] + [f"198.51.100.{i}" for i in range(1, 80)]
ATTACKER = "18.219.211.138"
C2_SERVER = "18.219.5.43"


def _times(rng, start: datetime, minutes: float, per_minute: float) -> np.ndarray:
    n = rng.poisson(max(per_minute * minutes, 0))
    offsets = np.sort(rng.uniform(0, minutes * 60, n))
    return np.datetime64(start) + (offsets * 1e6).astype("timedelta64[us]")


def _flows(rng, ts, src, dst, port, proto, dur_us, fwd, bwd, fwd_size, bwd_size, flags, label) -> pd.DataFrame:
    n = len(ts)
    fwd = np.maximum(np.asarray(fwd, dtype=int), 1)
    bwd = np.maximum(np.asarray(bwd, dtype=int), 0)
    dur = np.maximum(np.asarray(dur_us), 1).astype(np.int64)
    tcp = np.asarray(proto) == 6
    def flag(p):
        return (rng.random(n) < p).astype(int) * tcp
    return pd.DataFrame(
        {
            "Src IP": src, "Dst IP": dst, "Dst Port": port, "Protocol": proto, "Timestamp": ts,
            "Flow Duration": dur, "Tot Fwd Pkts": fwd, "Tot Bwd Pkts": bwd,
            "TotLen Fwd Pkts": (fwd * np.asarray(fwd_size)).astype(int),
            "TotLen Bwd Pkts": (bwd * np.asarray(bwd_size)).astype(int),
            "Flow IAT Mean": dur / np.maximum(fwd + bwd - 1, 1),
            "FIN Flag Cnt": flag(flags.get("fin", 0)), "SYN Flag Cnt": flag(flags.get("syn", 0)),
            "RST Flag Cnt": flag(flags.get("rst", 0)), "PSH Flag Cnt": flag(flags.get("psh", 0)),
            "ACK Flag Cnt": flag(flags.get("ack", 0)), "URG Flag Cnt": flag(flags.get("urg", 0)),
            "Label": label,
        }
    )


def benign(rng, start, minutes, rate=30.0) -> pd.DataFrame:
    ts = _times(rng, start, minutes, rate)
    n = len(ts)
    port = rng.choice([443, 80, 53, 22, 445, 8080, 3389, 0], n, p=[0.45, 0.18, 0.15, 0.02, 0.04, 0.03, 0.01, 0.12])
    high = port == 0
    port = np.where(high, rng.integers(1024, 65535, n), port)
    proto = np.where((port == 53) | (high & (rng.random(n) < 0.3)), 17, 6)
    return _flows(
        rng, ts, rng.choice(INTERNAL, n), rng.choice(EXTERNAL + INTERNAL[:10], n), port, proto,
        rng.lognormal(12, 2, n), rng.poisson(8, n) + 1, rng.poisson(7, n), rng.lognormal(5.5, 0.8, n),
        rng.lognormal(6.5, 1.0, n), {"fin": 0.7, "syn": 0.9, "rst": 0.05, "psh": 0.5, "ack": 0.95}, "Benign",
    )


def port_scan(rng, start, minutes, rate, src=ATTACKER, label="PortScan", internal=False) -> pd.DataFrame:
    ts = _times(rng, start, minutes, rate)
    n = len(ts)
    dst = rng.choice(INTERNAL, n)
    return _flows(
        rng, ts, rng.choice(INTERNAL, n) if internal else src, dst, rng.integers(1, 1024, n), np.full(n, 6),
        rng.lognormal(6, 1, n), np.ones(n), rng.integers(0, 2, n), np.full(n, 40), np.full(n, 40),
        {"syn": 1.0, "rst": 0.8}, label,
    )


def brute_force(rng, start, minutes, rate, port=22, label="SSH-Bruteforce") -> pd.DataFrame:
    ts = _times(rng, start, minutes, rate)
    n = len(ts)
    return _flows(
        rng, ts, ATTACKER, rng.choice(INTERNAL[:3], n), np.full(n, port), np.full(n, 6),
        rng.lognormal(13.5, 0.4, n), rng.poisson(18, n) + 5, rng.poisson(16, n) + 4,
        rng.lognormal(4.5, 0.3, n), rng.lognormal(4.8, 0.3, n), {"fin": 0.9, "syn": 1.0, "psh": 0.9, "ack": 1.0}, label,
    )


def bot_c2(rng, start, minutes, hosts: int) -> pd.DataFrame:
    parts = []
    for h in rng.choice(INTERNAL, hosts, replace=False):
        period = rng.uniform(8, 25)
        offsets = np.arange(0, minutes * 60, period) + rng.normal(0, 1.0, int(np.ceil(minutes * 60 / period)))
        ts = np.datetime64(start) + (np.clip(offsets, 0, None) * 1e6).astype("timedelta64[us]")
        n = len(ts)
        parts.append(_flows(
            rng, ts, h, C2_SERVER, np.full(n, 8080), np.full(n, 6), rng.lognormal(10, 0.3, n),
            np.full(n, 3), np.full(n, 2), rng.normal(120, 10, n), rng.normal(200, 20, n),
            {"fin": 1.0, "syn": 1.0, "psh": 1.0, "ack": 1.0}, "Bot",
        ))
    return pd.concat(parts, ignore_index=True)


def dos(rng, start, minutes, rate=400.0) -> pd.DataFrame:
    ts = _times(rng, start, minutes, rate)
    n = len(ts)
    return _flows(
        rng, ts, ATTACKER, INTERNAL[0], np.full(n, 80), np.full(n, 6), rng.lognormal(14, 0.5, n),
        rng.poisson(4, n) + 1, np.zeros(n), np.full(n, 300), np.zeros(n), {"syn": 1.0, "ack": 0.5, "psh": 0.8},
        "DoS attacks-Hulk",
    )


def backup_burst(rng, start, minutes) -> pd.DataFrame:
    ts = _times(rng, start, minutes, 25)
    n = len(ts)
    return _flows(
        rng, ts, INTERNAL[5], INTERNAL[6], np.full(n, 445), np.full(n, 6), rng.lognormal(15, 0.5, n),
        rng.poisson(400, n), rng.poisson(200, n), np.full(n, 1400), np.full(n, 60),
        {"fin": 0.9, "syn": 1.0, "psh": 0.9, "ack": 1.0}, "Benign",
    )


def generate_capture(day: datetime, seed: int, hours: float = 4.0) -> pd.DataFrame:
    """One synthetic 'day' of flows starting at ``day``."""
    rng = np.random.default_rng(seed)
    minutes = hours * 60
    parts = [benign(rng, day, minutes)]

    def at(m):
        return day + timedelta(minutes=float(m))

    n_campaigns = int(rng.integers(1, 3))
    slots = np.sort(rng.uniform(20, max(minutes - 150, 30), n_campaigns))
    for s in slots:
        recon_len = rng.uniform(10, 20)
        parts.append(port_scan(rng, at(s), recon_len, rate=rng.uniform(0.8, 2.5)))
        bf_start = s + recon_len + rng.uniform(0, 4)
        bf_len = rng.uniform(15, 30)
        port, label = (22, "SSH-Bruteforce") if rng.random() < 0.6 else (21, "FTP-BruteForce")
        parts.append(brute_force(rng, at(bf_start), bf_len, rng.uniform(40, 90), port, label))
        c2_start = bf_start + bf_len + rng.uniform(1, 5)
        c2_len = rng.uniform(25, 50)
        parts.append(bot_c2(rng, at(c2_start), c2_len, int(rng.integers(2, 5))))
        if rng.random() < 0.5:
            parts.append(port_scan(rng, at(c2_start + c2_len * 0.5), rng.uniform(10, 20), rng.uniform(15, 40),
                                   label="Infilteration", internal=True))
    if rng.random() < 0.4:
        parts.append(dos(rng, at(rng.uniform(10, minutes - 30)), rng.uniform(10, 20)))
    for _ in range(int(rng.integers(0, 3))):
        parts.append(port_scan(rng, at(rng.uniform(0, minutes - 15)), rng.uniform(3, 8), rng.uniform(0.5, 1.5)))
    if rng.random() < 0.7:
        parts.append(backup_burst(rng, at(rng.uniform(0, minutes - 20)), rng.uniform(8, 15)))

    df = pd.concat(parts, ignore_index=True)
    end = np.datetime64(day + timedelta(minutes=minutes))
    df = df[df["Timestamp"] < end].sort_values("Timestamp", kind="stable").reset_index(drop=True)
    df["Timestamp"] = pd.to_datetime(df["Timestamp"]).dt.strftime("%d/%m/%Y %H:%M:%S")
    df["Synthetic"] = 1
    return df[COLUMNS]


def write_synthetic(out_dir: str | Path, days: int = 10, hours: float = 4.0, seed: int = 0) -> list[Path]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for i in range(days):
        day = datetime(2026, 1, 5, 9, 0) + timedelta(days=i)
        path = out_dir / f"synthetic_{day:%Y-%m-%d}.csv"
        generate_capture(day, seed * 1000 + i, hours).to_csv(path, index=False)
        paths.append(path)
    return paths
