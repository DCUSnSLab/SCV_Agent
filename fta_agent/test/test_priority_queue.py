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
