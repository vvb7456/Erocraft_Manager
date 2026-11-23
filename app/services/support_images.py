"""客服截图原文件存储；单用户按独立配额优先淘汰自身旧图，同时受全局容量上限约束。"""

from pathlib import Path
from threading import Lock
from uuid import uuid4

from fastapi import HTTPException

from app.core.config import get_settings

_write_lock = Lock()
_EXTENSIONS = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}


def image_type(data: bytes) -> str:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    raise HTTPException(400, "请上传 PNG、JPEG 或 WebP 截图")


def image_path(name: str) -> Path:
    return Path(get_settings().support_image_dir) / name


def _evict_oldest(files: list[tuple[Path, int, int]], incoming: int, limit: int) -> None:
    total = sum(size for _, size, _ in files)
    for path, size, _ in sorted(files, key=lambda item: item[2]):
        if total + incoming <= limit:
            break
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        total -= size


def save_image(data: bytes, media_type: str, owner_user_id: int | None = None) -> str:
    settings = get_settings()
    directory = Path(settings.support_image_dir)
    global_limit = settings.support_image_max_mb * 1024 * 1024
    user_limit = min(global_limit, settings.support_image_user_max_mb * 1024 * 1024)
    effective_limit = user_limit if owner_user_id is not None else global_limit
    if len(data) > effective_limit:
        raise HTTPException(413, "截图超过存储容量上限")
    # 上传在线程池中写入，容量检查和写入需作为一个整体执行。
    with _write_lock:
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        if owner_user_id is not None:
            owner_dir = directory / str(owner_user_id)
            owner_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
            user_files = [
                (p, st.st_size, st.st_mtime_ns)
                for p in owner_dir.iterdir()
                if p.is_file()
                for st in (p.stat(),)
            ]
            _evict_oldest(user_files, len(data), user_limit)
        else:
            owner_dir = directory

        all_files = [
            (p, st.st_size, st.st_mtime_ns)
            for p in directory.rglob("*")
            if p.is_file()
            for st in (p.stat(),)
        ]
        _evict_oldest(all_files, len(data), global_limit)

        name = uuid4().hex + _EXTENSIONS[media_type]
        (owner_dir / name).write_bytes(data)
        return f"{owner_user_id}/{name}" if owner_user_id is not None else name
