import re
from typing import Annotated, Generic, TypeVar

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field

T = TypeVar("T")


def _strip(v):
    if isinstance(v, str):
        v = v.strip()
        return v or None
    return v


# Optional text: whitespace-only becomes None so blank form fields don't store "".
OptStr = Annotated[str | None, BeforeValidator(_strip)]


def ShortText(max_length: int):  # noqa: N802 - reads like a type
    # Constraint sits on the inner str so a blank value stripped to None isn't length-checked.
    return Annotated[
        Annotated[str, Field(max_length=max_length)] | None,
        BeforeValidator(_strip),
        Field(default=None),
    ]


def digits_only(value: str | None) -> str | None:
    if not value:
        return None
    d = re.sub(r"\D", "", value)
    return d or None


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int


class PageParams(BaseModel):
    page: int = Field(1, ge=1)
    page_size: int = Field(25, ge=1, le=100)

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size
