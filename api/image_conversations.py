from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Header, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from api.support import require_identity, resolve_image_base_url
from services.image_conversation_service import (
    ImageConversationAccessError,
    ImageConversationNotFound,
    image_conversation_service,
)
from services.image_service import download_images_zip


class RenameConversationRequest(BaseModel):
    title: str


class DownloadConversationImagesRequest(BaseModel):
    image_ids: list[str] | None = None


def _map_error(exc: Exception) -> HTTPException:
    if isinstance(exc, HTTPException):
        return exc
    if isinstance(exc, ImageConversationNotFound):
        return HTTPException(status_code=404, detail={"error": "会话不存在"})
    if isinstance(exc, ImageConversationAccessError):
        return HTTPException(status_code=403, detail={"error": "没有权限访问这个会话"})
    if isinstance(exc, ValueError):
        return HTTPException(status_code=400, detail={"error": str(exc)})
    return HTTPException(status_code=500, detail={"error": str(exc) or exc.__class__.__name__})


def create_router() -> APIRouter:
    router = APIRouter()

    @router.get("/api/image-conversations")
    async def list_image_conversations(
        request: Request,
        scope: str = Query(default="mine"),
        authorization: str | None = Header(default=None),
    ):
        identity = require_identity(authorization)
        include_all = scope == "all"
        try:
            return await run_in_threadpool(
                image_conversation_service.list_conversations,
                identity,
                include_all=include_all,
                base_url=resolve_image_base_url(request),
            )
        except Exception as exc:
            raise _map_error(exc) from exc

    @router.put("/api/image-conversations/{conversation_id}")
    async def upsert_image_conversation(
        conversation_id: str,
        request: Request,
        body: dict[str, Any] = Body(...),
        authorization: str | None = Header(default=None),
    ):
        identity = require_identity(authorization)
        try:
            return await run_in_threadpool(
                image_conversation_service.upsert_conversation,
                identity,
                conversation_id,
                body,
                base_url=resolve_image_base_url(request),
            )
        except Exception as exc:
            raise _map_error(exc) from exc

    @router.patch("/api/image-conversations/{conversation_id}/rename")
    async def rename_image_conversation(
        conversation_id: str,
        body: RenameConversationRequest,
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        identity = require_identity(authorization)
        try:
            return await run_in_threadpool(
                image_conversation_service.rename_conversation,
                identity,
                conversation_id,
                body.title,
                base_url=resolve_image_base_url(request),
            )
        except Exception as exc:
            raise _map_error(exc) from exc

    @router.delete("/api/image-conversations/{conversation_id}")
    async def delete_image_conversation(
        conversation_id: str,
        authorization: str | None = Header(default=None),
    ):
        identity = require_identity(authorization)
        try:
            return await run_in_threadpool(image_conversation_service.delete_conversation, identity, conversation_id)
        except Exception as exc:
            raise _map_error(exc) from exc

    @router.post("/api/image-conversations/clear")
    async def clear_image_conversations(authorization: str | None = Header(default=None)):
        identity = require_identity(authorization)
        try:
            return await run_in_threadpool(image_conversation_service.clear_conversations, identity)
        except Exception as exc:
            raise _map_error(exc) from exc

    @router.post("/api/image-conversations/{conversation_id}/download")
    async def download_image_conversation_images(
        conversation_id: str,
        body: DownloadConversationImagesRequest,
        authorization: str | None = Header(default=None),
    ):
        identity = require_identity(authorization)
        try:
            paths = await run_in_threadpool(
                image_conversation_service.download_paths,
                identity,
                conversation_id,
                body.image_ids,
            )
            buf = await run_in_threadpool(download_images_zip, paths)
        except Exception as exc:
            raise _map_error(exc) from exc
        return StreamingResponse(
            buf,
            media_type="application/zip",
            headers={"Content-Disposition": 'attachment; filename="image-conversation.zip"'},
        )

    return router
