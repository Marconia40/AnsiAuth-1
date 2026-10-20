from __future__ import annotations

import dataclasses
from typing import Any, Callable, Generic, Optional, TypeVar

from app.db.session import get_session

T = TypeVar("T")


class Repository(Generic[T]):
    def __init__(
        self,
        orm_model: type,
        to_domain: Callable[[Any], T],
        to_orm: Callable[[T], Any],
        pk_field: "str | tuple[str, ...]" = "id",
    ):
        self._orm_model = orm_model
        self._to_domain = to_domain
        self._to_orm = to_orm
        self._pk_field: tuple[str, ...] = (
            pk_field if isinstance(pk_field, tuple) else (pk_field,)
        )

    def _pk_filtro(self, pk: Any) -> dict:
        valores = pk if isinstance(pk, tuple) else (pk,)
        if len(valores) != len(self._pk_field):
            raise ValueError(
                f"pk esperaba {len(self._pk_field)} valor(es) {self._pk_field}, "
                f"recibió {len(valores)}"
            )
        return dict(zip(self._pk_field, valores))

    def get(self, pk: Any) -> Optional[T]:
        with get_session() as session:
            row = (
                session.query(self._orm_model)
                .filter_by(**self._pk_filtro(pk))
                .first()
            )
            return self._to_domain(row) if row is not None else None

    def list(self, **filtros: Any) -> list[T]:
        with get_session() as session:
            q = session.query(self._orm_model)
            if filtros:
                q = q.filter_by(**filtros)
            return [self._to_domain(row) for row in q.all()]

    def add(self, entidad: T) -> T:
        with get_session() as session:
            row = self._to_orm(entidad)
            pk_reales = [c.name for c in self._orm_model.__mapper__.primary_key]
            if list(self._pk_field) != pk_reales:
                valores_pk = tuple(getattr(entidad, campo) for campo in self._pk_field)
                existente = (
                    session.query(self._orm_model)
                    .filter_by(**self._pk_filtro(valores_pk))
                    .first()
                )
                if existente is not None:
                    for campo in pk_reales:
                        setattr(row, campo, getattr(existente, campo))
            merged = session.merge(row)
            session.flush()
            return self._to_domain(merged)

    def actualizar_campos(self, entidad: T, cambios: dict) -> T:
        pk = tuple(getattr(entidad, campo) for campo in self._pk_field)
        existente = self.get(pk if len(pk) > 1 else pk[0])
        if existente is None:
            return self.add(entidad)
        return self.add(dataclasses.replace(existente, **cambios))

    def remove(self, pk: Any) -> None:
        with get_session() as session:
            session.query(self._orm_model).filter_by(**self._pk_filtro(pk)).delete()

    def quitar(self, entidad: T) -> None:
        self.remove(tuple(getattr(entidad, campo) for campo in self._pk_field))

    def existe(self, **criterio: Any) -> bool:
        with get_session() as session:
            return session.query(self._orm_model).filter_by(**criterio).first() is not None
