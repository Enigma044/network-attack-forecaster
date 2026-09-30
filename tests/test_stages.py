import pytest

from netforecast.stages import STAGES, map_label, stage_index


@pytest.mark.parametrize(
    "label, stage",
    [
        ("Benign", None),
        ("BENIGN", None),
        ("FTP-BruteForce", "Initial Access"),
        ("SSH-Bruteforce", "Initial Access"),
        ("Brute Force -Web", "Initial Access"),
        ("Brute Force -XSS", "Initial Access"),
        ("SQL Injection", "Initial Access"),
        ("Bot", "Command and Control"),
        ("Infilteration", "Lateral Movement"),
        ("PortScan", "Reconnaissance"),
        ("DoS attacks-Hulk", None),
        ("DoS attacks-SlowHTTPTest", None),
        ("DDOS attack-HOIC", None),
        ("DDoS attacks-LOIC-HTTP", None),
        ("something new", None),
        (None, None),
    ],
)
def test_label_mapping(label, stage):
    assert map_label(label).stage == stage


def test_low_confidence_is_flagged():
    assert map_label("Infilteration").confidence == "low"


def test_exfiltration_never_assigned_from_cic_labels():
    cic2018 = ["Benign", "FTP-BruteForce", "SSH-Bruteforce", "DoS attacks-GoldenEye", "DoS attacks-Slowloris",
               "DoS attacks-SlowHTTPTest", "DoS attacks-Hulk", "DDoS attacks-LOIC-HTTP", "DDOS attack-LOIC-UDP",
               "DDOS attack-HOIC", "Brute Force -Web", "Brute Force -XSS", "SQL Injection", "Infilteration", "Bot"]
    assert "Exfiltration" not in {map_label(x).stage for x in cic2018}


def test_stage_index():
    assert stage_index("Reconnaissance") == 0
    assert stage_index(None) == -100
    assert len(STAGES) == 5
