"""Shared protected-path matching."""

from __future__ import annotations


def is_protected_path(
    file_path: str,
    protected_paths: tuple[str, ...] | list[str],
) -> bool:
    """Return whether a repository-relative path matches a protected entry."""
    normalized_path = file_path.replace("\\", "/")

    for protected_path in protected_paths:
        normalized_protected_path = protected_path.replace("\\", "/")
        if normalized_protected_path.endswith("/"):
            if normalized_path.startswith(normalized_protected_path):
                return True
        elif (
            normalized_path == normalized_protected_path
            or normalized_path.startswith(f"{normalized_protected_path}/")
        ):
            return True

    return False
