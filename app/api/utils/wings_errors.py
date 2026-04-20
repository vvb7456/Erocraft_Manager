"""Translate WingsServiceError into structured HTTPException for user-facing APIs."""

from __future__ import annotations

import re

from fastapi import HTTPException, status

from app.services.wings import WingsServiceError

# Wings error message → structured error code mapping
# Supports both English (upstream) and Chinese (pterodactyl-china) Wings builds.
_WINGS_ERROR_MAP: list[tuple[re.Pattern[str], str]] = [
    # --- File operations ---
    (re.compile(r"destination already exists|目标已存在", re.I), "file.destination_exists"),
    (re.compile(r"not (have )?enough (available )?disk space", re.I), "file.no_space"),
    (re.compile(r"format Wings does not understand", re.I), "file.unknown_archive"),
    (re.compile(r"text file busy|in use by another process", re.I), "file.text_busy"),
    (re.compile(r"name conflicts with an existing directory|名称.*冲突", re.I), "file.name_conflict"),
    (re.compile(r"Cannot open files of this type", re.I), "file.unsupported_type"),
    (re.compile(r"not a directory.*ENOTDIR", re.I), "file.not_a_directory"),
    (re.compile(r"is larger than the maximum.*upload size", re.I), "file.upload_too_large"),
    (re.compile(r"no such file or directory|not found on the system|requested directory does not exist", re.I), "file.not_found"),
    (re.compile(r"permission denied", re.I), "file.permission_denied"),
    (re.compile(r"present in egg denylist", re.I), "file.denylist"),
    (re.compile(r"file is a directory|Cannot perform that action: file is a directory", re.I), "file.is_directory"),
    (re.compile(r"file name is too long", re.I), "file.name_too_long"),
    (re.compile(r"没有指定要删除|No files were specified for deletion|No files to move or rename|没有提供要移动或重命名|No files were passed through to be compressed|No files to chmod", re.I), "file.no_files_specified"),
    # --- Server/power ---
    (re.compile(r"Cannot send commands to a stopped server", re.I), "server.offline"),
    (re.compile(r"currently in a suspended state|server that is suspended", re.I), "server.suspended"),
    (re.compile(r"currently installing", re.I), "server.installing"),
    (re.compile(r"power action provided was not valid", re.I), "server.invalid_power_action"),
    (re.compile(r"another power action is (currently being|running)|当前正在.*处理另一个电源操作", re.I), "server.power_conflict"),
    (re.compile(r"Cannot execute server reinstall.*another power action", re.I), "server.power_conflict"),
    # --- Generic ---
    (re.compile(r"could not process this request in time", re.I), "wings.timeout"),
]

# Fallback code when no pattern matches — never exposes raw Wings message
_FALLBACK_CODE = "wings.unknown_error"


def translate_wings_error(exc: WingsServiceError) -> HTTPException:
    """Map a WingsServiceError to an HTTPException with a structured error code."""
    msg = str(exc)
    for pattern, code in _WINGS_ERROR_MAP:
        if pattern.search(msg):
            return HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=code)
    return HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=_FALLBACK_CODE)
