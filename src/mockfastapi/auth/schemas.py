"""Public authentication value objects."""

from pydantic import BaseModel


class Principal(BaseModel):
    id: int
    username: str
    role: str


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    expires_in: int
