import sqlalchemy as sa

from tests.migrations.conftest import (
    REV_M2,
    engine_for,
    seed_device,
    seed_site,
    upgrade,
)


def test_verification_raises_on_orphaned_device(db_at_m1):
    url = db_at_m1

    engine = engine_for(url)
    try:
        with engine.begin() as conn:
            library_id = seed_site(conn, name="Library")
            seed_device(conn, name="lib_1", site_id=library_id)
    finally:
        engine.dispose()

    upgrade(url, REV_M2)

    engine = engine_for(url)
    try:
        with engine.begin() as conn:
            conn.execute(sa.text(
                "UPDATE devices SET device_group_id = NULL WHERE name = 'lib_1'"
            ))
    finally:
        engine.dispose()

    import importlib.util
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    path = root / "migrations" / "versions" / "e2msp2_msp_backfill.py"
    spec = importlib.util.spec_from_file_location("msp_backfill_mod", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)

    engine = engine_for(url)
    try:
        with engine.connect() as conn:
            import pytest
            with pytest.raises(RuntimeError, match="device_group_id"):
                mod._assert_zero(
                    conn,
                    "SELECT COUNT(*) FROM devices WHERE device_group_id IS NULL",
                    "devices with no device_group_id",
                )
    finally:
        engine.dispose()
