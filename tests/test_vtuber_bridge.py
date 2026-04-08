"""
Smoke test for VTuber Bridge async fixes.

Validates:
  1. Bridge loop thread starts and is alive
  2. No "Future attached to a different loop" errors
  3. Thread-safety: sync methods callable from background threads
  4. Async-safety: sync methods callable from inside asyncio.run()
  5. Graceful failure when VTuber Studio is not running
  6. No use of asyncio.get_event_loop() + run_until_complete()

Run:
    cd E:/Zelius
    python tests/test_vtuber_bridge.py
"""

import asyncio
import inspect
import re
import sys
import threading
import time
import os

# Allow importing from project root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from integrations.vtuber_bridge import VTuberBridge, _BridgeLoop, Expression


# ===========================================================================
# Helpers
# ===========================================================================

class _Result:
    """Tiny container for thread results."""
    def __init__(self):
        self.value = None
        self.error = None


def run_in_thread(fn):
    """Run *fn* in a background thread and return (value, error)."""
    r = _Result()

    def wrapper():
        try:
            r.value = fn()
        except Exception as e:
            r.error = e

    t = threading.Thread(target=wrapper)
    t.start()
    t.join(timeout=15)
    return r


# ===========================================================================
# Tests
# ===========================================================================

def test_bridge_loop_starts():
    """_BridgeLoop thread starts and is alive."""
    loop = _BridgeLoop()
    loop.start()
    time.sleep(0.2)
    assert loop.running, "Bridge loop should be running after start()"
    loop.stop()
    print("  PASS: Bridge loop starts and is alive")


def test_bridge_loop_runs_coro():
    """Can submit a simple coroutine to the bridge loop."""
    loop = _BridgeLoop()
    loop.start()

    async def add(a, b):
        return a + b

    result = loop.run_coro(add(3, 4))
    assert result == 7, f"Expected 7, got {result}"
    loop.stop()
    print("  PASS: Bridge loop runs coroutines correctly")


def test_bridge_init():
    """VTuberBridge initializes and its loop is alive."""
    bridge = VTuberBridge()
    assert bridge._loop.running, "Bridge loop should be running after init"
    bridge.shutdown()
    print("  PASS: VTuberBridge initializes with running loop")


def test_connect_fails_gracefully():
    """connect() fails gracefully when VTuber Studio is not running."""
    bridge = VTuberBridge(port=19999)  # unlikely to be listening
    result = bridge.connect()
    assert result is False, "connect() should return False when nothing is listening"
    assert bridge.is_connected() is False
    bridge.shutdown()
    print("  PASS: connect() fails gracefully (no crash)")


def test_connect_and_auth_fails_gracefully():
    """connect_and_auth() fails gracefully."""
    bridge = VTuberBridge(port=19999)
    result = bridge.connect_and_auth()
    assert result is False
    bridge.shutdown()
    print("  PASS: connect_and_auth() fails gracefully")


def test_thread_safety():
    """Sync methods are callable from a background thread without loop errors."""
    bridge = VTuberBridge(port=19999)

    r = run_in_thread(lambda: bridge.connect())
    assert r.error is None, f"Thread call raised: {r.error}"
    assert r.value is False  # not connected, but no crash

    r2 = run_in_thread(lambda: bridge.get_status())
    assert r2.error is None, f"get_status in thread raised: {r2.error}"
    assert isinstance(r2.value, dict)

    bridge.shutdown()
    print("  PASS: Sync methods are thread-safe (no loop mismatch)")


def test_async_safety():
    """Sync methods are callable from inside asyncio.run() without 'loop already running'."""
    bridge = VTuberBridge(port=19999)

    async def call_from_async():
        # This would crash with the old code:
        #   RuntimeError: This event loop is already running
        result = bridge.connect()
        return result

    # asyncio.run() creates its own loop; bridge.connect() must NOT call
    # run_until_complete on that loop.
    result = asyncio.run(call_from_async())
    assert result is False  # not connected, but no crash

    bridge.shutdown()
    print("  PASS: Sync methods work inside asyncio.run() (no nested loop crash)")


def test_status_includes_new_fields():
    """get_status() includes reconnection and bridge loop fields."""
    bridge = VTuberBridge()
    status = bridge.get_status()
    assert "reconnecting" in status, "Status should include 'reconnecting' field"
    assert "bridge_loop_alive" in status, "Status should include 'bridge_loop_alive'"
    assert status["bridge_loop_alive"] is True
    bridge.shutdown()
    print("  PASS: get_status() includes new diagnostic fields")


def test_no_run_until_complete_in_source():
    """Source code must not contain run_until_complete (the root cause)."""
    source_path = os.path.join(
        os.path.dirname(__file__), "..", "integrations", "vtuber_bridge.py"
    )
    with open(source_path, "r", encoding="utf-8") as f:
        source = f.read()

    matches = [
        m for m in re.finditer(r"run_until_complete", source)
    ]
    assert len(matches) == 0, (
        f"Found {len(matches)} occurrences of 'run_until_complete' in vtuber_bridge.py. "
        "This pattern was the root cause and should be eliminated."
    )
    print("  PASS: No run_until_complete in vtuber_bridge.py")


def test_no_get_event_loop_in_bridge():
    """Source should not use asyncio.get_event_loop() (the other root cause)."""
    source_path = os.path.join(
        os.path.dirname(__file__), "..", "integrations", "vtuber_bridge.py"
    )
    with open(source_path, "r", encoding="utf-8") as f:
        source = f.read()

    # Allow it in comments/docstrings, but not in actual code
    lines = source.split("\n")
    code_uses = []
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if stripped.startswith("#") or stripped.startswith('"""') or stripped.startswith("'"):
            continue
        if "get_event_loop()" in line:
            code_uses.append((i, line.strip()))

    assert len(code_uses) == 0, (
        f"Found asyncio.get_event_loop() in code at lines: {code_uses}"
    )
    print("  PASS: No asyncio.get_event_loop() in vtuber_bridge.py")


def test_lip_sync_starts_without_connection():
    """start_lip_sync can be called even without a connection (no crash)."""
    bridge = VTuberBridge(port=19999)
    # Should not crash — lip sync loop will encounter errors and stop
    bridge.start_lip_sync()
    time.sleep(0.5)
    bridge.stop_lip_sync()
    bridge.shutdown()
    print("  PASS: start_lip_sync handles missing connection gracefully")


def test_expression_enum():
    """Expression enum is intact."""
    assert Expression.NEUTRAL == "neutral"
    assert Expression.HAPPY == "happy"
    assert Expression.TALKING == "talking"
    print("  PASS: Expression enum intact")


# ===========================================================================
# Runner
# ===========================================================================

ALL_TESTS = [
    test_bridge_loop_starts,
    test_bridge_loop_runs_coro,
    test_bridge_init,
    test_connect_fails_gracefully,
    test_connect_and_auth_fails_gracefully,
    test_thread_safety,
    test_async_safety,
    test_status_includes_new_fields,
    test_no_run_until_complete_in_source,
    test_no_get_event_loop_in_bridge,
    test_lip_sync_starts_without_connection,
    test_expression_enum,
]


def main():
    print(f"\n{'='*60}")
    print("VTuber Bridge Async Fix — Smoke Tests")
    print(f"{'='*60}\n")

    passed = 0
    failed = 0
    errors = []

    for test_fn in ALL_TESTS:
        name = test_fn.__name__
        try:
            test_fn()
            passed += 1
        except Exception as e:
            failed += 1
            errors.append((name, e))
            print(f"  FAIL: {name}: {e}")

    print(f"\n{'-'*60}")
    print(f"Results: {passed} passed, {failed} failed out of {len(ALL_TESTS)}")

    if errors:
        print("\nFailed tests:")
        for name, err in errors:
            print(f"  • {name}: {err}")

    print(f"{'='*60}\n")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
