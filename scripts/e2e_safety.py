"""Fail-closed primitives for a future disposable Story Connect E2E runner.

This module deliberately does not launch processes, browsers, or databases.
The host runner is not safe to execute until an OS sandbox verifier is added.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import tempfile
import ctypes
from ctypes import wintypes
from uuid import uuid4


OWNER_FILE = ".story-connect-e2e-owner.json"
PROTECTED_DATABASE_NAME = ".e2e-phase34.sqlite3"
DEFAULT_DATABASE_NAME = "prototype.sqlite3"


class SafetyError(RuntimeError):
    """A required runner isolation invariant could not be established."""


class E2EWorkspace:
    """A unique workspace whose cleanup is limited to registered artifacts."""

    def __init__(self, temp_root: str | Path):
        raw_root = Path(temp_root).expanduser()
        if not raw_root.is_absolute() or ".." in raw_root.parts:
            raise SafetyError("The configured temporary root must be absolute and traversal-free.")
        if raw_root.is_symlink() or not raw_root.is_dir():
            raise SafetyError("The configured temporary root must be an existing, non-symlink directory.")
        self.temp_root = raw_root.resolve(strict=True)
        system_temp = Path(tempfile.gettempdir()).resolve(strict=True)
        if self.temp_root != system_temp and system_temp not in self.temp_root.parents:
            raise SafetyError("The configured temporary root must be inside the system temporary directory.")
        self.run_id = uuid4().hex
        self.path: Path | None = None
        self._owned: set[str] = set()
        self._identities: dict[str, tuple[int, int, int]] = {}
        self._workspace_identity: tuple[int, int, int] | None = None
        self._manifest_identity: tuple[int, int, int] | None = None
        self._handles: dict[str, int] = {}

    def _identity(self, path: Path, *, retain: bool = False) -> tuple[int, int, int]:
        if os.name == "nt":
            return self._windows_identity(path, retain=retain)
        info = path.lstat()
        if _is_reparse_point(info) or path.is_symlink():
            raise SafetyError("Reparse points and symlinks are not permitted.")
        if not info.st_ino:
            raise SafetyError("Stable filesystem identity is unavailable.")
        return info.st_dev, info.st_ino, info.st_mode

    def _windows_identity(self, path: Path, *, retain: bool) -> tuple[int, int, int]:
        class FILETIME(ctypes.Structure):
            _fields_ = [("low", wintypes.DWORD), ("high", wintypes.DWORD)]

        class BY_HANDLE_FILE_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("attributes", wintypes.DWORD), ("creation", FILETIME),
                ("access", FILETIME), ("write", FILETIME),
                ("volume", wintypes.DWORD), ("size_high", wintypes.DWORD),
                ("size_low", wintypes.DWORD), ("links", wintypes.DWORD),
                ("index_high", wintypes.DWORD), ("index_low", wintypes.DWORD),
            ]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        create_file = kernel32.CreateFileW
        create_file.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        create_file.restype = wintypes.HANDLE
        handle = create_file(str(path), 0x0080, 0x00000001, None, 3,
                             0x02000000 | 0x00200000, None)
        invalid = ctypes.c_void_p(-1).value
        if handle == invalid:
            raise SafetyError("Windows could not open a stable filesystem identity handle.")
        info = BY_HANDLE_FILE_INFORMATION()
        get_info = kernel32.GetFileInformationByHandle
        get_info.argtypes = [wintypes.HANDLE, ctypes.POINTER(BY_HANDLE_FILE_INFORMATION)]
        get_info.restype = wintypes.BOOL
        if not get_info(handle, ctypes.byref(info)):
            kernel32.CloseHandle(handle)
            raise SafetyError("Windows could not read filesystem identity information.")
        if info.attributes & 0x400:
            kernel32.CloseHandle(handle)
            raise SafetyError("Reparse points are not permitted.")
        identity = (info.volume, info.index_high, info.index_low)
        if not info.index_high and not info.index_low:
            kernel32.CloseHandle(handle)
            raise SafetyError("Windows did not provide a stable file identifier.")
        if retain:
            key = str(path)
            previous = self._handles.get(key)
            if previous is not None:
                kernel32.CloseHandle(handle)
            else:
                self._handles[key] = int(handle)
        else:
            kernel32.CloseHandle(handle)
        return identity

    def close_handles(self) -> None:
        """Release retained identity handles (no filesystem changes)."""
        if os.name == "nt" and self._handles:
            close_handle = ctypes.WinDLL("kernel32", use_last_error=True).CloseHandle
            for handle in self._handles.values():
                close_handle(wintypes.HANDLE(handle))
        self._handles.clear()

    def create(self) -> Path:
        if self.path is not None:
            raise SafetyError("This workspace has already been created.")
        path = Path(tempfile.mkdtemp(prefix=f"story-connect-e2e-{self.run_id}-", dir=self.temp_root))
        if path.parent.resolve(strict=True) != self.temp_root or path.is_symlink():
            raise SafetyError("The created workspace escaped its configured temporary root.")
        self.path = path.resolve(strict=True)
        manifest = self.path / OWNER_FILE
        with manifest.open("x", encoding="utf-8") as stream:
            json.dump({"schema": 1, "run_id": self.run_id, "workspace": str(self.path)}, stream)
        self._workspace_identity = self._identity(self.path, retain=True)
        self._manifest_identity = self._identity(manifest, retain=True)
        return self.path

    def _require_workspace(self) -> Path:
        if self.path is None:
            raise SafetyError("Create the disposable workspace first.")
        if (self.path.is_symlink() or self.path.resolve(strict=True).parent != self.temp_root
                or self._identity(self.path) != self._workspace_identity):
            raise SafetyError("The workspace identity or containment changed.")
        manifest_path = self.path / OWNER_FILE
        if self._identity(manifest_path) != self._manifest_identity:
            raise SafetyError("Workspace ownership manifest identity changed.")
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise SafetyError("Workspace ownership metadata is unavailable.") from exc
        if manifest != {"schema": 1, "run_id": self.run_id, "workspace": str(self.path)}:
            raise SafetyError("Workspace ownership metadata does not match this runner.")
        return self.path

    def path_for(self, relative: str | Path) -> Path:
        """Return a contained path after rejecting traversal and symlink components."""
        root = self._require_workspace()
        rel = Path(relative)
        if rel.is_absolute() or not rel.parts or ".." in rel.parts or any(part in ("", ".") for part in rel.parts):
            raise SafetyError("Artifact paths must be relative and traversal-free.")
        candidate = root.joinpath(rel)
        current = root
        for part in rel.parts:
            current = current / part
            if current.exists() or current.is_symlink():
                self._identity(current)
        if candidate.resolve(strict=False).parent != root and root not in candidate.resolve(strict=False).parents:
            raise SafetyError("Artifact path escapes the disposable workspace.")
        return candidate

    def database_path(self, configured: str | Path | None) -> Path:
        """Validate an explicit database filename without creating or opening it."""
        if configured is None or not str(configured).strip():
            raise SafetyError("An explicit disposable database path is required.")
        raw = Path(configured).expanduser()
        if raw.name.casefold() == PROTECTED_DATABASE_NAME.casefold():
            raise SafetyError("The protected database path is forbidden.")
        if raw.name.casefold() == DEFAULT_DATABASE_NAME.casefold():
            raise SafetyError("The default development database path is forbidden.")
        if raw.is_absolute():
            try:
                relative = raw.relative_to(self._require_workspace())
            except ValueError as exc:
                raise SafetyError("Database path must be inside this run's workspace.") from exc
        else:
            relative = raw
        candidate = self.path_for(relative)
        expected_parent = self.path_for("database")
        if candidate.parent != expected_parent or candidate.name != "e2e.sqlite3":
            raise SafetyError("Database must use the runner's dedicated database/e2e.sqlite3 path.")
        if candidate.exists():
            raise SafetyError("The disposable database path must not already exist.")
        return candidate

    def register_created_artifact(self, relative: str | Path) -> Path:
        """Register an artifact only if this runner created it exclusively."""
        path = self.path_for(relative)
        if path.exists():
            raise SafetyError("Refusing to register an artifact that already exists.")
        root = self._require_workspace()
        parent = path.parent
        missing_parents: list[Path] = []
        while parent != root and not parent.exists():
            missing_parents.append(parent)
            parent = parent.parent
        if parent != root and parent.relative_to(root).as_posix() not in self._owned:
            raise SafetyError("Artifact parent directory is not owned by this runner.")
        for directory in reversed(missing_parents):
            directory.mkdir()
            key = directory.relative_to(root).as_posix()
            self._owned.add(key)
            self._identities[key] = self._identity(directory, retain=True)
        try:
            path.mkdir() if path.suffix == "" else path.open("xb").close()
        except FileExistsError as exc:
            raise SafetyError("Artifact appeared before exclusive creation.") from exc
        key = path.relative_to(self._require_workspace()).as_posix()
        self._owned.add(key)
        self._identities[key] = self._identity(path, retain=True)
        return path

    def cleanup(self) -> None:
        """Fail closed: path-based cleanup is not race-resistant on supported hosts."""
        root = self._require_workspace()
        self._verify_complete_tree(root)
        raise SafetyError("No audited handle-relative cleanup adapter is configured.")

    def _verify_complete_tree(self, root: Path) -> None:
        """Refuse cleanup unless every current node is registered and unchanged."""
        for relative, identity in self._identities.items():
            current = self.path_for(relative)
            if self._identity(current) != identity:
                raise SafetyError("An owned artifact identity changed.")
        expected = set(self._owned)
        actual: set[str] = set()
        stack = [root]
        while stack:
            directory = stack.pop()
            for item in directory.iterdir():
                if item == root / OWNER_FILE:
                    continue
                relative = item.relative_to(root).as_posix()
                self._identity(item)
                actual.add(relative)
                if item.is_dir():
                    stack.append(item)
        if actual != expected:
            raise SafetyError("Workspace contains unregistered or missing artifacts; refusing cleanup.")


def require_os_network_isolation() -> None:
    """Fail closed until a platform sandbox verifier can produce attestation."""
    raise SafetyError("OS-enforced outbound network isolation has not been verified.")


_RUNTIME_ENV_ALLOWLIST = (
    "PATH", "SYSTEMROOT", "WINDIR", "SYSTEMDRIVE", "PATHEXT", "COMSPEC",
    "TEMP", "TMP", "TMPDIR", "LANG", "LC_ALL",
)


def child_environment(base: dict[str, str], workspace: E2EWorkspace,
                      configured_database_path: str | Path | None) -> dict[str, str]:
    """Build an allowlisted child environment after revalidating its DB path."""
    if not isinstance(workspace, E2EWorkspace):
        raise SafetyError("A live E2E workspace is required.")
    validated = workspace.database_path(configured_database_path)
    database = validated.resolve(strict=False)
    if database != validated or workspace.path not in database.parents:
        raise SafetyError("Canonical disposable database path validation failed.")
    result = {key: base[key] for key in _RUNTIME_ENV_ALLOWLIST if key in base}
    result["ENABLE_BASETEN"] = "0"
    result["STORY_CONNECT_E2E_MODE"] = "1"
    result["STORY_CONNECT_E2E_WORKSPACE"] = str(workspace.path)
    result["STORY_CONNECT_E2E_DATABASE_PATH"] = str(database)
    return result


def _is_reparse_point(info: os.stat_result) -> bool:
    attributes = getattr(info, "st_file_attributes", 0)
    return bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


__all__ = ["E2EWorkspace", "SafetyError", "child_environment", "require_os_network_isolation"]
