from fta_agent.core.priority_queue import PriorityOutQueue


def test_priority_ordering():
    q = PriorityOutQueue()
    q.push("l", "low")
    q.push("c", "critical")
    q.push("n", "normal")
    q.push("h", "high")
    order = [q.pop(timeout=0.1) for _ in range(4)]
    assert order == [("critical", "c"), ("high", "h"), ("normal", "n"), ("low", "l")]


def test_pop_timeout_returns_none():
    q = PriorityOutQueue()
    assert q.pop(timeout=0.05) is None


def test_overflow_drops_oldest():
    q = PriorityOutQueue(maxlen_per_priority=2)
    q.push(1, "low")
    q.push(2, "low")
    q.push(3, "low")
    assert q.dropped["low"] == 1
    assert q.pop(timeout=0.1) == ("low", 2)
    assert q.pop(timeout=0.1) == ("low", 3)


def test_high_conflates_same_key_on_overflow():
    q = PriorityOutQueue(maxlen_per_priority=2)
    q.push("odom_v1", "high", conflate_key="odom")
    q.push("gps_v1", "high", conflate_key="gps")
    q.push("odom_v2", "high", conflate_key="odom")  # 포화 → odom 항목 교체
    assert q.conflated["high"] == 1
    assert q.dropped["high"] == 0
    assert q.pop(timeout=0.1) == ("high", "odom_v2")
    assert q.pop(timeout=0.1) == ("high", "gps_v1")


def test_high_without_matching_key_drops_oldest():
    q = PriorityOutQueue(maxlen_per_priority=1)
    q.push("a", "high", conflate_key="p1")
    q.push("b", "high", conflate_key="p2")  # 같은 key 없음 → 오래된 것 드롭
    assert q.dropped["high"] == 1
    assert q.pop(timeout=0.1) == ("high", "b")
