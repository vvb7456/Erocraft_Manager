"""User-facing file management routes proxied to Wings."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.auth import get_current_user
from app.api.deps.db import get_db
from app.api.deps.ownership import get_owned_server
from app.db.models.pterodactyl import PteroServer, PteroUser
from app.schemas.user_servers import (
    FileCompressRequest,
    FileContentResponse,
    FileCreateFolderRequest,
    FileDecompressRequest,
    FileDeleteRequest,
    FileRenameRequest,
    FileWriteRequest,
    SignedUrlResponse,
    WingsFileEntry,
)
from app.api.utils.wings_errors import translate_wings_error
from app.services.pterodactyl_activity import pterodactyl_activity_logger
from app.services.wings import WingsServiceError, wings_service

router = APIRouter(prefix="/user", tags=["user_files"])


@router.get("/servers/{server_id}/files/list", response_model=list[WingsFileEntry])
async def list_user_server_files(
    directory: str = Query(default="/"),
    server: PteroServer = Depends(get_owned_server),
    db: AsyncSession = Depends(get_db),
) -> list[WingsFileEntry]:
    try:
        entries = await wings_service.list_files(db, server.node_id, server.uuid, directory)
    except WingsServiceError as exc:
        raise translate_wings_error(exc) from exc
    return [WingsFileEntry.model_validate(entry) for entry in entries]


@router.get("/servers/{server_id}/files/contents", response_model=FileContentResponse)
async def get_user_server_file_contents(
    request: Request,
    file: str = Query(min_length=1),
    current_user: PteroUser = Depends(get_current_user),
    server: PteroServer = Depends(get_owned_server),
    db: AsyncSession = Depends(get_db),
) -> FileContentResponse:
    try:
        content = await wings_service.get_file_contents(db, server.node_id, server.uuid, file)
    except WingsServiceError as exc:
        raise translate_wings_error(exc) from exc
    await pterodactyl_activity_logger.log_server_activity(
        db,
        server=server,
        actor=current_user,
        event="server:file.read",
        properties={"file": file},
        request=request,
    )
    await db.commit()
    return FileContentResponse(content=content)


@router.post("/servers/{server_id}/files/write", status_code=status.HTTP_204_NO_CONTENT)
async def write_user_server_file(
    payload: FileWriteRequest,
    request: Request,
    file: str = Query(min_length=1),
    current_user: PteroUser = Depends(get_current_user),
    server: PteroServer = Depends(get_owned_server),
    db: AsyncSession = Depends(get_db),
) -> Response:
    try:
        await wings_service.write_file(db, server.node_id, server.uuid, file, payload.content)
    except WingsServiceError as exc:
        raise translate_wings_error(exc) from exc
    await pterodactyl_activity_logger.log_server_activity(
        db,
        server=server,
        actor=current_user,
        event="server:file.write",
        properties={"file": file},
        request=request,
    )
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/servers/{server_id}/files/rename", status_code=status.HTTP_204_NO_CONTENT)
async def rename_user_server_file(
    payload: FileRenameRequest,
    request: Request,
    current_user: PteroUser = Depends(get_current_user),
    server: PteroServer = Depends(get_owned_server),
    db: AsyncSession = Depends(get_db),
) -> Response:
    try:
        await wings_service.rename_file(
            db,
            server.node_id,
            server.uuid,
            payload.root,
            payload.from_path,
            payload.to,
        )
    except WingsServiceError as exc:
        raise translate_wings_error(exc) from exc
    await pterodactyl_activity_logger.log_server_activity(
        db,
        server=server,
        actor=current_user,
        event="server:file.rename",
        properties={
            "directory": payload.root,
            "files": [{"from": payload.from_path, "to": payload.to}],
        },
        request=request,
    )
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/servers/{server_id}/files/delete", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user_server_files(
    payload: FileDeleteRequest,
    request: Request,
    current_user: PteroUser = Depends(get_current_user),
    server: PteroServer = Depends(get_owned_server),
    db: AsyncSession = Depends(get_db),
) -> Response:
    try:
        await wings_service.delete_files(db, server.node_id, server.uuid, payload.root, payload.files)
    except WingsServiceError as exc:
        raise translate_wings_error(exc) from exc
    await pterodactyl_activity_logger.log_server_activity(
        db,
        server=server,
        actor=current_user,
        event="server:file.delete",
        properties={"directory": payload.root, "files": payload.files},
        request=request,
    )
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/servers/{server_id}/files/compress")
async def compress_user_server_files(
    payload: FileCompressRequest,
    request: Request,
    current_user: PteroUser = Depends(get_current_user),
    server: PteroServer = Depends(get_owned_server),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        result = await wings_service.compress_files(db, server.node_id, server.uuid, payload.root, payload.files)
    except WingsServiceError as exc:
        raise translate_wings_error(exc) from exc
    await pterodactyl_activity_logger.log_server_activity(
        db,
        server=server,
        actor=current_user,
        event="server:file.compress",
        properties={"directory": payload.root, "files": payload.files},
        request=request,
    )
    await db.commit()
    return result


@router.post("/servers/{server_id}/files/decompress", status_code=status.HTTP_204_NO_CONTENT)
async def decompress_user_server_file(
    payload: FileDecompressRequest,
    request: Request,
    current_user: PteroUser = Depends(get_current_user),
    server: PteroServer = Depends(get_owned_server),
    db: AsyncSession = Depends(get_db),
) -> Response:
    try:
        await wings_service.decompress_file(db, server.node_id, server.uuid, payload.root, payload.file)
    except WingsServiceError as exc:
        raise translate_wings_error(exc) from exc
    await pterodactyl_activity_logger.log_server_activity(
        db,
        server=server,
        actor=current_user,
        event="server:file.decompress",
        properties={"directory": payload.root, "files": payload.file},
        request=request,
    )
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/servers/{server_id}/files/create-folder", status_code=status.HTTP_204_NO_CONTENT)
async def create_user_server_folder(
    payload: FileCreateFolderRequest,
    request: Request,
    current_user: PteroUser = Depends(get_current_user),
    server: PteroServer = Depends(get_owned_server),
    db: AsyncSession = Depends(get_db),
) -> Response:
    try:
        await wings_service.create_directory(db, server.node_id, server.uuid, payload.name, payload.path)
    except WingsServiceError as exc:
        raise translate_wings_error(exc) from exc
    await pterodactyl_activity_logger.log_server_activity(
        db,
        server=server,
        actor=current_user,
        event="server:file.create-directory",
        properties={"name": payload.name, "directory": payload.path},
        request=request,
    )
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/servers/{server_id}/files/download", response_model=SignedUrlResponse)
async def get_user_server_download_url(
    request: Request,
    file: str = Query(min_length=1),
    current_user: PteroUser = Depends(get_current_user),
    server: PteroServer = Depends(get_owned_server),
    db: AsyncSession = Depends(get_db),
) -> SignedUrlResponse:
    try:
        url = await wings_service.get_download_url(db, server.node_id, server.uuid, file)
    except WingsServiceError as exc:
        raise translate_wings_error(exc) from exc
    await pterodactyl_activity_logger.log_server_activity(
        db,
        server=server,
        actor=current_user,
        event="server:file.download",
        properties={"file": file},
        request=request,
    )
    await db.commit()
    return SignedUrlResponse(url=url)


@router.post("/servers/{server_id}/files/upload", response_model=SignedUrlResponse)
async def get_user_server_upload_url(
    server: PteroServer = Depends(get_owned_server),
    db: AsyncSession = Depends(get_db),
) -> SignedUrlResponse:
    try:
        url = await wings_service.get_upload_url(db, server.node_id, server.uuid)
    except WingsServiceError as exc:
        raise translate_wings_error(exc) from exc
    return SignedUrlResponse(url=url)
