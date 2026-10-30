"""Database path safety checks; never open the designated protected database."""
import os
import sqlite3
from pathlib import Path

import pytest

from app import store


@pytest.mark.parametrize("variant", ["absolute", "normalized", "parent-traversal", "relative", "slash-and-case"])
def test_protected_database_path_is_rejected_before_database_io(monkeypatch, variant):
    protected = store.DATA_DIR / store.PROTECTED_DATABASE_NAME
    if variant == "absolute":
        configured = str(protected)
    elif variant == "normalized":
        configured = str(store.DATA_DIR / "unused" / ".." / store.PROTECTED_DATABASE_NAME)
    elif variant == "parent-traversal":
        configured = str(store.DATA_DIR.parent / store.DATA_DIR.name / "nested" / ".." / store.PROTECTED_DATABASE_NAME)
    else:
        configured = os.path.relpath(protected, Path.cwd())
        if variant == "slash-and-case":
            configured = str(protected).replace("\\", "/").lower()

    calls = []
    original_resolve = Path.resolve
    protected_key = os.path.normcase(os.path.abspath(os.path.normpath(str(protected))))
    def guarded_resolve(path, *args, **kwargs):
        if os.path.normcase(os.path.abspath(os.path.normpath(str(path)))) == protected_key:
            calls.append("resolve_protected")
            raise AssertionError("protected target reached path resolution")
        return original_resolve(path, *args, **kwargs)

    monkeypatch.setenv("HACKATHON_DB_PATH", configured)
    monkeypatch.setattr(sqlite3, "connect", lambda *a, **k: calls.append("connect"))
    monkeypatch.setattr(Path, "is_file", lambda *a, **k: calls.append("is_file"))
    monkeypatch.setattr(Path, "mkdir", lambda *a, **k: calls.append("mkdir"))
    monkeypatch.setattr(Path, "resolve", guarded_resolve)

    with pytest.raises(ValueError):
        store.database_path()
    with pytest.raises(store.DatabaseUnavailable):
        with store.connect():
            pass
    with pytest.raises(ValueError):
        store.initialize_database()
    assert calls == []
