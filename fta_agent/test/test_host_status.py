import json
from types import SimpleNamespace

from fta_agent.observability import host_status as hs

ROUTE = """Iface\tDestination\tGateway \tFlags
wwan0\t00000000\t0100A8C0\t0003
wwan0\t0000FEA9\t00000000\t0001
"""


def test_default_iface():
    assert hs.default_iface(ROUTE) == "wwan0"
    assert hs.default_iface("Iface\tDestination\neth0\t0000FEA9\n") is None


def test_parse_mmcli_rssi_prefers_lte_and_skips_missing():
    doc = {"modem": {"signal": {"5g": {"rsrp": "-90.00"}, "lte": {"rssi": "-65.00"},
                                "gsm": {"rssi": "--"}}}}
    assert hs.parse_mmcli_rssi(doc) == -65.0
    assert hs.parse_mmcli_rssi({"modem": {"signal": {"lte": {"rssi": "--"}}}}) is None


def test_net_has_no_rssi_key_without_modem(monkeypatch):
    monkeypatch.setattr(hs, "run", lambda cmd: json.dumps({"modem-list": []}))
    assert "rssi_dbm" not in hs.collect_net()


def test_parse_chronyc():
    out = "C0A80001,192.168.0.1,3,1700000000.1,0.000012345,-0.000003,0.00001,1.2,0.0,0.01,0.002,0.0005,64.0,Normal\n"
    assert hs.parse_chronyc(out) == {"synced": True, "offset_ms": 0.012, "source": "192.168.0.1"}
    assert hs.parse_chronyc(out.replace("Normal", "Not synchronised"))["synced"] is False


def test_parse_tegrastats():
    line = "RAM 3000/7000MB CPU [5%@1200] GR3D_FREQ 37% cpu@45C"
    assert hs.parse_tegrastats(line) == 37.0
    assert hs.parse_tegrastats("RAM 3000/7000MB") is None


def test_cpu_temp_uses_cpu_sensor_only():
    t = lambda v: SimpleNamespace(current=v)  # noqa: E731
    temps = {"nvme": [t(80.0)], "k10temp": [t(60.0), t(65.0)]}
    assert hs.cpu_temp(temps) == 65.0
    assert hs.cpu_temp({"nvme": [t(80.0)]}) is None


def _health(mode="session", alive=True):
    return json.dumps({"ts": 1000.0, "mode": mode, "session": "20261028_s1",
                       "recorder": {"alive": alive}, "bag": {"bytes": 123}, "elapsed_sec": 40.0})


def test_logging_status_recording():
    assert hs.logging_status(_health(), 1.0) == {
        "recording": True, "session_id": "20261028_s1", "bytes": 123, "started_at": 960.0}


def test_logging_status_not_recording():
    assert hs.logging_status(None, None) == {"recording": False}
    assert hs.logging_status(_health(), 10.0) == {"recording": False}          # 오래됨
    assert hs.logging_status(_health(mode="preview"), 1.0) == {"recording": False}
    assert hs.logging_status(_health(alive=False), 1.0) == {"recording": False}


def test_collector_failure_leaves_none(monkeypatch):
    def boom():
        raise OSError("no /proc")
    monkeypatch.setattr(hs, "collect_net", boom)
    c = hs.HostStatusCollector(interval_sec=10)
    c._safe("net", hs.collect_net)
    assert c.snapshot()["net"] is None
