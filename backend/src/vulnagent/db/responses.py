"""Appwrite SDK responses as the plain JSON the service sent.

The server SDK wraps every response in a pydantic model and moves a row's
columns under a `data` key. The code here reads dictionaries with the columns
at the top level, so every response passes through :func:`plain` first.
"""

from __future__ import annotations

from typing import Any


def plain(response: Any) -> Any:
    to_dict = getattr(response, "to_dict", None)
    return _flatten(to_dict() if callable(to_dict) else response)


def _flatten(value: Any) -> Any:
    if isinstance(value, list):
        return [_flatten(item) for item in value]
    if not isinstance(value, dict):
        return value
    flat = {key: _flatten(item) for key, item in value.items()}
    columns = flat.get("data")
    if not isinstance(columns, dict):
        return flat
    return {**{key: item for key, item in flat.items() if key != "data"}, **columns}
