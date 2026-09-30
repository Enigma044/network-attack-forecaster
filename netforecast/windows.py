"""Aggregate flows into fixed time windows, split by capture, and build sequences.

A *capture* is one day of one source file (CIC-IDS-2018 ships one CSV per day).
Windows never span captures, and sequences are built inside a single capture
(or a single chronological block of it), so no training sequence can overlap
a test sequence.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .stages import STAGES, map_label, stage_index

PORT_GROUPS: dict[str, list[int]] = {
    "ftp": [20, 21],
    "ssh": [22],
    "web": [80, 443, 8080, 8443],
    "rdp": [3389],
    "smb": [139, 445],
    "dns": [53],
}

# Window-level features, in model input order. Raw IP addresses are never used
# as features; only counts of distinct addresses/pairs per window.
FEATURES: list[str] = [
    "log_n_flows",
    "frac_tcp",
    "frac_udp",
    "frac_other_proto",
    "dur_mean",
    "dur_std",
    "dur_max",
    "fwd_pkts_mean",
    "fwd_pkts_max",
    "bwd_pkts_mean",
    "bwd_pkts_max",
    "frac_no_bwd",
    "fwd_bytes_mean",
    "fwd_bytes_max",
    "bwd_bytes_mean",
    "iat_mean",
    "syn_rate",
    "rst_rate",
    "fin_rate",
    "psh_rate",
    "ack_rate",
    "urg_rate",
    "log_distinct_dst_ports",
    "distinct_dst_port_ratio",
    *[f"frac_port_{g}" for g in PORT_GROUPS],
    "frac_port_high",
    "log_distinct_src_ips",
    "log_distinct_dst_ips",
    "log_distinct_pairs",
]

# Source column each optional feature depends on (required columns are always present).
FEATURE_SOURCES: dict[str, str] = {
    "fwd_bytes_mean": "TotLen Fwd Pkts",
    "fwd_bytes_max": "TotLen Fwd Pkts",
    "bwd_bytes_mean": "TotLen Bwd Pkts",
    "iat_mean": "Flow IAT Mean",
    "syn_rate": "SYN Flag Cnt",
    "rst_rate": "RST Flag Cnt",
    "fin_rate": "FIN Flag Cnt",
    "psh_rate": "PSH Flag Cnt",
    "ack_rate": "ACK Flag Cnt",
    "urg_rate": "URG Flag Cnt",
    "log_distinct_src_ips": "Src IP",
    "log_distinct_dst_ips": "Dst IP",
    "log_distinct_pairs": "Src IP",
}

MAX_WINDOWS_PER_CAPTURE = 200_000


def add_capture_id(df: pd.DataFrame, source_name: str) -> pd.DataFrame:
    """Tag each flow with '<file stem>:<date>' so a multi-day file splits into daily captures."""
    stem = str(source_name).replace("\\", "/").rsplit("/", 1)[-1].rsplit(".", 1)[0]
    df = df.copy()
    df["capture_id"] = stem + ":" + df["Timestamp"].dt.strftime("%Y-%m-%d")
    return df


def missing_features(flows: pd.DataFrame) -> list[str]:
    return [f for f, src in FEATURE_SOURCES.items() if src not in flows.columns]


def _log1p_col(flows: pd.DataFrame, col: str) -> pd.Series:
    if col not in flows.columns:
        return pd.Series(0.0, index=flows.index)
    return np.log1p(flows[col].clip(lower=0).fillna(0).astype("float64"))


def _col(flows: pd.DataFrame, col: str) -> pd.Series:
    if col not in flows.columns:
        return pd.Series(0.0, index=flows.index)
    return flows[col].clip(lower=0).fillna(0).astype("float64")


def build_windows(
    flows: pd.DataFrame,
    window_seconds: int = 60,
    attack_fraction_threshold: float = 0.05,
) -> pd.DataFrame:
    """Aggregate flows (with ``capture_id``) into one row per (capture, window).

    Empty windows between the first and last flow of a capture are kept with
    zero features so that sequence steps are evenly spaced in time.

    Label columns: n_attack, n_labeled, attack_frac, is_attack (1 when the
    fraction of malicious flows >= attack_fraction_threshold, NaN if the window
    has flows but none are labeled), stage (dominant mapped stage among
    malicious flows) and top_label.
    """
    if "capture_id" not in flows.columns:
        raise ValueError("flows must have a capture_id column (use add_capture_id)")
    freq = f"{int(window_seconds)}s"
    proto = flows["Protocol"].astype("float64")
    port = flows["Dst Port"].astype("float64")
    d = pd.DataFrame(
        {
            "capture_id": flows["capture_id"].to_numpy(),
            "window_start": flows["Timestamp"].dt.floor(freq).to_numpy(),
            "tcp": (proto == 6).astype(float),
            "udp": (proto == 17).astype(float),
            "dur": _log1p_col(flows, "Flow Duration"),
            "fwd_pkts": _log1p_col(flows, "Tot Fwd Pkts"),
            "bwd_pkts": _log1p_col(flows, "Tot Bwd Pkts"),
            "no_bwd": (flows["Tot Bwd Pkts"].fillna(0) <= 0).astype(float),
            "fwd_bytes": _log1p_col(flows, "TotLen Fwd Pkts"),
            "bwd_bytes": _log1p_col(flows, "TotLen Bwd Pkts"),
            "iat": _log1p_col(flows, "Flow IAT Mean"),
            "syn": _col(flows, "SYN Flag Cnt"),
            "rst": _col(flows, "RST Flag Cnt"),
            "fin": _col(flows, "FIN Flag Cnt"),
            "psh": _col(flows, "PSH Flag Cnt"),
            "ack": _col(flows, "ACK Flag Cnt"),
            "urg": _col(flows, "URG Flag Cnt"),
            "dst_port": port,
            "port_high": (port >= 1024).astype(float),
            "is_attack": flows["is_attack"].astype("float64"),
        },
        index=flows.index,
    )
    for group, ports in PORT_GROUPS.items():
        d[f"port_{group}"] = port.isin(ports).astype(float)
    d["other_proto"] = 1.0 - d["tcp"] - d["udp"]

    keys = ["capture_id", "window_start"]
    g = d.groupby(keys, sort=True)
    w = g.agg(
        n_flows=("dur", "size"),
        frac_tcp=("tcp", "mean"),
        frac_udp=("udp", "mean"),
        frac_other_proto=("other_proto", "mean"),
        dur_mean=("dur", "mean"),
        dur_std=("dur", "std"),
        dur_max=("dur", "max"),
        fwd_pkts_mean=("fwd_pkts", "mean"),
        fwd_pkts_max=("fwd_pkts", "max"),
        bwd_pkts_mean=("bwd_pkts", "mean"),
        bwd_pkts_max=("bwd_pkts", "max"),
        frac_no_bwd=("no_bwd", "mean"),
        fwd_bytes_mean=("fwd_bytes", "mean"),
        fwd_bytes_max=("fwd_bytes", "max"),
        bwd_bytes_mean=("bwd_bytes", "mean"),
        iat_mean=("iat", "mean"),
        syn_rate=("syn", "mean"),
        rst_rate=("rst", "mean"),
        fin_rate=("fin", "mean"),
        psh_rate=("psh", "mean"),
        ack_rate=("ack", "mean"),
        urg_rate=("urg", "mean"),
        n_distinct_dst_ports=("dst_port", "nunique"),
        frac_port_high=("port_high", "mean"),
        n_attack=("is_attack", "sum"),
        n_labeled=("is_attack", "count"),
        **{f"frac_port_{grp}": (f"port_{grp}", "mean") for grp in PORT_GROUPS},
    )
    w["dur_std"] = w["dur_std"].fillna(0.0)

    if "Src IP" in flows.columns and "Dst IP" in flows.columns:
        ips = pd.DataFrame(
            {"capture_id": d["capture_id"], "window_start": d["window_start"],
             "src": flows["Src IP"].astype("string"), "dst": flows["Dst IP"].astype("string")}
        )
        gi = ips.groupby(keys, sort=True)
        w["n_distinct_src_ips"] = gi["src"].nunique()
        w["n_distinct_dst_ips"] = gi["dst"].nunique()
        w["n_distinct_pairs"] = ips.groupby(keys + ["src", "dst"], sort=False).size().groupby(level=[0, 1]).size()
    else:
        w["n_distinct_src_ips"] = 0
        w["n_distinct_dst_ips"] = 0
        w["n_distinct_pairs"] = 0

    # Dominant stage / label among malicious flows in each window.
    w["stage"] = None
    w["top_label"] = None
    if "Label" in flows.columns:
        attack_rows = flows["is_attack"] == 1
        if attack_rows.any():
            labels = flows.loc[attack_rows, "Label"].astype("string")
            stage_of = {lab: map_label(lab).stage for lab in labels.unique()}
            lab = pd.DataFrame(
                {"capture_id": d.loc[attack_rows, "capture_id"], "window_start": d.loc[attack_rows, "window_start"],
                 "label": labels, "stage": labels.map(stage_of)}
            )
            top = lab.groupby(keys)["label"].agg(lambda s: s.value_counts().index[0])
            w.loc[top.index, "top_label"] = top
            staged = lab.dropna(subset=["stage"])
            if not staged.empty:
                st = staged.groupby(keys)["stage"].agg(lambda s: s.value_counts().index[0])
                w.loc[st.index, "stage"] = st

    w = _fill_gaps(w, freq)

    w["log_n_flows"] = np.log1p(w["n_flows"])
    w["log_distinct_dst_ports"] = np.log1p(w["n_distinct_dst_ports"])
    w["distinct_dst_port_ratio"] = np.where(w["n_flows"] > 0, w["n_distinct_dst_ports"] / w["n_flows"].clip(lower=1), 0.0)
    w["log_distinct_src_ips"] = np.log1p(w["n_distinct_src_ips"])
    w["log_distinct_dst_ips"] = np.log1p(w["n_distinct_dst_ips"])
    w["log_distinct_pairs"] = np.log1p(w["n_distinct_pairs"])

    w["attack_frac"] = np.where(w["n_labeled"] > 0, w["n_attack"] / w["n_labeled"].clip(lower=1), 0.0)
    has_labels = flows["is_attack"].notna().any()
    if has_labels:
        known = (w["n_labeled"] > 0) | (w["n_flows"] == 0)
        attack = ((w["attack_frac"] >= attack_fraction_threshold) & (w["n_attack"] > 0)).astype(float)
        w["is_attack"] = attack.where(known, np.nan)
    else:
        w["is_attack"] = np.nan
    w.loc[w["is_attack"] != 1, "stage"] = None

    w = w.reset_index()
    w[FEATURES] = w[FEATURES].astype("float32")
    return w


def _fill_gaps(w: pd.DataFrame, freq: str) -> pd.DataFrame:
    """Reindex each capture onto a complete window grid, zero-filling empty windows."""
    parts = []
    for cap, grp in w.groupby(level=0, sort=True):
        starts = grp.index.get_level_values(1)
        grid = pd.date_range(starts.min(), starts.max(), freq=freq)
        if len(grid) > MAX_WINDOWS_PER_CAPTURE:
            raise ValueError(
                f"Capture {cap!r} spans {len(grid)} windows of {freq}; timestamps look inconsistent "
                "or the window is too small."
            )
        idx = pd.MultiIndex.from_product([[cap], grid], names=["capture_id", "window_start"])
        parts.append(grp.reindex(idx))
    out = pd.concat(parts)
    text_cols = ["stage", "top_label"]
    num_cols = [c for c in out.columns if c not in text_cols]
    out[num_cols] = out[num_cols].fillna(0.0)
    out[text_cols] = out[text_cols].astype(object).where(out[text_cols].notna(), None)
    return out


# ---------------------------------------------------------------------------
# Splits
# ---------------------------------------------------------------------------


@dataclass
class SplitInfo:
    method: str  # "by-capture" | "chronological-within-capture"
    train: list[str]
    val: list[str]
    test: list[str]
    note: str = ""
    test_hours: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"method": self.method, "train": self.train, "val": self.val, "test": self.test,
                "test_hours": self.test_hours, "note": self.note}


def assign_splits(
    windows: pd.DataFrame,
    test_captures: list[str] | None = None,
    val_captures: list[str] | None = None,
    test_frac: float = 0.2,
    val_frac: float = 0.2,
    seed: int = 42,
    val_block_windows: int = 0,
) -> tuple[pd.DataFrame, SplitInfo]:
    """Assign every window to train/val/test *before* sequences are built.

    With >= 3 captures (or explicit lists) whole captures go to one split.
    With fewer captures each capture is cut into contiguous 60/20/20 blocks and
    the block becomes the capture_id, so sequences never cross a block edge.
    With val_block_windows > 0 and no validation captures, validation comes from
    held-out time blocks of the training captures (see _blocked_validation).
    """
    windows = windows.copy()
    captures = sorted(windows["capture_id"].unique())

    if test_captures or val_captures:
        test = _match_captures(captures, test_captures or [])
        val = _match_captures(captures, val_captures or [])
        if set(test) & set(val):
            raise ValueError("A capture cannot be in both the test and validation split.")
        train = [c for c in captures if c not in test and c not in val]
        info = SplitInfo("by-capture", train, val, test, "explicit capture lists")
    elif len(captures) >= 3:
        info = _auto_capture_split(windows, captures, test_frac, val_frac, seed)
    else:
        parts = []
        for cap, grp in windows.groupby("capture_id", sort=True):
            n = len(grp)
            cut1, cut2 = int(n * 0.6), int(n * 0.8)
            split = np.array(["train"] * cut1 + ["val"] * (cut2 - cut1) + ["test"] * (n - cut2))
            grp = grp.copy()
            grp["split"] = split
            grp["capture_id"] = grp["capture_id"] + "#" + grp["split"]
            parts.append(grp)
        windows = pd.concat(parts, ignore_index=True)
        info = SplitInfo(
            "chronological-within-capture",
            sorted(c for c in windows["capture_id"].unique() if c.endswith("#train")),
            sorted(c for c in windows["capture_id"].unique() if c.endswith("#val")),
            sorted(c for c in windows["capture_id"].unique() if c.endswith("#test")),
            "Fewer than 3 captures: each capture was cut into contiguous 60/20/20 time blocks. "
            "Adjacent blocks are still correlated, so this is weaker than a by-day split.",
        )
        return windows, info

    lookup = {c: "train" for c in info.train} | {c: "val" for c in info.val} | {c: "test" for c in info.test}
    windows["split"] = windows["capture_id"].map(lookup)
    if val_block_windows and not info.val:
        windows, info = _blocked_validation(windows, info, val_block_windows, seed=seed)
    return windows, info


def _blocked_validation(windows: pd.DataFrame, info: SplitInfo, block: int, frac: float = 0.2,
                        seed: int = 42, test_frac: float = 0.15) -> tuple[pd.DataFrame, SplitInfo]:
    """Carve validation data out of the training captures as whole time blocks of ``block`` windows.

    Blocks are chosen by stratified random sampling: ``frac`` of the blocks that contain
    attack windows and ``frac`` of those that do not, so validation has a realistic mix
    of attack families and quiet periods. Each block becomes its own capture id, so no
    sequence spans train and validation. Test captures stay entirely unseen.

    A further ``test_frac`` of blocks (drawn the same way, disjoint from validation) is
    marked "test_hours": unseen hours of the training days, never used for training,
    early stopping or thresholds. It measures forecasting of known attack families at
    unseen times, while the test captures measure entirely unseen days.
    """
    rng = np.random.default_rng(seed)
    parts, blocks = [], []
    for cap, grp in windows.groupby("capture_id", sort=True):
        grp = grp.copy()
        if cap in info.train:
            b = np.arange(len(grp)) // block
            grp["capture_id"] = cap + "#block" + b.astype(str)
            for bid, bg in grp.groupby("capture_id", sort=True):
                blocks.append((bid, bool((bg["is_attack"] == 1).any())))
        parts.append(grp)
    windows = pd.concat(parts, ignore_index=True)
    val_ids: list[str] = []
    test_ids: list[str] = []
    for has_attack in (True, False):
        pool = [bid for bid, a in blocks if a == has_attack]
        if len(pool) < 3:
            continue
        order = list(rng.permutation(pool))
        n_val = max(1, int(round(len(pool) * frac)))
        n_test = int(round(len(pool) * test_frac)) if test_frac else 0
        val_ids += order[:n_val]
        test_ids += order[n_val:n_val + n_test]
    val_ids, test_ids = sorted(val_ids), sorted(test_ids)
    windows.loc[windows["capture_id"].isin(val_ids), "split"] = "val"
    windows.loc[windows["capture_id"].isin(test_ids), "split"] = "test_hours"
    note = (info.note + "; " if info.note else "") + (
        f"validation = {len(val_ids)} and test_hours = {len(test_ids)} blocks of {block} windows drawn (stratified by "
        f"attack presence, seed={seed}) from the training captures; blocks never share a sequence; "
        "test captures are entire unseen days")
    out = SplitInfo(info.method + "+blocked-val", info.train, val_ids, info.test, note)
    out.test_hours = test_ids
    return windows, out


def _match_captures(captures: list[str], wanted: list[str]) -> list[str]:
    """Match user-given names against capture ids (exact, or file-stem / date prefix)."""
    out = []
    for w in wanted:
        hits = [c for c in captures if c == w or c.split(":")[0] == w or c.startswith(w)]
        if not hits:
            raise ValueError(f"Capture {w!r} not found. Available: {', '.join(captures)}")
        out.extend(h for h in hits if h not in out)
    return out


def _auto_capture_split(windows, captures, test_frac, val_frac, seed) -> SplitInfo:
    n = len(captures)
    n_test = max(1, round(n * test_frac))
    n_val = max(1, round(n * val_frac)) if n - n_test >= 2 else 0
    positives = windows.groupby("capture_id")["is_attack"].apply(lambda s: bool((s == 1).any())).to_dict()
    rng = np.random.default_rng(seed)
    first = None
    for _ in range(200):
        order = list(rng.permutation(captures))
        test, val, train = order[:n_test], order[n_test:n_test + n_val], order[n_test + n_val:]
        first = first or (train, val, test)
        if all(any(positives.get(c, False) for c in part) for part in (train, test) + ((val,) if val else ())):
            return SplitInfo("by-capture", sorted(train), sorted(val), sorted(test), f"random capture split, seed={seed}")
    train, val, test = first
    return SplitInfo(
        "by-capture", sorted(train), sorted(val), sorted(test),
        f"random capture split, seed={seed}; could not place attack windows in every split",
    )


# ---------------------------------------------------------------------------
# Sequences
# ---------------------------------------------------------------------------


@dataclass
class SequenceSet:
    """Context windows plus the K windows that follow them (the world model's targets)."""

    X: np.ndarray  # (N, L, F) scaled context states S_t-L+1 .. S_t
    FS: np.ndarray  # (N, K, F) scaled future states S_t+1 .. S_t+K (zeros beyond the data)
    FY: np.ndarray  # (N, K) future window labels (NaN when unknown / beyond the data)
    FST: np.ndarray  # (N, K) future stage indices (-100 when none)
    CY: np.ndarray  # (N, L) context window labels
    CST: np.ndarray  # (N, L) context stage indices
    meta: pd.DataFrame  # capture_id, input_start, input_end, forecast_start, n_future_in_data

    def __len__(self) -> int:
        return len(self.X)

    @property
    def last_is_attack(self) -> np.ndarray:
        return self.CY[:, -1]

    def subset(self, keep: np.ndarray) -> "SequenceSet":
        return SequenceSet(self.X[keep], self.FS[keep], self.FY[keep], self.FST[keep], self.CY[keep], self.CST[keep],
                           self.meta.loc[keep].reset_index(drop=True))

    def arrays(self) -> dict:
        """numpy arrays in the form models.train_world_model expects (NaN context labels -> 0 mask handled there)."""
        return {"X": self.X, "FS": self.FS, "FY": self.FY, "FST": self.FST, "CY": self.CY, "CST": self.CST}


def make_sequences(
    windows: pd.DataFrame,
    features: np.ndarray,
    seq_len: int,
    k: int,
    window_seconds: int,
    include_future: bool = False,
) -> SequenceSet:
    """Build (S_t-L+1 .. S_t) -> (S_t+1 .. S_t+K) examples inside each capture.

    ``features`` is the scaled feature matrix aligned row-for-row with ``windows``.
    Training sets use only positions whose K future windows are all in the data.
    With include_future=True every position from the first full context to the last
    window is emitted; future windows beyond the data carry NaN labels. The last of
    these are the genuine forecasts.
    """
    if seq_len < 1 or k < 1:
        raise ValueError("seq_len and k must be >= 1")
    n_feat = features.shape[1]
    parts: dict[str, list] = {n: [] for n in ("X", "FS", "FY", "FST", "CY", "CST", "meta")}
    step = pd.Timedelta(seconds=window_seconds)
    windows = windows.reset_index(drop=True)
    for cap, idx in windows.groupby("capture_id", sort=False).indices.items():
        idx = np.sort(idx)
        n = len(idx)
        last_t = n - 1 if include_future else n - 1 - k
        ts = np.arange(seq_len - 1, last_t + 1)
        if len(ts) == 0:
            continue
        F = np.concatenate([features[idx], np.zeros((k, n_feat), dtype=features.dtype)])
        cap_w = windows.iloc[idx]
        is_attack = np.concatenate([cap_w["is_attack"].to_numpy(dtype="float64"), np.full(k, np.nan)])
        stage_idx = np.concatenate([np.array([stage_index(s) for s in cap_w["stage"]], dtype=np.int64),
                                    np.full(k, -100, dtype=np.int64)])
        ctx = ts[:, None] + np.arange(-seq_len + 1, 1)
        fut = ts[:, None] + np.arange(1, k + 1)
        parts["X"].append(F[ctx])
        parts["FS"].append(F[fut])
        parts["FY"].append(is_attack[fut].astype("float32"))
        parts["FST"].append(np.where(is_attack[fut] == 1, stage_idx[fut], -100))
        parts["CY"].append(is_attack[ctx].astype("float32"))
        parts["CST"].append(np.where(is_attack[ctx] == 1, stage_idx[ctx], -100))
        starts = cap_w["window_start"].to_numpy()
        parts["meta"].append(
            pd.DataFrame(
                {
                    "capture_id": cap,
                    "input_start": starts[ts - seq_len + 1],
                    "input_end": starts[ts],
                    "forecast_start": pd.to_datetime(starts[ts]) + step,
                    "n_future_in_data": np.minimum(n - 1 - ts, k),
                }
            )
        )
    if not parts["X"]:
        return SequenceSet(
            np.zeros((0, seq_len, n_feat), dtype="float32"), np.zeros((0, k, n_feat), dtype="float32"),
            np.zeros((0, k), dtype="float32"), np.zeros((0, k), dtype=np.int64),
            np.zeros((0, seq_len), dtype="float32"), np.zeros((0, seq_len), dtype=np.int64),
            pd.DataFrame(columns=["capture_id", "input_start", "input_end", "forecast_start", "n_future_in_data"]),
        )
    return SequenceSet(
        np.concatenate(parts["X"]).astype("float32"),
        np.concatenate(parts["FS"]).astype("float32"),
        np.concatenate(parts["FY"]),
        np.concatenate(parts["FST"]).astype(np.int64),
        np.concatenate(parts["CY"]),
        np.concatenate(parts["CST"]).astype(np.int64),
        pd.concat(parts["meta"], ignore_index=True),
    )


__all__ = [
    "FEATURES", "STAGES", "SequenceSet", "SplitInfo", "add_capture_id", "assign_splits",
    "build_windows", "make_sequences", "missing_features",
]
