"""차량 PC·링크·시각·버전 상태 수집 (health 확장).

ROS를 거치지 않고 에이전트가 직접 모은다 — ROS 그래프가 죽어도 health에 실린다.
외부 명령(nvidia-smi, tegrastats, mmcli, chronyc, git)은 느릴 수 있어 전용 스레드에서
수집해 캐시하고, health 타이머(rclpy executor)는 캐시만 읽는다.
값을 얻지 못하면 해당 항목은 None이고 health는 계속 나간다.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import threading
from typing import Optional

import psutil

LOGGING_STALE_SEC = 5.0  # scv_logger 감시 노드는 1초 주기 — 이보다 오래 없으면 녹화 아님
_CPU_SENSORS = ("coretemp", "k10temp", "cpu-thermal", "CPU-therm")  # x86 Intel/AMD, Jetson


def run(cmd: list[str]) -> Optional[str]:
    """명령 stdout. 명령 없음·실패·타임아웃이면 None."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=3, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r.stdout if r.returncode == 0 else None


def _num(v) -> Optional[float]:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None  # mmcli는 값이 없으면 "--"


# ---- host ----------------------------------------------------------------

def parse_tegrastats(line: str) -> Optional[float]:
    m = re.search(r"GR3D_FREQ (\d+)%", line)
    return float(m.group(1)) if m else None


def gpu_pct() -> Optional[float]:
    out = run(["nvidia-smi", "--query-gpu=utilization.gpu", "--format=csv,noheader,nounits"])
    if out is not None:  # x86 + NVIDIA (여러 장이면 최댓값)
        return max(float(x) for x in out.split())
    if shutil.which("tegrastats") is None:
        return None
    # Jetson — tegrastats는 계속 출력하므로 첫 줄만 읽고 끝낸다
    p = subprocess.Popen(["tegrastats", "--interval", "500"], stdout=subprocess.PIPE, text=True)
    line = p.stdout.readline()
    p.kill()
    p.wait()
    return parse_tegrastats(line)


def cpu_temp(temps: dict) -> Optional[float]:
    for name in _CPU_SENSORS:
        if temps.get(name):
            return max(t.current for t in temps[name])
    return None


def collect_host() -> dict:
    return {
        "cpu_pct": psutil.cpu_percent(interval=None),  # 직전 수집 이후 평균
        "mem_pct": psutil.virtual_memory().percent,
        "gpu_pct": gpu_pct(),
        "temp_c": cpu_temp(psutil.sensors_temperatures()),
        "disk_free_gb": round(shutil.disk_usage("/").free / 1024 ** 3, 1),
    }


# ---- net -----------------------------------------------------------------

def default_iface(route_text: str) -> Optional[str]:
    """/proc/net/route 에서 기본 경로(Destination 0) 인터페이스."""
    for line in route_text.splitlines()[1:]:
        f = line.split()
        if f[1] == "00000000":
            return f[0]
    return None


def parse_mmcli_rssi(doc: dict) -> Optional[float]:
    sig = doc.get("modem", {}).get("signal", {})
    for tech in ("lte", "umts", "gsm"):  # 5G NR에는 rssi가 없다 — NSA면 lte 값이 나온다
        v = _num(sig.get(tech, {}).get("rssi"))
        if v is not None:
            return v
    return None


def modem_rssi() -> Optional[float]:
    """USB LTE/5G 모뎀(ModemManager)의 RSSI. 모뎀이 없으면 None."""
    out = run(["mmcli", "-L", "-J"])
    modems = json.loads(out).get("modem-list") if out else None
    if not modems:
        return None
    out = run(["mmcli", "-m", modems[0], "--signal-get", "-J"])
    return parse_mmcli_rssi(json.loads(out)) if out else None


def collect_net() -> dict:
    with open("/proc/net/route", encoding="utf-8") as f:
        net = {"iface": default_iface(f.read())}
    rssi = modem_rssi()
    if rssi is not None:  # 모뎀이 아니면 키를 넣지 않는다
        net["rssi_dbm"] = rssi
    return net


# ---- time ----------------------------------------------------------------

def parse_chronyc(out: str) -> dict:
    """`chronyc -c tracking` CSV — [1]=기준 이름, [4]=시스템 시계 오차(s), [13]=leap 상태."""
    f = out.strip().split(",")
    return {
        "synced": f[13] != "Not synchronised",
        "offset_ms": round(float(f[4]) * 1000, 3),
        "source": f[1],
    }


def collect_time() -> Optional[dict]:
    out = run(["chronyc", "-c", "tracking"])
    if out:
        return parse_chronyc(out)
    out = run(["timedatectl", "show", "-p", "NTPSynchronized", "--value"])
    if out is not None:  # chrony가 없으면 systemd-timesyncd — 오차 값은 없다
        return {"synced": out.strip() == "yes", "offset_ms": None, "source": "timesyncd"}
    return None


# ---- version -------------------------------------------------------------

def collect_version(workspace_dir: Optional[str]) -> dict:
    from importlib.metadata import version
    out = {"agent": version("fta_agent"), "vehicle_sw": None, "git": None}
    if workspace_dir:
        # 서비스 계정(fta)이 다른 사용자 소유 저장소를 읽으면 git이 dubious ownership으로 거부한다
        git = ["git", "-c", "safe.directory=*", "-C", workspace_dir]
        desc = run(git + ["describe", "--always", "--dirty", "--tags"])
        head = run(git + ["rev-parse", "HEAD"])
        out["vehicle_sw"] = desc.strip() if desc else None
        out["git"] = head.strip() if head else None
    return out


# ---- logging (scv_logger) -------------------------------------------------

def logging_status(raw: Optional[str], age_sec: Optional[float]) -> dict:
    """scv_logger 감시 노드의 /scv_logger/health JSON → 녹화 상태.

    감시 노드는 GUI가 떠 있거나 녹화 중일 때만 발행한다 — 메시지가 없으면 녹화 아님.
    """
    if raw is None or age_sec > LOGGING_STALE_SEC:
        return {"recording": False}
    h = json.loads(raw)
    if h.get("mode") != "session" or not h.get("recorder", {}).get("alive"):
        return {"recording": False}
    return {
        "recording": True,
        "session_id": h.get("session"),
        "bytes": h.get("bag", {}).get("bytes"),
        "started_at": round(h["ts"] - h["elapsed_sec"], 1),
    }


# ---- 수집 스레드 -----------------------------------------------------------

class HostStatusCollector:
    def __init__(self, interval_sec: float, workspace_dir: Optional[str] = None):
        self._interval = interval_sec
        self._workspace_dir = workspace_dir
        self._cache: dict = {"host": None, "net": None, "time": None, "version": None}
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, name="host-status", daemon=True)
        psutil.cpu_percent(interval=None)  # 첫 호출 기준점

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def snapshot(self) -> dict:
        return dict(self._cache)  # 키별 대입만 하므로 GIL 아래 원자적

    def _safe(self, key: str, fn) -> None:
        try:
            self._cache[key] = fn()
        except Exception:  # noqa: BLE001 — 수집 실패가 health 발행을 막으면 안 된다
            self._cache[key] = None

    def _loop(self) -> None:
        self._safe("version", lambda: collect_version(self._workspace_dir))  # 기동 시 1회
        while not self._stop.is_set():
            self._safe("host", collect_host)
            self._safe("net", collect_net)
            self._safe("time", collect_time)
            self._stop.wait(self._interval)
