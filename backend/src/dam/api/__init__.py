"""Local HTTP API (FastAPI): a thin layer over the App services."""

from dam.api.main import create_api

__all__ = ["create_api"]
