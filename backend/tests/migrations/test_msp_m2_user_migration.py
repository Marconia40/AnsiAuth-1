import sqlalchemy as sa

from tests.migrations.conftest import (
    REV_M2,
    engine_for,
    seed_allowed_site,
    seed_site,
    seed_user,
    upgrade,
)


def test_step6_migrates_users_correctly(db_at_m1):
    url = db_at_m1

    engine = engine_for(url)
    try:
        with engine.begin() as conn:
            library_id = seed_site(conn, name="Library")
            dc_id = seed_site(conn, name="Datacenter")

            admin_id = seed_user(conn, username="alice", role="admin")
            super_id = seed_user(conn, username="bob", role="super-admin")

            obs_id = seed_user(conn, username="juan", role="observer")
            seed_allowed_site(conn, user_id=obs_id, site_id=library_id)
            seed_allowed_site(conn, user_id=obs_id, site_id=dc_id)

            unassigned_op_id = seed_user(
                conn, username="drifter", role="operator"
            )
    finally:
        engine.dispose()

    upgrade(url, REV_M2)

    engine = engine_for(url)
    try:
        with engine.connect() as conn:
            for uid in (admin_id, super_id):
                flag = conn.execute(sa.text(
                    "SELECT is_system_admin FROM users WHERE id = :u"
                ).bindparams(u=uid)).scalar()
                assert bool(flag) is True

            juan_grants = conn.execute(sa.text("""
                SELECT site_id, device_group_id, role
                  FROM role_assignments
                 WHERE user_id = :u
                 ORDER BY site_id
            """).bindparams(u=obs_id)).fetchall()
            assert sorted((s, g, r) for s, g, r in juan_grants) == sorted([
                (library_id, None, "observer"),
                (dc_id, None, "observer"),
            ])

            n_drifter_grants = conn.execute(sa.text(
                "SELECT COUNT(*) FROM role_assignments WHERE user_id = :u"
            ).bindparams(u=unassigned_op_id)).scalar()
            assert n_drifter_grants == 0

            drifter_flag = conn.execute(sa.text(
                "SELECT is_system_admin FROM users WHERE id = :u"
            ).bindparams(u=unassigned_op_id)).scalar()
            assert bool(drifter_flag) is False
    finally:
        engine.dispose()


def test_step6_skips_base_infra_grants(db_at_m1):
    url = db_at_m1

    engine = engine_for(url)
    try:
        with engine.begin() as conn:
            base_id = seed_site(
                conn, name="Base Infrastructure", kind="BASE_INFRASTRUCTURE"
            )
            regular_id = seed_site(conn, name="Library")

            uid = seed_user(conn, username="mystery", role="observer")
            seed_allowed_site(conn, user_id=uid, site_id=base_id)
            seed_allowed_site(conn, user_id=uid, site_id=regular_id)
    finally:
        engine.dispose()

    upgrade(url, REV_M2)

    engine = engine_for(url)
    try:
        with engine.connect() as conn:
            rows = conn.execute(sa.text(
                "SELECT site_id FROM role_assignments WHERE user_id = :u"
            ).bindparams(u=uid)).fetchall()
            grant_site_ids = {r[0] for r in rows}
            assert grant_site_ids == {regular_id}
            assert base_id not in grant_site_ids
    finally:
        engine.dispose()
