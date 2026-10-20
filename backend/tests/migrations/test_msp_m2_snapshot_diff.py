import sqlalchemy as sa

from tests.migrations.conftest import (
    REV_M2,
    engine_for,
    seed_allowed_site,
    seed_device,
    seed_site,
    seed_user,
    upgrade,
)


def _legacy_visible(conn, user_id: int) -> set[str]:
    allowed_ids = {
        r[0] for r in conn.execute(sa.text(
            "SELECT site_id FROM user_allowed_sites WHERE user_id = :u"
        ).bindparams(u=user_id)).fetchall()
    }
    if not allowed_ids:
        rows = conn.execute(sa.text(
            "SELECT name FROM devices WHERE site_id IS NULL"
        )).fetchall()
    else:
        placeholders = ",".join(f":s{i}" for i in range(len(allowed_ids)))
        bind = {f"s{i}": sid for i, sid in enumerate(allowed_ids)}
        rows = conn.execute(sa.text(
            f"SELECT name FROM devices WHERE site_id IN ({placeholders})"
        ).bindparams(**bind)).fetchall()
    return {r[0] for r in rows}


def _msp_visible(conn, user_id: int) -> set[str]:
    rows = conn.execute(sa.text("""
        SELECT DISTINCT d.name
          FROM devices d
          JOIN device_groups g ON g.id = d.device_group_id
          JOIN role_assignments ra ON ra.site_id = g.site_id
         WHERE ra.user_id = :u
           AND ra.device_group_id IS NULL
    """).bindparams(u=user_id)).fetchall()
    return {r[0] for r in rows}


def test_snapshot_diff_matches_for_users_with_allowed_sites(db_at_m1):
    url = db_at_m1

    engine = engine_for(url)
    try:
        with engine.begin() as conn:
            library_id = seed_site(conn, name="Library")
            dc_id = seed_site(conn, name="Datacenter")
            warehouse_id = seed_site(conn, name="Warehouse")

            seed_device(conn, name="lib_1", site_id=library_id)
            seed_device(conn, name="lib_2", site_id=library_id)
            seed_device(conn, name="dc_1", site_id=dc_id)
            seed_device(conn, name="dc_2", site_id=dc_id)
            seed_device(conn, name="wh_1", site_id=warehouse_id)

            obs_id = seed_user(conn, username="juan", role="observer")
            seed_allowed_site(conn, user_id=obs_id, site_id=library_id)

            op_id = seed_user(conn, username="rita", role="operator")
            seed_allowed_site(conn, user_id=op_id, site_id=library_id)
            seed_allowed_site(conn, user_id=op_id, site_id=dc_id)

            wh_obs_id = seed_user(conn, username="dana", role="observer")
            seed_allowed_site(conn, user_id=wh_obs_id, site_id=warehouse_id)
    finally:
        engine.dispose()

    engine = engine_for(url)
    try:
        with engine.connect() as conn:
            legacy = {
                uid: _legacy_visible(conn, uid)
                for uid in (obs_id, op_id, wh_obs_id)
            }
    finally:
        engine.dispose()

    upgrade(url, REV_M2)

    engine = engine_for(url)
    try:
        with engine.connect() as conn:
            new = {
                uid: _msp_visible(conn, uid)
                for uid in (obs_id, op_id, wh_obs_id)
            }
    finally:
        engine.dispose()

    for uid in (obs_id, op_id, wh_obs_id):
        assert legacy[uid] == new[uid], (
            f"visibility mismatch for user_id={uid}: "
            f"legacy={legacy[uid]}, new={new[uid]}"
        )


def test_snapshot_diff_users_on_fallback_lose_visibility(db_at_m1):
    url = db_at_m1

    engine = engine_for(url)
    try:
        with engine.begin() as conn:
            seed_device(conn, name="unassigned_1", site_id=None)
            seed_device(conn, name="unassigned_2", site_id=None)
            drifter_id = seed_user(conn, username="drifter", role="observer")
    finally:
        engine.dispose()

    engine = engine_for(url)
    try:
        with engine.connect() as conn:
            legacy = _legacy_visible(conn, drifter_id)
            assert legacy == {"unassigned_1", "unassigned_2"}
    finally:
        engine.dispose()

    upgrade(url, REV_M2)

    engine = engine_for(url)
    try:
        with engine.connect() as conn:
            new = _msp_visible(conn, drifter_id)
            assert new == set()

            flag = conn.execute(sa.text(
                "SELECT is_system_admin FROM users WHERE id = :u"
            ).bindparams(u=drifter_id)).scalar()
            assert bool(flag) is False
    finally:
        engine.dispose()
