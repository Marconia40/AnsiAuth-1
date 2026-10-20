import logging
import os
import threading
import time
import uuid
from contextlib import contextmanager

logger = logging.getLogger(__name__)

MAX_JOBS_PER_WINDOW: int = 30
WINDOW_SECONDS: float = 60.0
_REDIS_RECHECK_SECONDS: float = 30.0

DEVICE_LOCK_TTL_S: int = int(os.getenv("DEVICE_LOCK_TTL_S", "60"))
DEVICE_LOCK_RENEW_S: float = float(os.getenv("DEVICE_LOCK_RENEW_S", "20"))
DEVICE_LOCK_WAIT_S: float = float(os.getenv("DEVICE_LOCK_WAIT_S", "600"))
_ESPERA_POR_DEFECTO = object()

MAX_CONCURRENT_SSH: int = int(os.getenv("MAX_CONCURRENT_SSH", "20"))

SSH_SLOT_LEASE_S: float = 600.0

SSH_SLOT_POLL_INTERVAL_S: float = 0.2

_SSH_SLOT_KEY = "ssh_semaphore:slots"

_SSH_ACQUIRE_LUA = """
local now = tonumber(ARGV[1])
local ttl = tonumber(ARGV[2])
local maxn = tonumber(ARGV[3])
local slot_id = ARGV[4]

redis.call('ZREMRANGEBYSCORE', KEYS[1], 0, now - ttl)

local count = redis.call('ZCARD', KEYS[1])
if count >= maxn then
    return 0
end

redis.call('ZADD', KEYS[1], now, slot_id)
return 1
"""


class _RenovadorDeLock:
    def __init__(self, redis_lock, device_id: str, ttl: int, cada: float):
        self._lock = redis_lock
        self._device_id = device_id
        self._ttl = ttl
        self._cada = cada
        self._parar = threading.Event()
        self._hilo = threading.Thread(
            target=self._correr, name=f"device-lock-renew-{device_id}", daemon=True,
        )
        self.perdido = False

    def iniciar(self) -> None:
        self._hilo.start()

    def detener(self) -> None:
        self._parar.set()
        if self._hilo.is_alive():
            self._hilo.join(timeout=5)

    def _correr(self) -> None:
        from redis.exceptions import LockError

        while not self._parar.wait(self._cada):
            try:
                self._lock.extend(self._ttl, replace_ttl=True)
            except LockError:
                self.perdido = True
                logger.error(
                    "Device lock LOST device=%s: expired or taken by another worker while the "
                    "job was still running -- it no longer has exclusive access to the device",
                    self._device_id,
                )
                return
            except Exception as exc:
                logger.warning(
                    "Device lock renewal failed device=%s (%s), will retry", self._device_id, exc,
                )


class RedisCoordinator:
    def __init__(self, redis_url: str | None = None):
        self._redis_url = redis_url if redis_url is not None else os.getenv("REDIS_URL")
        self._redis_client = None
        self._last_check: float = 0.0
        self._locks: dict[str, threading.Lock] = {}
        self._device_timestamps: dict[str, list[float]] = {}
        self._meta_lock = threading.Lock()
        self._ssh_semaphore = threading.BoundedSemaphore(MAX_CONCURRENT_SSH)

    def _get_redis(self):
        if self._redis_client is not None:
            return self._redis_client
        now = time.time()
        if now - self._last_check < _REDIS_RECHECK_SECONDS:
            return None
        self._last_check = now
        if not self._redis_url:
            return None
        try:
            import redis as _redis
            r = _redis.from_url(self._redis_url, socket_connect_timeout=2)
            r.ping()
            self._redis_client = r
            logger.info("RedisCoordinator: using Redis at %s", self._redis_url)
            return r
        except Exception as exc:
            logger.warning("RedisCoordinator: Redis unavailable (%s), using in-process fallback", exc)
            return None

    def _get_inprocess_lock(self, device_id: str) -> threading.Lock:
        with self._meta_lock:
            if device_id not in self._locks:
                self._locks[device_id] = threading.Lock()
            return self._locks[device_id]


    @contextmanager
    def bloquear(self, device_id: str, timeout: "float | None | object" = _ESPERA_POR_DEFECTO):
        if timeout is _ESPERA_POR_DEFECTO:
            timeout = DEVICE_LOCK_WAIT_S
        r = self._get_redis()
        use_redis = False
        redis_lock = None

        if r is not None:
            try:
                redis_lock = r.lock(
                    f"device_lock:{device_id}", timeout=DEVICE_LOCK_TTL_S, thread_local=False,
                )
                logger.info("Waiting for device lock device=%s", device_id)
                acquired = redis_lock.acquire(blocking=True, blocking_timeout=timeout)
                if not acquired:
                    limit = f"{timeout}s" if timeout is not None else "the timeout"
                    raise TimeoutError(
                        f"Could not acquire device lock for '{device_id}' within {limit} — device busy"
                    )
                use_redis = True
                logger.info("Device lock acquired device=%s", device_id)
            except TimeoutError:
                raise
            except Exception as exc:
                logger.warning("Device lock: Redis acquisition failed (%s), using in-process", exc)
                redis_lock = None

        if use_redis:
            renovador = _RenovadorDeLock(redis_lock, device_id, DEVICE_LOCK_TTL_S, DEVICE_LOCK_RENEW_S)
            try:
                renovador.iniciar()
                yield
            finally:
                renovador.detener()
                try:
                    redis_lock.release()
                except Exception:
                    pass
                logger.info("Device lock released device=%s", device_id)
        else:
            lock = self._get_inprocess_lock(device_id)
            logger.info("Waiting for device lock device=%s", device_id)
            if timeout is not None:
                acquired = lock.acquire(timeout=timeout)
            else:
                lock.acquire()
                acquired = True
            if not acquired:
                raise TimeoutError(
                    f"Could not acquire device lock for '{device_id}' within {timeout}s — device busy"
                )
            logger.info("Device lock acquired device=%s", device_id)
            try:
                yield
            finally:
                lock.release()
                logger.info("Device lock released device=%s", device_id)

    def bloqueo_en_redis(self, device_id: str) -> "bool | None":
        r = self._get_redis()
        if r is None:
            return None
        try:
            return r.exists(f"device_lock:{device_id}") > 0
        except Exception as exc:
            logger.warning("Device lock check: Redis error (%s)", exc)
            return None

    def esta_ocupado(self, device_id: str) -> bool:
        r = self._get_redis()
        if r is not None:
            try:
                return r.exists(f"device_lock:{device_id}") > 0
            except Exception:
                pass
        lock = self._get_inprocess_lock(device_id)
        acquired = lock.acquire(blocking=False)
        if acquired:
            lock.release()
        return not acquired


    def limitar(self, device_id: str) -> None:
        r = self._get_redis()
        if r is not None:
            try:
                self._wait_redis(r, device_id)
                return
            except Exception as exc:
                logger.warning("Rate limiter: Redis error (%s), falling back to in-process", exc)
        self._wait_inprocess(device_id)

    def _wait_redis(self, r, device_id: str) -> None:
        key = f"rate_limit:{device_id}"
        while True:
            r.set(key, 0, ex=int(WINDOW_SECONDS), nx=True)
            count = r.incr(key)
            if count <= MAX_JOBS_PER_WINDOW:
                return
            r.decr(key)
            ttl = r.ttl(key)
            wait_time = max(ttl, 1) + 0.05
            logger.info("Rate limit: device=%s waiting %.2fs for slot", device_id, wait_time)
            time.sleep(wait_time)

    def _wait_inprocess(self, device_id: str) -> None:
        while True:
            now = time.time()
            with self._meta_lock:
                if device_id not in self._device_timestamps:
                    self._device_timestamps[device_id] = []
                cutoff = now - WINDOW_SECONDS
                self._device_timestamps[device_id] = [t for t in self._device_timestamps[device_id] if t > cutoff]
                if len(self._device_timestamps[device_id]) < MAX_JOBS_PER_WINDOW:
                    self._device_timestamps[device_id].append(now)
                    return
                oldest = min(self._device_timestamps[device_id])
                wait_time = (oldest + WINDOW_SECONDS) - now + 0.05
            logger.info("Rate limit: device=%s waiting %.2fs for slot", device_id, wait_time)
            time.sleep(max(wait_time, 0.05))

    def resetear(self, device_id: str | None = None) -> None:
        r = self._get_redis()
        if r is not None:
            try:
                if device_id:
                    r.delete(f"rate_limit:{device_id}")
                else:
                    for key in r.scan_iter("rate_limit:*"):
                        r.delete(key)
            except Exception:
                pass
        with self._meta_lock:
            if device_id:
                self._device_timestamps.pop(device_id, None)
            else:
                self._device_timestamps.clear()


    def hay_sync_pendiente(self, device_name: str, scope: str) -> bool:
        r = self._get_redis()
        if r is None:
            return False
        try:
            return bool(r.exists(f"sync_pending:{device_name}:{scope}"))
        except Exception as exc:
            logger.warning("Sync coalescing: Redis error (%s), assuming no pending", exc)
            return False

    def marcar_sync_pendiente(self, device_name: str, scope: str, ttl_s: int = 300) -> None:
        r = self._get_redis()
        if r is None:
            return
        try:
            r.set(f"sync_pending:{device_name}:{scope}", "1", ex=ttl_s)
        except Exception as exc:
            logger.warning("Sync coalescing: Redis error marking pending (%s)", exc)

    def reservar_sync(
        self, device_name: str, scope: str, task_id: str, ttl_s: int = 300,
    ) -> "str | None":
        r = self._get_redis()
        if r is None:
            return None
        key = f"sync_pending:{device_name}:{scope}"
        try:
            if r.set(key, task_id, ex=ttl_s, nx=True):
                return None
            existente = r.get(key)
        except Exception as exc:
            logger.warning("Sync coalescing: Redis error reserving (%s), no coalescing", exc)
            return None
        if existente is None:
            return self.reservar_sync(device_name, scope, task_id, ttl_s)
        return existente.decode() if isinstance(existente, bytes) else str(existente)

    def limpiar_sync_pendiente(self, device_name: str, scope: str) -> None:
        r = self._get_redis()
        if r is None:
            return
        try:
            r.delete(f"sync_pending:{device_name}:{scope}")
        except Exception as exc:
            logger.warning("Sync coalescing: Redis error clearing pending (%s)", exc)


    @contextmanager
    def adquirir_slot(self):
        r = self._get_redis()
        if r is not None:
            try:
                slot_id = self._acquire_ssh_slot_redis(r)
            except Exception as exc:
                logger.warning(
                    "SSH slot: Redis acquire failed (%s), falling back to in-process semaphore", exc,
                )
            else:
                try:
                    yield slot_id
                finally:
                    try:
                        r.zrem(_SSH_SLOT_KEY, slot_id)
                        logger.debug("SSH slot released slot_id=%s", slot_id)
                    except Exception as exc:
                        logger.warning(
                            "SSH slot release: Redis error (%s), slot will expire in %ss",
                            exc, SSH_SLOT_LEASE_S,
                        )
                return
        self._ssh_semaphore.acquire()
        logger.debug("SSH slot acquired (in-process fallback)")
        try:
            yield None
        finally:
            self._ssh_semaphore.release()
            logger.debug("SSH slot released (in-process fallback)")

    def _acquire_ssh_slot_redis(self, r) -> str:
        while True:
            slot_id = str(uuid.uuid4())
            now = time.time()
            acquired = r.eval(
                _SSH_ACQUIRE_LUA,
                1,
                _SSH_SLOT_KEY,
                now, SSH_SLOT_LEASE_S, MAX_CONCURRENT_SSH, slot_id,
            )
            if acquired == 1:
                logger.debug("SSH slot acquired slot_id=%s", slot_id)
                return slot_id
            time.sleep(SSH_SLOT_POLL_INTERVAL_S)
