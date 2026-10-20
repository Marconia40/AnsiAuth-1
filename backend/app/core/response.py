from typing import Any

_UNSET = object()


def ok(data: Any = _UNSET, **extra) -> dict:
    body: dict = {"success": True}
    if data is not _UNSET:
        body["data"] = data
    body.update(extra)
    return body
