import io

import pandas as pd

from netforecast.schema import REQUIRED_COLUMNS, load_flows

HEADER = "Dst Port,Protocol,Timestamp,Flow Duration,Tot Fwd Pkts,Tot Bwd Pkts,Label\n"


def csv(text: str) -> io.BytesIO:
    return io.BytesIO(text.encode())


def test_valid_cic2018_rows():
    flows, report = load_flows(csv(HEADER + "22,6,14/02/2018 08:31:01,100,3,2,Benign\n80,6,14/02/2018 08:32:01,5,1,0,FTP-BruteForce\n"), "a.csv")
    assert report.ok, report.errors
    assert report.n_rows_valid == 2
    assert report.has_labels
    assert list(flows["is_attack"]) == [0.0, 1.0]
    assert flows["Timestamp"].iloc[0] == pd.Timestamp("2018-02-14 08:31:01")  # day-first
    assert report.data_kind == "external"


def test_missing_required_column_is_an_error():
    _, report = load_flows(csv("Dst Port,Protocol,Timestamp\n22,6,14/02/2018 08:31:01\n"), "a.csv")
    assert not report.ok
    assert "Flow Duration" in report.errors[0]


def test_empty_file():
    _, report = load_flows(csv(""), "empty.csv")
    assert not report.ok and "empty" in report.errors[0].lower()


def test_header_only():
    _, report = load_flows(csv(HEADER), "h.csv")
    assert not report.ok and "no data rows" in report.errors[0]


def test_ctu13_is_rejected_with_explanation():
    text = "StartTime,Dur,Proto,SrcAddr,Sport,Dir,DstAddr,Dport,State,sTos,dTos,TotPkts,TotBytes,SrcBytes,Label\n"
    _, report = load_flows(csv(text + "2011/08/10 09:46:53,1.0,tcp,1.1.1.1,1,->,2.2.2.2,80,S,0,0,1,60,60,flow=Background\n"), "c.binetflow")
    assert not report.ok and "CTU-13" in report.errors[0]


def test_mostly_malformed_rows_rejected():
    rows = "22,6,not-a-date,1,1,1,Benign\n" * 5 + "22,6,14/02/2018 08:31:01,1,1,1,Benign\n"
    _, report = load_flows(csv(HEADER + rows), "bad.csv")
    assert not report.ok and "malformed" in report.errors[0]


def test_repeated_header_and_bad_rows_dropped_with_warnings():
    rows = (
        "22,6,14/02/2018 08:31:01,100,3,2,Benign\n"
        + HEADER
        + "22,6,14/02/2018 08:31:05,abc,3,2,Benign\n"
        + "443,6,14/02/2018 08:31:09,-5,3,2,Benign\n"
    )
    flows, report = load_flows(csv(HEADER + rows), "r.csv")
    assert report.ok
    assert len(flows) == 2
    joined = " ".join(report.warnings)
    assert "repeated header" in joined and "non-numeric" in joined and "negative" in joined
    assert (flows["Flow Duration"] >= 0).all()


def test_cic2017_aliases_and_whitespace_headers():
    text = " Destination Port, Protocol, Timestamp, Flow Duration, Total Fwd Packets, Total Backward Packets, Label\n"
    flows, report = load_flows(csv(text + "80,6,3/7/2017 8:55,10,1,1,BENIGN\n"), "x.csv")
    assert report.ok, report.errors
    assert set(REQUIRED_COLUMNS) <= set(flows.columns)
    assert flows["is_attack"].iloc[0] == 0.0


def test_labels_optional():
    text = HEADER.replace(",Label", "")
    flows, report = load_flows(csv(text + "22,6,14/02/2018 08:31:01,100,3,2\n"), "n.csv")
    assert report.ok and not report.has_labels
    assert flows["is_attack"].isna().all()


def test_synthetic_marker_detected(synthetic_dir):
    path = sorted(synthetic_dir.glob("*.csv"))[0]
    _, report = load_flows(path)
    assert report.ok and report.data_kind == "synthetic"
    assert not report.optional_missing


CIC2018_HEADER = (
    "Dst Port,Protocol,Timestamp,Flow Duration,Tot Fwd Pkts,Tot Bwd Pkts,TotLen Fwd Pkts,TotLen Bwd Pkts,"
    "Fwd Pkt Len Max,Fwd Pkt Len Min,Fwd Pkt Len Mean,Fwd Pkt Len Std,Bwd Pkt Len Max,Bwd Pkt Len Min,"
    "Bwd Pkt Len Mean,Bwd Pkt Len Std,Flow Byts/s,Flow Pkts/s,Flow IAT Mean,Flow IAT Std,Flow IAT Max,"
    "Flow IAT Min,Fwd IAT Tot,Fwd IAT Mean,Fwd IAT Std,Fwd IAT Max,Fwd IAT Min,Bwd IAT Tot,Bwd IAT Mean,"
    "Bwd IAT Std,Bwd IAT Max,Bwd IAT Min,Fwd PSH Flags,Bwd PSH Flags,Fwd URG Flags,Bwd URG Flags,"
    "Fwd Header Len,Bwd Header Len,Fwd Pkts/s,Bwd Pkts/s,Pkt Len Min,Pkt Len Max,Pkt Len Mean,Pkt Len Std,"
    "Pkt Len Var,FIN Flag Cnt,SYN Flag Cnt,RST Flag Cnt,PSH Flag Cnt,ACK Flag Cnt,URG Flag Cnt,CWE Flag Count,"
    "ECE Flag Cnt,Down/Up Ratio,Pkt Size Avg,Fwd Seg Size Avg,Bwd Seg Size Avg,Fwd Byts/b Avg,Fwd Pkts/b Avg,"
    "Fwd Blk Rate Avg,Bwd Byts/b Avg,Bwd Pkts/b Avg,Bwd Blk Rate Avg,Subflow Fwd Pkts,Subflow Fwd Byts,"
    "Subflow Bwd Pkts,Subflow Bwd Byts,Init Fwd Win Byts,Init Bwd Win Byts,Fwd Act Data Pkts,Fwd Seg Size Min,"
    "Active Mean,Active Std,Active Max,Active Min,Idle Mean,Idle Std,Idle Max,Idle Min,Label"
)


def test_full_cic2018_header_layout():
    cols = CIC2018_HEADER.split(",")
    assert len(cols) == 80

    def row(ts, label):
        values = {c: "0" for c in cols}
        values.update({"Dst Port": "22", "Protocol": "6", "Timestamp": ts, "Flow Duration": "1500",
                       "Tot Fwd Pkts": "4", "Tot Bwd Pkts": "3", "Flow Byts/s": "Infinity", "Label": label})
        return ",".join(values[c] for c in cols)

    text = "\n".join([CIC2018_HEADER, row("14/02/2018 08:31:01", "Benign"), row("14/02/2018 08:31:02", "SSH-Bruteforce")])
    flows, report = load_flows(csv(text + "\n"), "Wednesday-14-02-2018_TrafficForML_CICFlowMeter.csv")
    assert report.ok, report.errors
    # every optional column except the IP addresses exists in the public 2018 files
    assert set(report.optional_missing) == {"Src IP", "Dst IP"}
    assert list(flows["is_attack"]) == [0.0, 1.0]


def test_cic2018_twelve_hour_clock_and_epoch_rows_fixed():
    rows = (
        "22,6,14/02/2018 10:00:00,1,1,1,FTP-BruteForce\n"
        "22,6,14/02/2018 02:30:00,1,1,1,SSH-Bruteforce\n"   # 14:30 written without PM
        "22,6,12/01/1970 05:00:00,1,1,1,Benign\n"
        + "22,6,14/02/2018 09:00:00,1,1,1,Benign\n" * 3
    )
    flows, report = load_flows(csv(HEADER + rows), "Wednesday-14-02-2018.csv")
    assert report.ok
    ssh = flows.loc[flows["Label"] == "SSH-Bruteforce", "Timestamp"].iloc[0]
    assert ssh == pd.Timestamp("2018-02-14 14:30:00")
    assert (flows["Timestamp"].dt.year == 2018).all()
    joined = " ".join(report.warnings)
    assert "12-hour clock" in joined and "epoch-era" in joined


def test_24_hour_clock_left_alone():
    rows = "22,6,14/02/2018 02:00:00,1,1,1,Benign\n22,6,14/02/2018 15:00:00,1,1,1,Benign\n"
    flows, report = load_flows(csv(HEADER + rows), "a.csv")
    assert list(flows["Timestamp"].dt.hour) == [2, 15]
    assert not any("12-hour" in w for w in report.warnings)
