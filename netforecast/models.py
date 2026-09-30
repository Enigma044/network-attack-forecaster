"""World model (LSTM state-transition model), logistic-regression baseline, thresholds and metrics.

The world model learns the dynamics of the window-level network state:

    h_t              = LSTM(S_1 .. S_t)
    P(S_t+1 | S_≤t)  = Normal(mu(h_t), diag(sigma²(h_t)))      next-state head
    P(attack_t+1)    = sigmoid(a(h_t))                           attack head
    P(stage_t+1)     = softmax(g(h_t))                           stage head (ATT&CK-style stages)

Forecasting is forward simulation: from the observed context, sample S_t+1, feed it
back in, and repeat K times. Many sampled rollouts give a distribution over the
next K windows' attack probabilities.
"""

from __future__ import annotations

import copy
import os
from dataclasses import dataclass

import numpy as np
import torch
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, confusion_matrix, precision_recall_curve
from torch import nn

from .stages import STAGES

LOGVAR_MIN, LOGVAR_MAX = -6.0, 3.0


class WorldModel(nn.Module):
    def __init__(self, n_features: int, hidden: int = 64, layers: int = 1, dropout: float = 0.1, n_stages: int = len(STAGES)):
        super().__init__()
        self.n_features = n_features
        self.lstm = nn.LSTM(n_features, hidden, num_layers=layers, batch_first=True,
                            dropout=dropout if layers > 1 else 0.0)
        self.drop = nn.Dropout(dropout)
        self.state_mu = nn.Linear(hidden, n_features)
        self.state_logvar = nn.Linear(hidden, n_features)
        self.attack_head = nn.Linear(hidden, 1)
        self.stage_head = nn.Linear(hidden, n_stages)

    def heads(self, h: torch.Tensor):
        h = self.drop(h)
        mu = self.state_mu(h)
        logvar = self.state_logvar(h).clamp(LOGVAR_MIN, LOGVAR_MAX)
        return mu, logvar, self.attack_head(h).squeeze(-1), self.stage_head(h)

    def forward(self, seq: torch.Tensor):
        """Teacher-forced pass: outputs at position i describe window i+1."""
        out, _ = self.lstm(seq)
        return self.heads(out)

    def rollout(self, context: torch.Tensor, k: int, sample: bool = False, generator: torch.Generator | None = None):
        """Simulate k future windows from a (B, L, F) context.

        Returns attack logits (B, k), stage logits (B, k, n_stages) and simulated
        states (B, k, F). With sample=True each step draws S_t+1 from the predicted
        Gaussian; otherwise it uses the mean.
        """
        out, hc = self.lstm(context)
        h = out[:, -1]
        logits, stages, states = [], [], []
        for step in range(k):
            mu, logvar, a, s = self.heads(h)
            logits.append(a)
            stages.append(s)
            nxt = mu
            if sample:
                noise = torch.randn(mu.shape, generator=generator, device=mu.device)
                nxt = mu + noise * torch.exp(0.5 * logvar)
            states.append(nxt)
            if step < k - 1:
                out, hc = self.lstm(nxt.unsqueeze(1), hc)
                h = out[:, -1]
        return torch.stack(logits, 1), torch.stack(stages, 1), torch.stack(states, 1)


@dataclass
class WorldModelConfig:
    hidden: int = 64
    layers: int = 1
    dropout: float = 0.1
    epochs: int = 40
    batch_size: int = 64
    lr: float = 1e-3
    weight_decay: float = 0.0
    state_loss_weight: float = 0.05
    stage_loss_weight: float = 0.3
    rollout_loss_weight: float = 1.0
    patience: int = 6
    seed: int = 42


def _set_threads() -> None:
    torch.set_num_threads(max(1, min(8, os.cpu_count() or 1)))


def _masked_bce(logits, targets, pos_weight):
    mask = ~torch.isnan(targets)
    if not mask.any():
        return logits.sum() * 0.0
    return nn.functional.binary_cross_entropy_with_logits(
        logits[mask], targets[mask], pos_weight=pos_weight)


def _stage_ce(stage_logits, stage_targets):
    flat_t = stage_targets.reshape(-1)
    if not (flat_t != -100).any():
        return stage_logits.sum() * 0.0
    return nn.functional.cross_entropy(stage_logits.reshape(-1, stage_logits.shape[-1]), flat_t, ignore_index=-100)


def world_model_loss(model: WorldModel, batch: dict, cfg: WorldModelConfig, pos_weight: torch.Tensor):
    """Teacher-forced one-step loss over context+future, plus an open-loop K-step rollout loss."""
    X, FS, FY, FST, CY, CST = (batch[k] for k in ("X", "FS", "FY", "FST", "CY", "CST"))
    k = FS.shape[1]
    full = torch.cat([X, FS], 1)                       # windows 1 .. L+K
    labels = torch.cat([CY, FY], 1)[:, 1:]             # labels of windows 2 .. L+K
    stages = torch.cat([CST, FST], 1)[:, 1:]
    mu, logvar, a, s = model(full[:, :-1])
    target = full[:, 1:]
    nll = 0.5 * (logvar + (target - mu) ** 2 / logvar.exp()).mean()
    tf = cfg.state_loss_weight * nll + _masked_bce(a, labels, pos_weight) + cfg.stage_loss_weight * _stage_ce(s, stages)

    ra, rs, rstate = model.rollout(X, k)
    ol = _masked_bce(ra, FY, pos_weight) + cfg.stage_loss_weight * _stage_ce(rs, FST)
    ol = ol + cfg.state_loss_weight * ((rstate - FS) ** 2).mean()
    return tf + cfg.rollout_loss_weight * ol, float(nll.detach())


def _to_tensors(d: dict) -> dict:
    return {k: torch.from_numpy(v) for k, v in d.items()}


def train_world_model(train: dict, val: dict | None, cfg: WorldModelConfig, log=print) -> tuple[WorldModel, list[dict]]:
    """train/val: dicts of numpy arrays X (N,L,F), FS (N,K,F), FY (N,K), FST (N,K), CY (N,L), CST (N,L)."""
    _set_threads()
    torch.manual_seed(cfg.seed)
    rng = np.random.default_rng(cfg.seed)
    model = WorldModel(train["X"].shape[2], cfg.hidden, cfg.layers, cfg.dropout)
    opt = torch.optim.AdamW(model.parameters(), lr=cfg.lr, weight_decay=cfg.weight_decay)
    fy = train["FY"][~np.isnan(train["FY"])]
    n_pos = float(fy.sum())
    pos_weight = torch.tensor(np.clip((len(fy) - n_pos) / max(n_pos, 1.0), 1.0, 50.0), dtype=torch.float32)
    T = _to_tensors(train)
    V = _to_tensors(val) if val is not None and len(val["X"]) else None
    best_state, best, bad, history = None, float("inf"), 0, []
    n = len(T["X"])
    for epoch in range(1, cfg.epochs + 1):
        model.train()
        order = rng.permutation(n)
        total = 0.0
        for start in range(0, n, cfg.batch_size):
            b = torch.from_numpy(order[start:start + cfg.batch_size])
            opt.zero_grad()
            loss, _ = world_model_loss(model, {k: v[b] for k, v in T.items()}, cfg, pos_weight)
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
            total += loss.item() * len(b)
        row = {"epoch": epoch, "train_loss": total / n}
        if V is not None:
            model.eval()
            with torch.no_grad():
                vl, vnll = world_model_loss(model, V, cfg, pos_weight)
            row["val_loss"], row["val_state_nll"] = float(vl), vnll
        history.append(row)
        log(f"  epoch {epoch:3d}  train_loss={row['train_loss']:.4f}" + (f"  val_loss={row['val_loss']:.4f}" if V is not None else ""))
        monitor = row.get("val_loss", row["train_loss"])
        if monitor < best - 1e-4:
            best, best_state, bad = monitor, copy.deepcopy(model.state_dict()), 0
        else:
            bad += 1
            if V is not None and bad >= cfg.patience:
                log(f"  early stop at epoch {epoch} (best val_loss={best:.4f})")
                break
    if best_state is not None:
        model.load_state_dict(best_state)
    model.eval()
    return model, history


@torch.no_grad()
def simulate(model: WorldModel, X: np.ndarray, k: int, n_samples: int = 0, seed: int = 0, batch: int = 1024) -> dict:
    """Forward-simulate k windows for every context in X.

    Returns per-step attack probabilities from the mean rollout ("p", (N,k)),
    stage probabilities ((N,k,S)) and, if n_samples > 0, sampled rollouts:
    per-step 10th/90th percentiles and P(attack within k windows).

    P(attack within k) is the peak per-step probability along each simulated
    trajectory, averaged over trajectories. Consecutive windows are strongly
    correlated, so treating steps as independent (1 - prod(1 - p)) would overstate it.
    """
    _set_threads()
    model.eval()
    N = len(X)
    p = np.zeros((N, k), dtype="float32")
    st = np.zeros((N, k, len(STAGES)), dtype="float32")
    out = {"p": p, "stage": st}
    if n_samples:
        q10 = np.zeros((N, k), dtype="float32")
        q90 = np.zeros((N, k), dtype="float32")
        any_p = np.zeros(N, dtype="float32")
    gen = torch.Generator().manual_seed(seed)
    for start in range(0, N, batch):
        xb = torch.from_numpy(X[start:start + batch])
        a, s, _ = model.rollout(xb, k)
        p[start:start + len(xb)] = torch.sigmoid(a).numpy()
        st[start:start + len(xb)] = torch.softmax(s, -1).numpy()
        if n_samples:
            rep = xb.repeat(n_samples, 1, 1)
            sa, _, _ = model.rollout(rep, k, sample=True, generator=gen)
            sp = torch.sigmoid(sa).reshape(n_samples, len(xb), k)
            q10[start:start + len(xb)] = torch.quantile(sp, 0.1, dim=0).numpy()
            q90[start:start + len(xb)] = torch.quantile(sp, 0.9, dim=0).numpy()
            any_p[start:start + len(xb)] = sp.max(dim=2).values.mean(0).numpy()
    if n_samples:
        out.update(q10=q10, q90=q90, any=any_p)
    else:
        out["any"] = p.max(axis=1)
    return out


# ---------------------------------------------------------------------------
# Baseline
# ---------------------------------------------------------------------------


def flatten(X: np.ndarray) -> np.ndarray:
    """Baseline input: the same window sequence, flattened (seq_len * n_features)."""
    return X.reshape(len(X), -1)


class HorizonBaseline:
    """One logistic regression per forecast step, plus one for 'any attack within K'.

    Same inputs as the world model (the flattened context), no temporal structure.
    """

    def __init__(self, seed: int = 42):
        self.seed = seed
        self.step_models: list[LogisticRegression | float] = []
        self.any_model: LogisticRegression | float = 0.0

    def _fit(self, X, y):
        keep = ~np.isnan(y)
        y = y[keep].astype(int)
        if len(np.unique(y)) < 2:
            return float(y.mean()) if len(y) else 0.0  # constant fallback when a step has one class
        clf = LogisticRegression(class_weight="balanced", max_iter=3000, C=1.0, random_state=self.seed)
        return clf.fit(flatten(X[keep]), y)

    def fit(self, X, FY):
        self.step_models = [self._fit(X, FY[:, j]) for j in range(FY.shape[1])]
        self.any_model = self._fit(X, any_within(FY))
        return self

    @staticmethod
    def _predict(m, Xf):
        if isinstance(m, float):
            return np.full(len(Xf), m, dtype="float32")
        return m.predict_proba(Xf)[:, 1].astype("float32")

    def predict(self, X) -> dict:
        Xf = flatten(X) if len(X) else np.zeros((0, 1))
        if len(X) == 0:
            k = len(self.step_models)
            return {"p": np.zeros((0, k), dtype="float32"), "any": np.zeros(0, dtype="float32")}
        return {"p": np.stack([self._predict(m, Xf) for m in self.step_models], 1), "any": self._predict(self.any_model, Xf)}


def any_within(FY: np.ndarray) -> np.ndarray:
    """1 if any of the K future windows is an attack window; NaN if unknown and no attack seen."""
    has_attack = np.nansum(FY == 1, axis=1) > 0
    all_known = ~np.isnan(FY).any(axis=1)
    return np.where(has_attack, 1.0, np.where(all_known, 0.0, np.nan)).astype("float32")


# ---------------------------------------------------------------------------
# Thresholds and metrics
# ---------------------------------------------------------------------------


def tune_threshold(y: np.ndarray, scores: np.ndarray) -> tuple[float, str]:
    """Pick the F1-maximising threshold on validation data; 0.5 if that is impossible."""
    y = np.asarray(y).astype(int)
    if len(y) == 0 or y.sum() == 0 or y.sum() == len(y):
        return 0.5, "default 0.5 (validation split lacks one of the classes)"
    precision, recall, thresholds = precision_recall_curve(y, scores)
    f1 = 2 * precision * recall / np.clip(precision + recall, 1e-12, None)
    best = int(np.argmax(f1[:-1]))
    return float(thresholds[best]), "max F1 on validation split"


def binary_metrics(y: np.ndarray, scores: np.ndarray, threshold: float) -> dict:
    y = np.asarray(y).astype(int)
    pred = (np.asarray(scores) >= threshold).astype(int)
    tn, fp, fn, tp = confusion_matrix(y, pred, labels=[0, 1]).ravel()
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    fpr = fp / (fp + tn) if fp + tn else 0.0
    both = 0 < y.sum() < len(y)
    return {
        "precision": round(float(precision), 4),
        "recall": round(float(recall), 4),
        "f1": round(float(f1), 4),
        "false_positive_rate": round(float(fpr), 4),
        "average_precision": round(float(average_precision_score(y, scores)), 4) if both else None,
        "threshold": round(float(threshold), 4),
        "tp": int(tp), "fp": int(fp), "tn": int(tn), "fn": int(fn),
        "n": int(len(y)), "positives": int(y.sum()),
    }
