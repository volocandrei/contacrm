"""Tipurile de transport comune tuturor endpoint-urilor.

Contractul JSON este **camelCase**, pentru că frontend-ul îl consumă direct
(`frontend/src/api/types.ts`). Python-ul rămâne snake_case; conversia o face
`alias_generator`, într-un singur loc.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field
from pydantic.alias_generators import to_camel

MAX_PAGE_SIZE = 200
DEFAULT_PAGE_SIZE = 25


class ApiModel(BaseModel):
    """Baza oricărei scheme expuse prin API."""

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        from_attributes=True,
    )


class PageParams(ApiModel):
    """Paginarea, validată la margine — nu în servicii (§61)."""

    page: Annotated[int, Field(ge=1)] = 1
    page_size: Annotated[int, Field(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


class SortParams(ApiModel):
    sort: str | None = None
    order: Literal["asc", "desc"] = "desc"


class Paginated[T](ApiModel):
    """Forma exactă a lui `Paginated<T>` din frontend."""

    items: list[T]
    page: int
    page_size: int
    total: int

    @computed_field  # type: ignore[prop-decorator]
    @property
    def total_pages(self) -> int:
        if self.page_size <= 0:
            return 1
        return max(1, -(-self.total // self.page_size))

    @classmethod
    def build(cls, items: list[T], total: int, params: PageParams) -> Paginated[T]:
        return cls(items=items, page=params.page, page_size=params.page_size, total=total)
