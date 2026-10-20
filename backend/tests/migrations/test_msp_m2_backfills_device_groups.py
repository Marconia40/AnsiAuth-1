import sqlalchemy as sa

from tests.migrations.conftest import (
    REV_M2,
    engine_for,
    seed_device,
    seed_device_group,
    seed_group_member,
    seed_site,
    upgrade,
)


def test_step3_assigns_every_device_to_a_group(db_at_m1):
    url = db_at_m1

    engine = engine_for(url)
    try:
        with engine.begin() as conn:
            seed_device(conn, name="orphan_device", site_id=None)

            library_id = seed_site(conn, name="Library")
            circulation_gid = seed_device_group(
                conn, name="Circulation", site_id=library_id
            )
            seed_device(conn, name="lib_switch_1", site_id=library_id)
            seed_group_member(
                conn, group_id=circulation_gid, device_name="lib_switch_1"
            )

            dc_id = seed_site(conn, name="Datacenter")
            seed_device(conn, name="dc_switch_1", site_id=dc_id)
    finally:
        engine.dispose()

    upgrade(url, REV_M2)

    engine = engine_for(url)
    try:
        with engine.connect() as conn:
            base_default_gid = conn.execute(sa.text("""
                SELECT default_group_id FROM sites WHERE kind='BASE_INFRASTRUCTURE'
            """)).scalar()
            assert base_default_gid is not None
            orphan_gid = conn.execute(sa.text(
                "SELECT device_group_id FROM devices WHERE name='orphan_device'"
            )).scalar()
            assert orphan_gid == base_default_gid

            lib_gid = conn.execute(sa.text(
                "SELECT device_group_id FROM devices WHERE name='lib_switch_1'"
            )).scalar()
            assert lib_gid == circulation_gid

            dc_default_gid = conn.execute(sa.text("""
                SELECT s.default_group_id FROM sites s WHERE s.name='Datacenter'
            """)).scalar()
            assert dc_default_gid is not None
            dc_gid = conn.execute(sa.text(
                "SELECT device_group_id FROM devices WHERE name='dc_switch_1'"
            )).scalar()
            assert dc_gid == dc_default_gid

            n_null = conn.execute(sa.text(
                "SELECT COUNT(*) FROM devices WHERE device_group_id IS NULL"
            )).scalar()
            assert n_null == 0
    finally:
        engine.dispose()
