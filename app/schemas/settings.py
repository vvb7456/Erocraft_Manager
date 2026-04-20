"""Schemas for runtime settings routes."""

from __future__ import annotations

from pydantic import BaseModel


class SettingsMessageResponse(BaseModel):
    message: str
