"""Load JPype's native bridge from an ASCII path on Windows."""
from __future__ import annotations

import hashlib
import importlib.util
import os
import shutil
import sys
import tempfile
from pathlib import Path


def prepare_native_bridge():
    """Cache only the installed native extension; never move the user's project."""
    if sys.platform != "win32":
        return None
    spec = importlib.util.find_spec("_jpype")
    if spec is None or spec.origin is None or spec.origin.isascii():
        return None
    source = Path(spec.origin)
    root = Path(tempfile.gettempdir())
    if not str(root).isascii():
        root = Path(os.environ.get("SystemRoot", "C:/Windows")) / "Temp"
    if not str(root).isascii():
        raise RuntimeError("JPype needs a writable ASCII temporary directory.")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()[:20]
    directory = root / "comsolpilot-native" / digest
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / source.name
    if not target.is_file():
        descriptor, temporary = tempfile.mkstemp(dir=directory, suffix=".tmp")
        os.close(descriptor)
        try:
            shutil.copyfile(source, temporary)
            try:
                os.replace(temporary, target)
            except PermissionError:
                if not target.is_file():
                    raise
        finally:
            Path(temporary).unlink(missing_ok=True)
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))
    return str(target)
