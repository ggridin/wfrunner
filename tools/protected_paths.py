"""Shared protected-path matching."""

from __future__ import annotations


def _normalize(path: str) -> str:
    return path.replace("\\", "/")


def is_protected_path(
    file_path: str,
    protected_paths: tuple[str, ...] | list[str],
) -> bool:
    """Return whether a repository-relative path matches a protected entry."""
    normalized_path = _normalize(file_path)

    for protected_path in protected_paths:
        normalized_protected_path = _normalize(protected_path)
        if normalized_protected_path.endswith("/"):
            if normalized_path.startswith(normalized_protected_path):
                return True
        elif (
            normalized_path == normalized_protected_path
            or normalized_path.startswith(f"{normalized_protected_path}/")
        ):
            return True

    return False


def allowed_entry_covers_protected_path(
    allowed_entry: str,
    protected_paths: tuple[str, ...] | list[str],
) -> bool:
    """Return whether an ``allowed_files`` entry authorizes writing a protected path.

    An entry may be a concrete path or a folder pattern. Folder patterns must be
    checked as patterns: testing ``docs/**`` as though it were a literal path
    never matches a protected entry, yet it grants write access to everything
    beneath ``docs/``. Both spellings are handled:

    - ``prefix/**`` covers every protected entry at or below ``prefix/``.
    - ``prefix/*`` covers protected entries directly inside ``prefix/``.
    """
    normalized_entry = _normalize(allowed_entry)

    if is_protected_path(normalized_entry, protected_paths):
        return True

    if normalized_entry.endswith("/**"):
        prefix = normalized_entry[:-2]
        recursive = True
    elif normalized_entry.endswith("/*"):
        prefix = normalized_entry[:-1]
        recursive = False
    else:
        return False

    # A pattern rooted inside a protected directory is itself protected.
    if is_protected_path(prefix, protected_paths):
        return True

    for protected_path in protected_paths:
        normalized_protected_path = _normalize(protected_path)
        if not normalized_protected_path.startswith(prefix):
            continue
        remainder = normalized_protected_path[len(prefix):]
        if not remainder:
            return True
        if recursive:
            return True
        # Single-level patterns only reach entries directly inside the prefix.
        if "/" not in remainder.rstrip("/"):
            return True

    return False
