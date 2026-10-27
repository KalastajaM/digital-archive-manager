"""The base of the request models, and the error answer (dam.api.schemas)."""

from pydantic import BaseModel, ConfigDict


class StrictIn(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ErrorBody(BaseModel):
    error: str
