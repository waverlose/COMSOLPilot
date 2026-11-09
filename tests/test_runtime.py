"""Unicode-path startup compatibility without loading a JVM."""
import sys
from types import SimpleNamespace


def test_ascii_bridge_needs_no_cache(tmp_path, monkeypatch):
    from src import runtime
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(runtime.importlib.util, "find_spec", lambda _: SimpleNamespace(origin=str(tmp_path / "_jpype.pyd")))
    assert runtime.prepare_native_bridge() is None


def test_unicode_bridge_is_cached_without_moving_project(tmp_path, monkeypatch):
    from src import runtime
    source = tmp_path / "中文项目" / "_jpype.pyd"
    source.parent.mkdir()
    source.write_bytes(b"test-native-bridge")
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(sys, "path", list(sys.path))
    monkeypatch.setattr(runtime.importlib.util, "find_spec", lambda _: SimpleNamespace(origin=str(source)))
    monkeypatch.setattr(runtime.tempfile, "gettempdir", lambda: str(tmp_path))
    cached = runtime.prepare_native_bridge()
    assert cached.isascii()
    assert runtime.prepare_native_bridge() == cached
    assert source.read_bytes() == b"test-native-bridge"
    from pathlib import Path
    assert Path(cached).read_bytes() == source.read_bytes()
    assert sys.path[0] == str(Path(cached).parent)
    source.write_bytes(b"updated-native-bridge")
    assert runtime.prepare_native_bridge() != cached


def test_absent_bridge_does_not_create_cache(monkeypatch):
    from src import runtime
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(runtime.importlib.util, "find_spec", lambda _: None)
    assert runtime.prepare_native_bridge() is None


def test_non_windows_does_not_modify_module_lookup(monkeypatch):
    from src import runtime
    monkeypatch.setattr(sys, "platform", "linux")
    assert runtime.prepare_native_bridge() is None
