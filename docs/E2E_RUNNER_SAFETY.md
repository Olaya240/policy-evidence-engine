# Disposable E2E runner safety design

`scripts/e2e_safety.py` supplies a unique workspace, run ownership metadata,
canonical path validation, a workspace-bound database path, and an allowlisted
child environment. The allowlist preserves only runtime variables needed by
Python/Node on Windows or POSIX: `PATH`, `SYSTEMROOT`, `WINDIR`, `SYSTEMDRIVE`,
`PATHEXT`, `COMSPEC`, `TEMP`, `TMP`, `TMPDIR`, `LANG`, and `LC_ALL`. It then
sets `ENABLE_BASETEN=0` and explicit E2E mode/workspace/database variables.
Other inherited keys, including provider and cloud credentials, are omitted.

The backend's normal `HACKATHON_DB_PATH` validation remains confined to its
application data directory. A distinct E2E configuration is used only when all
three `STORY_CONNECT_E2E_MODE`, `STORY_CONNECT_E2E_WORKSPACE`, and
`STORY_CONNECT_E2E_DATABASE_PATH` values are present and valid. E2E mode rejects
the normal database override and accepts only
`<system-temp>/story-connect-e2e-*/database/e2e.sqlite3` with the matching owner
manifest. Normal startup retains the existing data-directory rules.

On Windows, identity checks open paths with `CreateFileW`,
`FILE_FLAG_BACKUP_SEMANTICS`, and `FILE_FLAG_OPEN_REPARSE_POINT`, query
`BY_HANDLE_FILE_INFORMATION` for the volume serial and file index, and reject
`FILE_ATTRIBUTE_REPARSE_POINT`. Handles are retained for the workspace,
manifest, and registered artifacts. POSIX uses `lstat` device/inode identity.
These checks detect replacement at validation time; the Windows handle share
mode does not reliably prevent rename or deletion, as the replacement tests
demonstrate. Creation and registration remain path-based, so a substitution
between validation and the filesystem operation is not proven impossible.

Cleanup recursively inventories the workspace, checks every entry against the
registered identities, and refuses when any entry is missing, replaced,
unregistered, a symlink, or a reparse point. It currently performs no
deletions. A reviewed handle-relative creation/deletion adapter is required
before cleanup can be enabled. This means interrupted runs may leave temporary
artifacts for manual inspection.

OS-level network isolation is not implemented. Its gate always raises. Windows
Job Object ownership, Playwright profile lifecycle, and runner integration are
also absent. No application process or browser can be started through these
primitives. Browser execution remains prohibited pending a separate audit and
explicit authorization.

`scripts/test_e2e_safety.py` uses temporary directories and synthetic files
only. It validates path and environment policy without opening or creating a
database, starting processes, or making network requests. Its reparse-point
test checks the attribute-handling branch with synthetic metadata; the symlink
test may be skipped when the host cannot create directory symlinks.
