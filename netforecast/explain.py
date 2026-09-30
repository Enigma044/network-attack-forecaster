"""Explanations for world-model forecasts.

* Feature attribution: Shapley values estimated by permutation sampling (the method
  behind SHAP's PermutationExplainer). A feature that is "absent" is set to its
  training mean (0 after scaling) in every context window. The explained output is
  the mean attack log-odds across the K simulated future windows (mean rollout), so
  the values add up to (prediction − baseline prediction) in log-odds. Log-odds are
  used because probabilities saturate near 0 and 1.
* Temporal attribution: occlude one context window at a time (set it to the
  training mean) and record the change in that log-odds. Shows *when* the evidence
  appeared.

These describe how the model responds to its inputs; they do not prove cause.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import torch

from .models import WorldModel

FEATURE_DESCRIPTIONS: dict[str, str] = {
    "log_n_flows": "flow count",
    "frac_tcp": "share of TCP flows",
    "frac_udp": "share of UDP flows",
    "frac_other_proto": "share of non-TCP/UDP flows",
    "dur_mean": "mean flow duration",
    "dur_std": "spread of flow durations",
    "dur_max": "longest flow",
    "fwd_pkts_mean": "mean forward packets per flow",
    "fwd_pkts_max": "max forward packets per flow",
    "bwd_pkts_mean": "mean backward packets per flow",
    "bwd_pkts_max": "max backward packets per flow",
    "frac_no_bwd": "share of flows with no reply packets",
    "fwd_bytes_mean": "mean forward bytes",
    "fwd_bytes_max": "max forward bytes",
    "bwd_bytes_mean": "mean backward bytes",
    "iat_mean": "mean packet inter-arrival time",
    "syn_rate": "SYN flags per flow",
    "rst_rate": "RST flags per flow",
    "fin_rate": "FIN flags per flow",
    "psh_rate": "PSH flags per flow",
    "ack_rate": "ACK flags per flow",
    "urg_rate": "URG flags per flow",
    "log_distinct_dst_ports": "distinct destination ports",
    "distinct_dst_port_ratio": "distinct destination ports per flow",
    "frac_port_ftp": "share of flows to FTP (20/21)",
    "frac_port_ssh": "share of flows to SSH (22)",
    "frac_port_web": "share of flows to web ports",
    "frac_port_rdp": "share of flows to RDP (3389)",
    "frac_port_smb": "share of flows to SMB (139/445)",
    "frac_port_dns": "share of flows to DNS (53)",
    "frac_port_high": "share of flows to ports >= 1024",
    "log_distinct_src_ips": "distinct source addresses",
    "log_distinct_dst_ips": "distinct destination addresses",
    "log_distinct_pairs": "distinct source→destination pairs",
}

FEATURE_GROUPS: dict[str, str] = {
    **{f: "volume" for f in ("log_n_flows",)},
    **{f: "protocol" for f in ("frac_tcp", "frac_udp", "frac_other_proto")},
    **{f: "timing" for f in ("dur_mean", "dur_std", "dur_max", "iat_mean")},
    **{f: "packets & bytes" for f in ("fwd_pkts_mean", "fwd_pkts_max", "bwd_pkts_mean", "bwd_pkts_max",
                                       "frac_no_bwd", "fwd_bytes_mean", "fwd_bytes_max", "bwd_bytes_mean")},
    **{f: "TCP flags" for f in ("syn_rate", "rst_rate", "fin_rate", "psh_rate", "ack_rate", "urg_rate")},
    **{f: "ports" for f in ("log_distinct_dst_ports", "distinct_dst_port_ratio", "frac_port_ftp", "frac_port_ssh",
                             "frac_port_web", "frac_port_rdp", "frac_port_smb", "frac_port_dns", "frac_port_high")},
    **{f: "hosts" for f in ("log_distinct_src_ips", "log_distinct_dst_ips", "log_distinct_pairs")},
}


@torch.no_grad()
def _any_logodds(model: WorldModel, batch: np.ndarray, k: int) -> np.ndarray:
    """Mean attack log-odds over the k simulated windows (mean rollout)."""
    logits, _, _ = model.rollout(torch.from_numpy(batch.astype("float32")), k)
    return logits.mean(dim=1).numpy().astype("float64")


def shapley_features(model: WorldModel, x_seq: np.ndarray, k: int, n_permutations: int = 24, seed: int = 0) -> tuple[np.ndarray, float, float]:
    """Permutation-sampling Shapley values per feature for one (L, F) context.

    Returns (phi (F,), prediction log-odds, baseline log-odds). sum(phi) equals
    prediction - baseline exactly (each permutation telescopes).
    """
    L, F = x_seq.shape
    rng = np.random.default_rng(seed)
    perms = [rng.permutation(F) for _ in range(n_permutations)]
    batch = np.zeros((n_permutations, F + 1, L, F), dtype="float32")
    for i, perm in enumerate(perms):
        for j in range(1, F + 1):
            batch[i, j] = batch[i, j - 1]
            f = perm[j - 1]
            batch[i, j, :, f] = x_seq[:, f]
    out = _any_logodds(model, batch.reshape(-1, L, F), k).reshape(n_permutations, F + 1)
    phi = np.zeros(F)
    for i, perm in enumerate(perms):
        phi[perm] += np.diff(out[i])
    phi /= n_permutations
    base = float(out[:, 0].mean())
    pred = float(out[:, -1].mean())
    return phi, pred, base


def temporal_importance(model: WorldModel, x_seq: np.ndarray, k: int) -> np.ndarray:
    """Change in log-odds when each context window is replaced by the training mean."""
    L, _ = x_seq.shape
    batch = np.repeat(x_seq[None], L + 1, axis=0)
    for t in range(L):
        batch[t + 1, t] = 0.0
    out = _any_logodds(model, batch, k)
    return out[0] - out[1:]


def explain_forecast(model: WorldModel, x_seq: np.ndarray, feature_names: list[str], k: int,
                     n_permutations: int = 24) -> dict:
    phi, pred, base = shapley_features(model, x_seq, k, n_permutations)
    table = pd.DataFrame(
        {
            "feature": feature_names,
            "description": [FEATURE_DESCRIPTIONS.get(f, f) for f in feature_names],
            "group": [FEATURE_GROUPS.get(f, "other") for f in feature_names],
            "shap_logodds": phi,
            "z_last": x_seq[-1],
            "z_peak": x_seq[np.abs(x_seq).argmax(axis=0), np.arange(x_seq.shape[1])],
        }
    )
    table = table.reindex(table["shap_logodds"].abs().sort_values(ascending=False).index).reset_index(drop=True)
    groups = table.groupby("group")["shap_logodds"].sum().sort_values(key=np.abs, ascending=False)
    return {
        "table": table,
        "groups": groups,
        "pred_logodds": pred,
        "base_logodds": base,
        "temporal": temporal_importance(model, x_seq, k),
    }


def summarize(table: pd.DataFrame, top_k: int = 3) -> list[str]:
    """Plain-language sentences for the strongest contributors."""
    lines = []
    for row in table.head(top_k).itertuples():
        if abs(row.shap_logodds) < 0.05:
            continue
        z = row.z_last
        size = "slightly" if abs(z) < 1 else "noticeably" if abs(z) < 2 else "much"
        direction = "higher" if z >= 0 else "lower"
        strong = abs(row.shap_logodds) >= 1
        effect = (f"made the model {'much ' if strong else ''}more worried" if row.shap_logodds > 0
                  else f"{'strongly ' if strong else ''}reassured it")
        lines.append(
            f"In the latest minute, the {row.description} was {size} {direction} than normal ({z:+.1f}σ). "
            f"That {effect} ({row.shap_logodds:+.2f} log-odds)."
        )
    return lines
