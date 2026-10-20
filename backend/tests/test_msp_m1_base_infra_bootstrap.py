from app.db.models import DeviceGroupModel, SiteModel
from app.db.session import get_session
from app.repositories.site_repository import BASE_INFRA_SITE_KIND, DEFAULT_GROUP_NAME

BASE_INFRA_SITE_NAME = "Base Infrastructure"


def ensure_base_infrastructure():
    from app.composition import site_repository
    return site_repository.crear_con_grupo_default(
        BASE_INFRA_SITE_NAME, "System-managed base infrastructure site.",
        kind=BASE_INFRA_SITE_KIND,
    )


def test_exactly_one_base_infrastructure_site_exists():
    with get_session() as session:
        rows = session.query(SiteModel).filter_by(kind=BASE_INFRA_SITE_KIND).all()
        assert len(rows) == 1
        assert rows[0].name == BASE_INFRA_SITE_NAME


def test_base_infra_site_has_non_null_default_group_id():
    with get_session() as session:
        site = session.query(SiteModel).filter_by(kind=BASE_INFRA_SITE_KIND).one()
        assert site.default_group_id is not None


def test_base_infra_default_group_is_flagged_and_named():
    with get_session() as session:
        site = session.query(SiteModel).filter_by(kind=BASE_INFRA_SITE_KIND).one()
        group = session.query(DeviceGroupModel).filter_by(
            id=site.default_group_id
        ).one()
        assert group.is_default is True
        assert group.name == DEFAULT_GROUP_NAME
        assert group.site_id == site.id


def test_ensure_base_infrastructure_is_idempotent():
    with get_session() as session:
        sites_before = session.query(SiteModel).filter_by(
            kind=BASE_INFRA_SITE_KIND
        ).count()
        groups_before = session.query(DeviceGroupModel).filter_by(
            is_default=True
        ).count()

    ensure_base_infrastructure()
    ensure_base_infrastructure()

    with get_session() as session:
        sites_after = session.query(SiteModel).filter_by(
            kind=BASE_INFRA_SITE_KIND
        ).count()
        groups_after = session.query(DeviceGroupModel).filter_by(
            is_default=True
        ).count()

    assert sites_after == sites_before
    assert groups_after == groups_before


def test_ensure_relinks_when_default_group_id_is_cleared():
    with get_session() as session:
        site = session.query(SiteModel).filter_by(kind=BASE_INFRA_SITE_KIND).one()
        original_default_group_id = site.default_group_id
        site.default_group_id = None

    ensure_base_infrastructure()

    with get_session() as session:
        site = session.query(SiteModel).filter_by(kind=BASE_INFRA_SITE_KIND).one()
        default_group_count = session.query(DeviceGroupModel).filter_by(
            site_id=site.id, is_default=True
        ).count()
        assert site.default_group_id == original_default_group_id
        assert default_group_count == 1
