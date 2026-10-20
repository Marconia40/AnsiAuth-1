import os
import threading
import time

import pytest

from app.services import redis_coordinator as rc_module
from app.services.redis_coordinator import RedisCoordinator


def _fresh_coordinator_no_redis() -> RedisCoordinator:
    return RedisCoordinator(redis_url="")


def test_ssh_semaphore_permits_up_to_max_concurrent():
    coord = _fresh_coordinator_no_redis()
    n = rc_module.MAX_CONCURRENT_SSH

    inside = 0
    max_inside = 0
    lock = threading.Lock()
    barrier = threading.Barrier(n)
    release = threading.Event()

    def worker():
        nonlocal inside, max_inside
        with coord.adquirir_slot():
            barrier.wait(timeout=5)
            with lock:
                inside += 1
                if inside > max_inside:
                    max_inside = inside
            release.wait(timeout=5)
            with lock:
                inside -= 1

    threads = [threading.Thread(target=worker) for _ in range(n)]
    for t in threads:
        t.start()
    time.sleep(0.3)
    release.set()
    for t in threads:
        t.join(timeout=5)

    assert max_inside == n, f"Expected all {n} workers concurrent, saw peak={max_inside}"


def test_ssh_semaphore_blocks_beyond_max():
    coord = _fresh_coordinator_no_redis()
    n = rc_module.MAX_CONCURRENT_SSH

    holders_started = threading.Barrier(n + 1)
    release_holders = threading.Event()

    def holder():
        with coord.adquirir_slot():
            holders_started.wait(timeout=5)
            release_holders.wait(timeout=10)

    holder_threads = [threading.Thread(target=holder) for _ in range(n)]
    for t in holder_threads:
        t.start()
    holders_started.wait(timeout=5)

    extra_acquired = threading.Event()

    def extra():
        with coord.adquirir_slot():
            extra_acquired.set()

    extra_thread = threading.Thread(target=extra)
    extra_thread.start()

    assert not extra_acquired.wait(timeout=0.4), (
        "Semaphore let a caller through when all slots were held"
    )

    release_holders.set()
    for t in holder_threads:
        t.join(timeout=5)
    assert extra_acquired.wait(timeout=5), (
        "Extra caller never got a slot after holders released"
    )
    extra_thread.join(timeout=5)


def test_ssh_semaphore_releases_on_exception():
    coord = _fresh_coordinator_no_redis()
    n = rc_module.MAX_CONCURRENT_SSH

    for _ in range(n * 2):
        with pytest.raises(RuntimeError, match="boom"):
            with coord.adquirir_slot():
                raise RuntimeError("boom")

    got = threading.Event()

    def probe():
        with coord.adquirir_slot():
            got.set()

    t = threading.Thread(target=probe)
    t.start()
    assert got.wait(timeout=2), "Semaphore was not released after exception in with-block"
    t.join(timeout=2)


@pytest.mark.skipif(
    not os.getenv("REDIS_URL"),
    reason="Redis-path test requires REDIS_URL to be set",
)
def test_ssh_semaphore_redis_path_permits_and_releases():
    coord = RedisCoordinator()
    r = coord._get_redis()
    assert r is not None, "REDIS_URL set but coordinator couldn't reach Redis"
    r.delete(rc_module._SSH_SLOT_KEY)

    with coord.adquirir_slot() as slot_id:
        assert slot_id is not None
        assert r.zcard(rc_module._SSH_SLOT_KEY) == 1

    assert r.zcard(rc_module._SSH_SLOT_KEY) == 0

    with coord.adquirir_slot():
        assert r.zcard(rc_module._SSH_SLOT_KEY) == 1
    assert r.zcard(rc_module._SSH_SLOT_KEY) == 0


@pytest.mark.skipif(
    not os.getenv("REDIS_URL"),
    reason="Redis-path test requires REDIS_URL to be set",
)
def test_ssh_semaphore_redis_reclaims_expired_leases(monkeypatch):
    coord = RedisCoordinator()
    r = coord._get_redis()
    assert r is not None
    r.delete(rc_module._SSH_SLOT_KEY)

    stale_ts = time.time() - (rc_module.SSH_SLOT_LEASE_S + 60)
    for i in range(rc_module.MAX_CONCURRENT_SSH):
        r.zadd(rc_module._SSH_SLOT_KEY, {f"stale-{i}": stale_ts})
    assert r.zcard(rc_module._SSH_SLOT_KEY) == rc_module.MAX_CONCURRENT_SSH

    got = threading.Event()

    def probe():
        with coord.adquirir_slot():
            got.set()

    t = threading.Thread(target=probe)
    t.start()
    assert got.wait(timeout=3), "Acquire didn't reclaim expired leases"
    t.join(timeout=3)

    r.delete(rc_module._SSH_SLOT_KEY)
