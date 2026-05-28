"""Pure helper functions for system settings page.

resolve_project_root: locate repo root by walking up from a start path
read_env / write_env: .env file I/O with sensitive-key protection
"""

from pathlib import Path

PROJECT_MARKERS = ("pyproject.toml", ".env.example", "CLAUDE.md")


def resolve_project_root(start: Path) -> Path:
    """Walk up from *start* until a marker file is found.

    Raises FileNotFoundError if no marker is found before filesystem root.
    """
    cur = start.resolve()
    if cur.is_file():
        cur = cur.parent
    for _ in range(20):
        if any((cur / m).exists() for m in PROJECT_MARKERS):
            return cur
        parent = cur.parent
        if parent == cur:
            break
        cur = parent
    raise FileNotFoundError(
        f"Could not locate project root (searched for {PROJECT_MARKERS}) "
        f"starting from {start}"
    )


def read_env(env_path: Path) -> dict[str, str]:
    """Read a .env file into a dict. Preserves key order.

    Lines starting with '#' are skipped. Blank lines are skipped.
    """
    env: dict[str, str] = {}
    if not env_path.exists():
        return env
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, _, value = line.partition("=")
            env[key.strip()] = value.strip()
    return env


def write_env(
    env_path: Path,
    updates: dict[str, str],
    sensitive_keys: set[str],
) -> None:
    """Update *env_path* with *updates*.

    Sensitive keys whose new value is ``"****"`` or ``""`` are NOT overwritten.
    New keys are appended. Comments and blank lines are preserved.
    """
    if not env_path.exists():
        return
    content = env_path.read_text(encoding="utf-8")
    lines = content.splitlines()
    new_lines: list[str] = []
    updated_keys: set[str] = set()

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            new_lines.append(line)
            continue
        if "=" not in stripped:
            new_lines.append(line)
            continue
        key, _, old_value = stripped.partition("=")
        key = key.strip()
        if key in updates:
            new_value = updates[key]
            if key in sensitive_keys and new_value in ("****", ""):
                new_lines.append(line)  # preserve original
            else:
                new_lines.append(f"{key}={new_value}")
            updated_keys.add(key)
        else:
            new_lines.append(line)

    # Append new keys
    for key, value in updates.items():
        if key not in updated_keys and value:
            new_lines.append(f"{key}={value}")

    env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
