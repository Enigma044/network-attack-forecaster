"""Input schema and validation for CIC-IDS-2018 flow CSVs (CICFlowMeter export).

Only a subset of the ~80 CICFlowMeter columns is read. Header names are matched
after trimming whitespace and ignoring case, and the CIC-IDS-2017 spellings
("Destination Port", "Total Fwd Packets", ...) are accepted as aliases.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import IO

import numpy as np
import pandas as pd
from pandas.api.types import union_categoricals

# canonical name -> accepted header spellings
COLUMN_ALIASES: dict[str, list[str]] = {
    "Timestamp": ["Timestamp"],
    "Dst Port": ["Dst Port", "Destination Port"],
    "Protocol": ["Protocol"],
    "Flow Duration": ["Flow Duration"],
    "Tot Fwd Pkts": ["Tot Fwd Pkts", "Total Fwd Packets"],
    "Tot Bwd Pkts": ["Tot Bwd Pkts", "Total Backward Packets"],
    "TotLen Fwd Pkts": ["TotLen Fwd Pkts", "Total Length of Fwd Packets"],
    "TotLen Bwd Pkts": ["TotLen Bwd Pkts", "Total Length of Bwd Packets"],
    "Flow IAT Mean": ["Flow IAT Mean"],
    "FIN Flag Cnt": ["FIN Flag Cnt", "FIN Flag Count"],
    "SYN Flag Cnt": ["SYN Flag Cnt", "SYN Flag Count"],
    "RST Flag Cnt": ["RST Flag Cnt", "RST Flag Count"],
    "PSH Flag Cnt": ["PSH Flag Cnt", "PSH Flag Count"],
    "ACK Flag Cnt": ["ACK Flag Cnt", "ACK Flag Count"],
    "URG Flag Cnt": ["URG Flag Cnt", "URG Flag Count"],
    "Src IP": ["Src IP", "Source IP"],
    "Dst IP": ["Dst IP", "Destination IP"],
    "Label": ["Label"],
    "Synthetic": ["Synthetic"],  # marker column written by netforecast.synthetic
}

REQUIRED_COLUMNS = ["Timestamp", "Dst Port", "Protocol", "Flow Duration", "Tot Fwd Pkts", "Tot Bwd Pkts"]
OPTIONAL_COLUMNS = [c for c in COLUMN_ALIASES if c not in REQUIRED_COLUMNS and c != "Synthetic"]
NUMERIC_COLUMNS = [c for c in COLUMN_ALIASES if c not in ("Timestamp", "Src IP", "Dst IP", "Label")]

# CTU-13 bidirectional NetFlow (.binetflow) headers, recognised only to give a clear message.
_CTU13_MARKERS = {"starttime", "srcaddr", "dstaddr", "totbytes"}

TIMESTAMP_FORMATS = ["%d/%m/%Y %H:%M:%S", "%d/%m/%Y %I:%M:%S %p", "%Y-%m-%d %H:%M:%S"]

MAX_BAD_ROW_FRACTION = 0.5
CHUNK_ROWS = 500_000  # rows parsed at a time; keeps peak memory low for ~1 GB files


@dataclass
class ValidationReport:
    source: str
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    n_rows_read: int = 0
    n_rows_valid: int = 0
    columns_found: list[str] = field(default_factory=list)
    optional_missing: list[str] = field(default_factory=list)
    has_labels: bool = False
    data_kind: str = "external"  # "external" (user-supplied CSV) or "synthetic"
    time_start: pd.Timestamp | None = None
    time_end: pd.Timestamp | None = None
    label_counts: dict[str, int] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.errors


def _norm(name: str) -> str:
    return str(name).strip().lower()


def _resolve_columns(header: list[str]) -> dict[str, str]:
    """Map raw header names to canonical names (first match wins)."""
    lookup: dict[str, str] = {}
    for canonical, aliases in COLUMN_ALIASES.items():
        for alias in aliases:
            lookup.setdefault(_norm(alias), canonical)
    resolved: dict[str, str] = {}
    taken: set[str] = set()
    for raw in header:
        canonical = lookup.get(_norm(raw))
        if canonical and canonical not in taken:
            resolved[raw] = canonical
            taken.add(canonical)
    return resolved


def _rewind(source) -> None:
    if hasattr(source, "seek"):
        source.seek(0)


def parse_timestamps(values: pd.Series) -> pd.Series:
    """Parse CIC timestamps (day-first). Tries the known formats before a generic fallback."""
    text = values.astype("string").str.strip()
    best = None
    for fmt in TIMESTAMP_FORMATS:
        parsed = pd.to_datetime(text, format=fmt, errors="coerce")
        if best is None or parsed.notna().sum() > best.notna().sum():
            best = parsed
        if parsed.notna().mean() > 0.99:
            return parsed
    fallback = pd.to_datetime(text, dayfirst=True, format="mixed", errors="coerce")
    return fallback if fallback.notna().sum() > best.notna().sum() else best


def _fix_cic2018_clock(df: pd.DataFrame, has_ampm: bool, report: ValidationReport) -> None:
    """Repair two known CIC-IDS-2018 timestamp quirks in place.

    * A handful of rows carry epoch-era dates (1970); they are dropped (set to NaT).
    * The CSVs use a 12-hour clock without AM/PM: afternoon flows (13:00–19:59) are
      written as 01:00–07:59. When no hour is >= 13, the file spans both sides of 08:00,
      and no AM/PM marker is present, hours before 08:00 are moved to the afternoon.
      This matches the dataset's documented attack schedule (e.g. SSH brute force on
      14-02-2018 at 14:01–15:31 appears as 02:01–03:31 in the file).
    """
    ts = df["Timestamp"]
    bogus = ts.notna() & (ts < pd.Timestamp("2000-01-01"))
    if bogus.any():
        report.warnings.append(f"{int(bogus.sum())} row(s) have epoch-era timestamps (before 2000) and were dropped.")
        df.loc[bogus, "Timestamp"] = pd.NaT
        ts = df["Timestamp"]
    hours = ts.dt.hour
    valid = ts.notna()
    if not valid.any() or has_ampm:
        return
    if hours[valid].max() <= 12 and (hours[valid] < 8).any() and (hours[valid] >= 8).any():
        pm = valid & (hours < 8)
        df.loc[pm, "Timestamp"] = ts[pm] + pd.Timedelta(hours=12)
        report.warnings.append(
            f"12-hour clock without AM/PM detected (known CIC-IDS-2018 quirk): {int(pm.sum())} row(s) timed "
            "01:00–07:59 were read as 13:00–19:59."
        )


def load_flows(source: str | Path | IO, name: str | None = None) -> tuple[pd.DataFrame | None, ValidationReport]:
    """Read and validate one flow CSV.

    Returns (flows, report). flows is None when the report has errors. The frame
    uses canonical column names, is sorted by Timestamp, and has an ``is_attack``
    column (1.0/0.0, NaN when unlabeled).
    """
    name = name or getattr(source, "name", None) or str(source)
    report = ValidationReport(source=str(name))

    try:
        _rewind(source)
        header = list(pd.read_csv(source, nrows=0).columns)
    except pd.errors.EmptyDataError:
        report.errors.append("The file is empty.")
        return None, report
    except (UnicodeDecodeError, pd.errors.ParserError, ValueError, OSError) as exc:
        report.errors.append(f"Could not read a CSV header: {exc}")
        return None, report

    if _CTU13_MARKERS <= {_norm(h) for h in header}:
        report.errors.append(
            "This looks like a CTU-13 .binetflow file. CTU-13 is not supported in this MVP; "
            "please upload a CIC-IDS-2018 (CICFlowMeter) flow CSV."
        )
        return None, report

    resolved = _resolve_columns(header)
    report.columns_found = sorted(resolved.values(), key=list(COLUMN_ALIASES).index)
    missing_required = [c for c in REQUIRED_COLUMNS if c not in resolved.values()]
    if missing_required:
        report.errors.append(
            "Missing required column(s): " + ", ".join(missing_required)
            + ". Expected a CIC-IDS-2018 CICFlowMeter CSV (see README, 'Supported input')."
        )
        return None, report
    report.optional_missing = [c for c in OPTIONAL_COLUMNS if c not in resolved.values()]
    if report.optional_missing:
        report.warnings.append(
            "Optional column(s) not present; related features will be zero: " + ", ".join(report.optional_missing)
        )

    # Parse in chunks: each chunk is cleaned and converted to compact dtypes straight away, so
    # a stray repeated header line never forces whole columns into Python strings.
    parts: list[pd.DataFrame] = []
    label_parts: list[pd.Categorical] = []
    n_repeated = 0
    has_ampm = False
    try:
        _rewind(source)
        for chunk in pd.read_csv(source, usecols=list(resolved), low_memory=False, chunksize=CHUNK_ROWS):
            chunk = chunk.rename(columns=resolved)
            report.n_rows_read += len(chunk)
            # CIC-IDS-2018 files contain repeated header lines in the middle of the data.
            repeated = chunk["Timestamp"].astype("string").str.strip().str.lower() == "timestamp"
            if repeated.any():
                n_repeated += int(repeated.sum())
                chunk = chunk.loc[~repeated]
            raw_ts = chunk["Timestamp"].astype("string")
            has_ampm = has_ampm or bool(raw_ts.str.contains(r"\b(?:AM|PM)\b", case=False, regex=True).any())
            chunk["Timestamp"] = parse_timestamps(raw_ts)
            for col in NUMERIC_COLUMNS:
                if col in chunk.columns:
                    chunk[col] = (pd.to_numeric(chunk[col], errors="coerce")
                                  .replace([np.inf, -np.inf], np.nan).astype("float32"))
            if "Label" in chunk.columns:
                label = chunk.pop("Label").astype("string").str.strip()
                label_parts.append(pd.Categorical(label.mask(label == "")))
            parts.append(chunk)
    except (pd.errors.ParserError, ValueError, OSError) as exc:
        report.errors.append(f"Could not parse the CSV body: {exc}")
        return None, report
    if not parts or report.n_rows_read == 0:
        report.errors.append("The file has a header but no data rows.")
        return None, report
    df = pd.concat(parts, ignore_index=True)
    del parts
    if label_parts:
        df["Label"] = union_categoricals(label_parts)
        del label_parts
    if n_repeated:
        report.warnings.append(f"Dropped {n_repeated} repeated header row(s).")

    _fix_cic2018_clock(df, has_ampm, report)

    bad_ts = df["Timestamp"].isna()
    bad_required = df[REQUIRED_COLUMNS[1:]].isna().any(axis=1)
    bad = bad_ts | bad_required
    n_bad = int(bad.sum()) + n_repeated
    if bad_ts.any():
        report.warnings.append(f"{int(bad_ts.sum())} row(s) have an unparseable Timestamp and were dropped.")
    if (bad_required & ~bad_ts).any():
        report.warnings.append(
            f"{int((bad_required & ~bad_ts).sum())} row(s) have non-numeric required values and were dropped."
        )
    if bad.any():
        df = df.loc[~bad]
    if df.empty or n_bad / max(report.n_rows_read, 1) > MAX_BAD_ROW_FRACTION:
        report.errors.append(
            f"{n_bad} of {report.n_rows_read} rows are malformed (more than {MAX_BAD_ROW_FRACTION:.0%}). "
            "Check the timestamp format (expected dd/mm/YYYY HH:MM:SS) and numeric columns."
        )
        return None, report

    negative = df["Flow Duration"] < 0
    if negative.any():
        report.warnings.append(f"{int(negative.sum())} row(s) have negative Flow Duration; clipped to 0.")
        df.loc[negative, "Flow Duration"] = 0

    if "Label" in df.columns:
        labels = df["Label"]
        report.has_labels = bool(labels.notna().any())
        if report.has_labels and labels.isna().any():
            report.warnings.append(f"{int(labels.isna().sum())} row(s) have no Label; treated as unlabeled.")
        benign = np.asarray(labels.cat.categories.astype(str).str.lower() == "benign")
        codes = labels.cat.codes.to_numpy()
        attack = np.where(codes >= 0, ~benign[np.clip(codes, 0, None)], False).astype("float32")
        df["is_attack"] = np.where(codes < 0, np.nan, attack).astype("float32")
        report.label_counts = {str(k): int(v) for k, v in labels.value_counts().items() if v > 0}
    else:
        df["is_attack"] = np.float32(np.nan)
        report.warnings.append("No Label column: forecasts can be produced, but not evaluated.")

    if "Synthetic" in df.columns and (df["Synthetic"] == 1).any():
        report.data_kind = "synthetic"

    if not df["Timestamp"].is_monotonic_increasing:
        df = df.sort_values("Timestamp", kind="stable")
    df = df.reset_index(drop=True)
    report.n_rows_valid = len(df)
    report.time_start = df["Timestamp"].iloc[0]
    report.time_end = df["Timestamp"].iloc[-1]
    return df, report
