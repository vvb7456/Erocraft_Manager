"""客服截图原文件存储；所有会话共用容量上限。"""

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


def save_image(data: bytes, media_type: str) -> str:
    settings = get_settings()
    directory = Path(settings.support_image_dir)
    limit = settings.support_image_max_mb * 1024 * 1024
    if len(data) > limit:
        raise HTTPException(413, "截图超过存储容量上限")
    # 上传在线程池中写入，容量检查和写入需作为一个整体执行。
    with _write_lock:
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        files = [(path, path.stat()) for path in directory.iterdir() if path.is_file()]
        total = sum(stat.st_size for _, stat in files)
        for path, stat in sorted(files, key=lambda item: item[1].st_mtime_ns):
            if total + len(data) <= limit:
                break
            path.unlink()
            total -= stat.st_size
        name = uuid4().hex + _EXTENSIONS[media_type]
        (directory / name).write_bytes(data)
        return name
