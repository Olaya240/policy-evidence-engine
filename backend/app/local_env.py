"""Backend-only loader for the local ``backend/.env`` file.

Fills documented backend variables from ``backend/.env`` into ``os.environ``
only when they are not already set, so the real process environment always
wins and existing provider behavior is unchanged when variables are set
directly. Unknown keys, blank values, and malformed lines are ignored.

Loading is skipped while the pytest suite is running so offline tests stay
hermetic and keep their synthetic/mock defaults. No values are ever logged
or printed by this module.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ENV_FILE_NAME = ".env"

# Only these documented backend variables may come from the env file. Anything
# else (PATH, PYTHONPATH, frontend variables, typos) is ignored.
ALLOWED_ENV_KEYS = frozenset({
    "ENABLE_META",
    "ENABLE_BASETEN",
    "MODEL_API_KEY",
    "BASETEN_API_KEY",
    "META_MAX_REQUESTS",
    "META_MAX_ESTIMATED_COST_USD",
    "META_CONSERVATIVE_COST_PER_REQUEST_USD",
    "POLICY_DEMO_PROVIDER",
    "POLICY_DEMO_BASETEN_MAX_REQUESTS",
    "POLICY_DEMO_BASETEN_MAX_ESTIMATED_COST_USD",
    "POLICY_DEMO_BASETEN_CONSERVATIVE_COST_PER_REQUEST_USD",
    "HACKATHON_DB_PATH",
})


def backend_env_path() -> Path:
    """Return the backend ``.env`` path, resolved from this file's location."""
    return Path(__file__).resolve().parent.parent / ENV_FILE_NAME


def _parse_env_file(path: Path) -> dict[str, str]:
    """Parse ``KEY=VALUE`` lines; return allowlisted, non-empty entries.

    Blank lines and ``#`` comments are skipped. Surrounding single or double
    quotes are stripped from values. Anything malformed or not allowlisted is
    silently ignored so a stray line can never hijack the process environment.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    entries: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        key = key.strip()
        if (not key or key not in ALLOWED_ENV_KEYS or not key.replace("_", "").isalnum()
                or key[0].isdigit()):
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        if not value:
            continue
        entries.setdefault(key, value)
    return entries


def load_backend_env_file(path: Path | str | None = None) -> tuple[str, ...]:
    """Fill unset allowlisted variables from ``backend/.env``.

    Returns the sorted names of variables that were filled. Names only; values
    are never returned, logged, or printed.
    """
    if "pytest" in sys.modules or os.environ.get("PYTEST_CURRENT_TEST"):
        return ()
    env_path = Path(path) if path is not None else backend_env_path()
    filled: list[str] = []
    for key, value in _parse_env_file(env_path).items():
        if key not in os.environ:
            os.environ[key] = value
            filled.append(key)
    return tuple(sorted(filled))


__all__ = ["ALLOWED_ENV_KEYS", "ENV_FILE_NAME", "backend_env_path", "load_backend_env_file"]
