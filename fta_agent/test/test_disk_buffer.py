from fta_agent.core.disk_buffer import DiskBuffer


def test_event_append_and_drain_in_order(tmp_path):
    buf = DiskBuffer(tmp_path, max_disk_mb=10)
    for i in range(5):
        buf.append_event("estop", "event", "critical", f"e{i}".encode())
    sent = []
    n, done = buf.drain(lambda r: sent.append(r["d"]) or True)
    assert done and n == 5
    assert sent == [b"e0", b"e1", b"e2", b"e3", b"e4"]
    assert buf.pending()["event_segments"] == 0


def test_state_keeps_latest_only(tmp_path):
    buf = DiskBuffer(tmp_path, max_disk_mb=10)
    for i in range(10):
        buf.put_latest_state("odom", "state", "high", f"s{i}".encode())
    sent = []
    n, done = buf.drain(lambda r: sent.append(r["d"]) or True)
    assert done and n == 1
    assert sent == [b"s9"]  # 최신값만 (FR-5.4)


def test_drain_stops_on_failure_and_preserves(tmp_path):
    buf = DiskBuffer(tmp_path, max_disk_mb=10)
    for i in range(3):
        buf.append_event("estop", "event", "critical", f"e{i}".encode())
    n, done = buf.drain(lambda r: False)  # 전송 실패 상황
    assert not done and n == 0
    assert buf.pending()["event_segments"] == 1  # 세그먼트 보존
    sent = []
    n2, done2 = buf.drain(lambda r: sent.append(r["d"]) or True)
    assert done2 and n2 == 3


def test_restart_recovery(tmp_path):
    buf1 = DiskBuffer(tmp_path, max_disk_mb=10)
    buf1.append_event("estop", "event", "critical", b"before_crash")
    buf1.put_latest_state("odom", "state", "high", b"last_state")
    buf1.close()

    buf2 = DiskBuffer(tmp_path, max_disk_mb=10)  # 재시작 시뮬레이션
    sent = []
    n, done = buf2.drain(lambda r: sent.append((r["p"], r["d"])) or True)
    assert done and n == 2
    assert ("estop", b"before_crash") in sent
    assert ("odom", b"last_state") in sent


def test_disk_cap_drops_oldest_segment(tmp_path):
    buf = DiskBuffer(tmp_path, max_disk_mb=1, segment_max_bytes=256 * 1024)
    payload = bytes(64 * 1024)
    for i in range(32):  # 2MB > 1MB 상한
        buf.append_event("bulk_event", "event", "critical", payload)
    assert buf.stats["segments_dropped"] > 0
    assert buf.pending()["bytes"] <= 1024 * 1024 + 300 * 1024  # 상한 근처 유지


def test_truncated_record_ignored(tmp_path):
    buf = DiskBuffer(tmp_path, max_disk_mb=10)
    buf.append_event("e", "event", "critical", b"complete")
    buf.close()
    seg = next((tmp_path / "events").glob("seg_*.log"))
    with open(seg, "ab") as f:
        f.write(b"\x00\x00\x10\x00garbage")  # 길이 헤더만 있고 본문 잘림
    buf2 = DiskBuffer(tmp_path, max_disk_mb=10)
    sent = []
    n, done = buf2.drain(lambda r: sent.append(r["d"]) or True)
    assert done and sent == [b"complete"]
