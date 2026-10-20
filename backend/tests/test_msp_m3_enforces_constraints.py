from __future__ import annotations

import uuid

import pytest
from sqlalchemy.exc import IntegrityError

from app.db.models import (
    DeviceGroupModel,
    DeviceModel,
    SiteModel,
)
from app.db.session import get_session


BASE_INFRA_KIND = "BASE_INFRASTRUCTURE"


def _cleanup_site(site_id: int) -> None:
    from app.db.models import RoleAssignmentModel
    with get_session() as session:
        group_ids = [
            r[0]
            for r in session.query(DeviceGroupModel.id).filter_by(site_id=site_id).all()
        ]
        if group_ids:
            session.query(DeviceModel).filter(
                DeviceModel.device_group_id.in_(group_ids)
            ).delete(synchronize_session=False)
        session.query(RoleAssignmentModel).filter_by(site_id=site_id).delete(synchronize_session=False)
        row = session.query(SiteModel).filter_by(id=site_id).first()
        if row is not None:
            row.default_group_id = None
        session.flush()
        session.query(DeviceGroupModel).filter_by(site_id=site_id).delete(synchronize_session=False)
        session.query(SiteModel).filter_by(id=site_id).delete(synchronize_session=False)


def test_second_base_infrastructure_site_rejected():
    with pytest.raises(IntegrityError):
        with get_session() as session:
            session.add(SiteModel(
                name=f"impostor-base-{uuid.uuid4().hex[:6]}",
                kind=BASE_INFRA_KIND,
            ))


def test_second_default_group_in_same_site_rejected():
    site_name = f"m3-dup-def-{uuid.uuid4().hex[:6]}"
    site_id = None
    try:
        with get_session() as session:
            site = SiteModel(name=site_name, kind="REGULAR")
            session.add(site)
            session.flush()
            site_id = site.id
            g1 = DeviceGroupModel(name="Default", site_id=site.id, is_default=True)
            session.add(g1)
            session.flush()
            site.default_group_id = g1.id

        with pytest.raises(IntegrityError):
            with get_session() as session:
                session.add(DeviceGroupModel(
                    name="ExtraDefault", site_id=site_id, is_default=True,
                ))
    finally:
        if site_id is not None:
            _cleanup_site(site_id)


def test_two_default_groups_in_different_sites_allowed():
    tag = uuid.uuid4().hex[:6]
    a_name = f"m3-def-A-{tag}"
    b_name = f"m3-def-B-{tag}"
    a_id = b_id = None
    try:
        for name in (a_name, b_name):
            with get_session() as session:
                site = SiteModel(name=name, kind="REGULAR")
                session.add(site)
                session.flush()
                g = DeviceGroupModel(name="Default", site_id=site.id, is_default=True)
                session.add(g)
                session.flush()
                site.default_group_id = g.id
                if name == a_name:
                    a_id = site.id
                else:
                    b_id = site.id
    finally:
        for sid in (b_id, a_id):
            if sid is not None:
                _cleanup_site(sid)


def test_two_groups_same_name_same_site_rejected():
    site_name = f"m3-uq-dup-{uuid.uuid4().hex[:6]}"
    site_id = None
    try:
        with get_session() as session:
            site = SiteModel(name=site_name, kind="REGULAR")
            session.add(site)
            session.flush()
            site_id = site.id
            g1 = DeviceGroupModel(name="engineering", site_id=site.id, is_default=False)
            session.add(g1)
            session.flush()

        with pytest.raises(IntegrityError):
            with get_session() as session:
                session.add(DeviceGroupModel(
                    name="engineering", site_id=site_id, is_default=False,
                ))
    finally:
        if site_id is not None:
            _cleanup_site(site_id)


def test_two_groups_same_name_different_sites_allowed():
    tag = uuid.uuid4().hex[:6]
    site_ids = []
    try:
        for name in (f"m3-uq-A-{tag}", f"m3-uq-B-{tag}"):
            with get_session() as session:
                site = SiteModel(name=name, kind="REGULAR")
                session.add(site)
                session.flush()
                site_ids.append(site.id)
                session.add(DeviceGroupModel(
                    name="engineering", site_id=site.id, is_default=False,
                ))
    finally:
        for sid in reversed(site_ids):
            _cleanup_site(sid)


def test_delete_site_with_groups_blocked_by_restrict_fk():
    site_name = f"m3-fk-{uuid.uuid4().hex[:6]}"
    site_id = None
    try:
        with get_session() as session:
            site = SiteModel(name=site_name, kind="REGULAR")
            session.add(site)
            session.flush()
            site_id = site.id
            session.add(DeviceGroupModel(
                name="Default", site_id=site.id, is_default=True,
            ))

        with pytest.raises(IntegrityError):
            with get_session() as session:
                session.query(SiteModel).filter_by(id=site_id).delete(
                    synchronize_session=False,
                )
    finally:
        if site_id is not None:
            _cleanup_site(site_id)
