import json
import os

import psutil

from pawlock.instance import InstanceGuard, find_running, stop_running


def test_acquire_and_release(tmp_path):
    path = tmp_path / "pawlock.pid"
    guard = InstanceGuard(path)
    assert guard.acquire()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["pid"] == os.getpid()
    assert find_running(path) is None  # it's us, not "another" PawLock
    guard.release()
    assert not path.exists()


def test_recycled_pid_is_not_mistaken_for_pawlock(tmp_path):
    path = tmp_path / "pawlock.pid"
    parent = psutil.Process().parent()
    path.write_text(json.dumps({"pid": parent.pid, "created": parent.create_time() - 1000}), encoding="utf-8")
    assert find_running(path) is None


def test_live_instance_is_found(tmp_path):
    path = tmp_path / "pawlock.pid"
    parent = psutil.Process().parent()
    path.write_text(json.dumps({"pid": parent.pid, "created": parent.create_time()}), encoding="utf-8")
    found = find_running(path)
    assert found is not None and found.pid == parent.pid
    assert InstanceGuard(path).acquire() is False


def test_garbage_pid_files(tmp_path):
    path = tmp_path / "pawlock.pid"
    for content in ("", "not json", "[]", '{"pid": "x"}', '{"pid": 999999999, "created": 0}'):
        path.write_text(content, encoding="utf-8")
        assert find_running(path) is None


def test_stop_when_nothing_is_running(tmp_path):
    assert stop_running(tmp_path / "missing.pid") == "not-running"
