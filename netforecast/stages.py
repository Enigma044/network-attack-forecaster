"""Map dataset attack labels to coarse attack stages.

The mapping is deliberately conservative: a label only gets a stage when the
dataset documentation describes the traffic well enough to justify it. Labels
that do not fit the five stages used here (e.g. DoS/DDoS, which is "Impact")
stay unmapped instead of being forced into a stage. No label in CIC-IDS-2018
supports "Exfiltration", so that stage is never assigned from these datasets.
"""

from __future__ import annotations

from dataclasses import dataclass

STAGES = [
    "Reconnaissance",
    "Initial Access",
    "Lateral Movement",
    "Command and Control",
    "Exfiltration",
]


@dataclass(frozen=True)
class StageMapping:
    stage: str | None
    confidence: str  # "medium" | "low" | "n/a"
    rationale: str


# Ordered (substring, mapping) rules applied to the lower-cased label.
# DoS rules come first so "DDoS"/"DoS" labels never fall through to another rule.
_RULES: list[tuple[tuple[str, ...], StageMapping]] = [
    (
        ("ddos", "dos attack", "dos-", "hulk", "goldeneye", "slowloris", "slowhttptest", "loic", "hoic"),
        StageMapping(None, "n/a", "Denial of service is an Impact activity, outside the five stages used here."),
    ),
    (
        ("portscan", "port scan", "scan"),
        StageMapping("Reconnaissance", "medium", "Port scanning of target hosts from outside (CIC-IDS-2017 PortScan)."),
    ),
    (
        ("infilt",),
        StageMapping(
            "Lateral Movement",
            "low",
            "CIC-IDS-2018 infiltration traffic is mostly internal sweeps/port scans from an already "
            "compromised host; this precedes lateral movement (ATT&CK 'Discovery' is closer but not in the stage set).",
        ),
    ),
    (
        ("brute", "patator", "ftp-", "ssh-"),
        StageMapping("Initial Access", "medium", "Password guessing against exposed FTP/SSH/web login services."),
    ),
    (
        ("sql injection", "sqli", "xss", "web attack"),
        StageMapping("Initial Access", "medium", "Exploitation attempts against a public-facing web application."),
    ),
    (
        ("bot",),
        StageMapping("Command and Control", "medium", "Botnet (Ares/Zeus in CIC data) traffic between infected hosts and the controller."),
    ),
]

_BENIGN = StageMapping(None, "n/a", "Benign traffic.")
_UNKNOWN = StageMapping(None, "n/a", "Label not recognised; no stage assigned.")


def map_label(label: object) -> StageMapping:
    """Return the stage mapping for one dataset label."""
    if label is None or (isinstance(label, float) and label != label):
        return _UNKNOWN
    text = str(label).strip().lower()
    if text in ("benign", "normal", "background"):
        return _BENIGN
    for needles, mapping in _RULES:
        if any(n in text for n in needles):
            return mapping
    return _UNKNOWN


def stage_index(stage: str | None) -> int:
    """Index into STAGES, or -100 (PyTorch ignore_index) for no stage."""
    return STAGES.index(stage) if stage in STAGES else -100


def mapping_table() -> list[dict]:
    """Documentation-friendly view of the label→stage rules."""
    rows = []
    for needles, m in _RULES:
        rows.append(
            {
                "label contains": ", ".join(needles),
                "stage": m.stage or "(unmapped)",
                "confidence": m.confidence,
                "rationale": m.rationale,
            }
        )
    return rows
