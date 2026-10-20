from __future__ import annotations

from dataclasses import dataclass


_ROLE_LEVEL = {"observer": 1, "operator": 2, "admin": 3}


@dataclass(frozen=True)
class VisibilityScope:
    es_system_admin: bool
    grants: tuple[tuple[int, "int | None", str], ...]

    def rol_para(self, site_id: int, device_group_id: "int | None" = None) -> "str | None":
        if self.es_system_admin:
            return "super-admin"
        site_wide: "str | None" = None
        group_specific: "str | None" = None
        for sid, gid, role in self.grants:
            if sid != site_id:
                continue
            if gid is None:
                site_wide = role
            elif device_group_id is not None and gid == device_group_id:
                group_specific = role
        if device_group_id is None:
            return site_wide
        candidates = [r for r in (site_wide, group_specific) if r is not None]
        if not candidates:
            return None
        return max(candidates, key=_ROLE_LEVEL.__getitem__)

    @property
    def site_ids(self) -> "set[int] | None":
        return None if self.es_system_admin else {sid for sid, gid, _ in self.grants if gid is None}

    @property
    def device_group_ids(self) -> "set[int]":
        return set() if self.es_system_admin else {gid for _, gid, _ in self.grants if gid is not None}
