from __future__ import annotations

import base64
import json
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import inspect

from app.errors import ApiError


def json_value(value: Any) -> Any:
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, list):
        return [json_value(item) for item in value]
    if isinstance(value, dict):
        return {key: json_value(item) for key, item in value.items()}
    return value


def model_dict(model: Any, *, exclude: set[str] | None = None) -> dict[str, Any]:
    excluded = exclude or set()
    return {
        column.key: json_value(getattr(model, column.key))
        for column in inspect(model).mapper.column_attrs
        if column.key not in excluded
    }


def encode_cursor(created_at: datetime, identifier: str) -> str:
    payload = json.dumps([created_at.isoformat(), identifier], separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(payload).rstrip(b"=").decode()


def decode_cursor(cursor: str | None) -> tuple[datetime, str] | None:
    if not cursor:
        return None
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
        timestamp, identifier = json.loads(raw)
        return datetime.fromisoformat(timestamp), str(identifier)
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise ApiError(422, "CURSOR_INVALID", "分页游标无效。") from exc


def encode_sorted_cursor(sort_order: int, created_at: datetime, identifier: str) -> str:
    payload = json.dumps(
        [sort_order, created_at.isoformat(), identifier], separators=(",", ":")
    ).encode()
    return base64.urlsafe_b64encode(payload).rstrip(b"=").decode()


def decode_sorted_cursor(cursor: str | None) -> tuple[int, datetime, str] | None:
    if not cursor:
        return None
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
        sort_order, timestamp, identifier = json.loads(raw)
        if isinstance(sort_order, bool) or not isinstance(sort_order, int):
            raise ValueError("invalid sort order")
        return sort_order, datetime.fromisoformat(timestamp), str(identifier)
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise ApiError(422, "CURSOR_INVALID", "分页游标无效。") from exc


def page_response(items: list[dict[str, Any]], next_cursor: str | None) -> dict[str, Any]:
    return {"items": items, "next_cursor": next_cursor}
