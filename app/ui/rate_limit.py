"""
In-memory per-IP rate limiter (sliding window) untuk endpoint dashboard API.

Desain:
- Sliding window dengan deque timestamp per kunci (IP / route).
- State disimpan di memori proses — cukup untuk deployment single-node
  (deployment multi-node dapat memakai Redis, lihat settings.redis_url).
- Batas dikonfigurasi lewat settings.dashboard_rate_limit (0 = nonaktif)
  dan settings.dashboard_rate_limit_window (detik).
- Satu instance limiter per path endpoint sehingga endpoint yang berbeda
  tidak saling menghabiskan kuota.
"""
import math
import time
from collections import defaultdict, deque
from typing import Deque, Dict, Tuple

from fastapi import HTTPException, Request

from app.config import get_settings

# Batas jumlah IP yang dilacak agar memory aman dari spoofed-IP flood
_MAX_TRACKED_KEYS = 10_000


class RateLimiter:
    """Sliding-window rate limiter sederhana berbasis memori."""

    def __init__(self, max_requests: int, window_seconds: float):
        self.max_requests = int(max_requests)
        self.window_seconds = float(window_seconds)
        self._hits: Dict[str, Deque[float]] = defaultdict(deque)

    def check(self, key: str) -> Tuple[bool, float]:
        """Cat satu hit untuk `key`.

        Returns:
            (allowed, retry_after_seconds)
            - allowed=True  -> request diterima (hit sudah dicatat)
            - allowed=False -> melebihi kuota; retry_after berisi sisa detik
              (dibulatkan ke atas, minimal 1) untuk header Retry-After.
        """
        # 0 / nilai negatif = limiter nonaktif
        if self.max_requests <= 0 or self.window_seconds <= 0:
            return True, 0.0

        now = time.monotonic()
        hits = self._hits[key]

        # Buang entri di luar window
        while hits and now - hits[0] >= self.window_seconds:
            hits.popleft()

        if len(hits) >= self.max_requests:
            retry_after = max(1, math.ceil(self.window_seconds - (now - hits[0])))
            return False, float(retry_after)

        hits.append(now)

        # Cegah memory tumbuh tanpa batas dari banyak IP berbeda
        if len(self._hits) > _MAX_TRACKED_KEYS:
            self._evict_stale(now)

        return True, 0.0

    def _evict_stale(self, now: float) -> None:
        """Hapus bucket kosong / kadaluarsa saat jumlah key terlalu banyak."""
        stale = [
            k for k, v in self._hits.items()
            if not v or now - v[-1] >= self.window_seconds
        ]
        for k in stale:
            self._hits.pop(k, None)
        # Jika masih kelebihan (semua bucket aktif), buang yang terlama
        if len(self._hits) > _MAX_TRACKED_KEYS:
            ordered = sorted(self._hits.items(), key=lambda kv: kv[1][-1])
            for k, _ in ordered[: len(self._hits) - _MAX_TRACKED_KEYS]:
                self._hits.pop(k, None)

    def reset(self) -> None:
        """Kosongkan semua state (untuk testing / admin reset)."""
        self._hits.clear()


# Satu limiter per path endpoint (diisi lazy oleh dependency)
_limiters: Dict[str, RateLimiter] = {}


def get_limiter(route_path: str) -> RateLimiter:
    """Ambil (atau buat) limiter untuk satu path endpoint."""
    limiter = _limiters.get(route_path)
    if limiter is None:
        settings = get_settings()
        limiter = RateLimiter(
            max_requests=settings.dashboard_rate_limit,
            window_seconds=settings.dashboard_rate_limit_window,
        )
        _limiters[route_path] = limiter
    return limiter


def reset_all_limiters() -> None:
    """Reset seluruh limiter (dipakai test suite agar antar-test bersih)."""
    _limiters.clear()


def _client_ip(request: Request) -> str:
    """Ambil IP klien; hormati X-Forwarded-For bila ada reverse proxy."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        # Format: "client, proxy1, proxy2" -> ambil yang pertama
        first = forwarded.split(",")[0].strip()
        if first:
            return first
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


async def rate_limit_dependency(request: Request) -> None:
    """FastAPI dependency: batasi rate per-IP untuk endpoint /api/*.

    Dipasang bersama require_api_key pada setiap route /api/*.
    melebihi kuota -> HTTP 429 + header Retry-After.
    """
    route = request.scope.get("route")
    route_path = getattr(route, "path", request.url.path)

    limiter = get_limiter(route_path)
    allowed, retry_after = limiter.check(_client_ip(request))
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded. Slow down and retry shortly.",
            headers={"Retry-After": str(int(retry_after))},
        )
