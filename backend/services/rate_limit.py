from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException, Request

try:
    import redis
except Exception:  # pragma: no cover
    redis = None


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(raw.strip())
    except ValueError:
        return default
    return max(minimum, min(maximum, value))


def _sanitize_token(value: str, fallback: str) -> str:
    if not value:
        return fallback
    normalized = value.strip()
    if not normalized:
        return fallback
    if re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", normalized):
        return normalized
    digest = hashlib.sha1(normalized.encode("utf-8")).hexdigest()
    return digest[:24]


def _hash_short(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:24]


@dataclass(frozen=True)
class RateLimitSettings:
    enabled: bool
    redis_url: str
    session_chat_limit: int
    session_analysis_limit: int
    device_daily_limit: int
    ip_daily_limit: int


def get_rate_limit_settings() -> RateLimitSettings:
    legacy_session_limit = _env_int("APP_SESSION_REQUEST_LIMIT", 3, 1, 50)
    return RateLimitSettings(
        enabled=_env_bool("APP_RATE_LIMIT_ENABLED", True),
        redis_url=os.getenv("REDIS_URL", "redis://localhost:6379/0"),
        session_chat_limit=_env_int("APP_SESSION_CHAT_LIMIT", legacy_session_limit, 1, 50),
        session_analysis_limit=_env_int("APP_SESSION_ANALYSIS_LIMIT", legacy_session_limit, 1, 50),
        device_daily_limit=_env_int("APP_DEVICE_DAILY_LIMIT", 10, 1, 5000),
        ip_daily_limit=_env_int("APP_IP_DAILY_LIMIT", 200, 1, 20000),
    )


def _utc_day_key() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d")


def _seconds_until_utc_midnight() -> int:
    now = datetime.now(timezone.utc)
    tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    remaining = int((tomorrow - now).total_seconds())
    return max(60, remaining)


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "").strip()
    if forwarded:
        first = forwarded.split(",")[0].strip()
        if first:
            return _sanitize_token(first, "unknown-ip")
    if request.client and request.client.host:
        return _sanitize_token(request.client.host, "unknown-ip")
    return "unknown-ip"


def _identity_tokens(request: Request) -> tuple[str, str, str]:
    ip = _client_ip(request)
    ua = request.headers.get("user-agent", "").strip().lower()
    default_fingerprint = _hash_short(f"fp|{ip}|{ua}")
    default_session = _hash_short(f"sess|{ip}|{ua}")

    device_fp = _sanitize_token(
        request.headers.get("x-device-fingerprint", ""),
        default_fingerprint,
    )
    session_id = _sanitize_token(
        request.headers.get("x-session-id", ""),
        default_session,
    )
    return ip, device_fp, session_id


class RedisRateLimiter:
    def __init__(self) -> None:
        self._redis = None

    def _get_redis(self):
        if redis is None:
            return None
        if self._redis is not None:
            return self._redis
        settings = get_rate_limit_settings()
        try:
            self._redis = redis.Redis.from_url(
                settings.redis_url,
                decode_responses=True,
                socket_connect_timeout=1,
                socket_timeout=1,
            )
        except Exception:
            self._redis = None
        return self._redis

    def _reset_at_from_ttl(self, ttl_seconds: int) -> str:
        return (datetime.now(timezone.utc) + timedelta(seconds=max(0, ttl_seconds))).isoformat()

    def _check_counter(self, key: str, limit: int, ttl_seconds: int, limit_type: str) -> None:
        rds = self._get_redis()
        if rds is None:
            return
        try:
            current = int(rds.incr(key))
            if current == 1:
                rds.expire(key, ttl_seconds)
            if current > limit:
                ttl = int(rds.ttl(key))
                effective_ttl = ttl if ttl > 0 else ttl_seconds
                raise HTTPException(
                    status_code=429,
                    detail={
                        "code": "RATE_LIMIT_EXCEEDED",
                        "limit_type": limit_type,
                        "message": "Usage quota exhausted.",
                        "limit": limit,
                        "used": max(limit, current),
                        "remaining": 0,
                        "remaining_today": 0,
                        "reset_at": self._reset_at_from_ttl(effective_ttl),
                    },
                )
        except HTTPException:
            raise
        except Exception:
            # Fail-open if Redis is temporarily unavailable.
            return

    def _session_limit_for_bucket(self, settings: RateLimitSettings, session_bucket: str) -> int:
        normalized = session_bucket.strip().lower()
        if normalized == "analysis":
            return settings.session_analysis_limit
        return settings.session_chat_limit

    def _read_counter(self, key: str) -> int:
        rds = self._get_redis()
        if rds is None:
            return 0
        try:
            raw = rds.get(key)
            return int(raw) if raw is not None else 0
        except Exception:
            return 0

    def usage_snapshot(self, request: Request, scope: str = "interactive") -> dict[str, Any]:
        settings = get_rate_limit_settings()
        day_key = _utc_day_key()
        day_ttl = _seconds_until_utc_midnight()
        ip, device_fp, session_id = _identity_tokens(request)

        ip_key = f"rl:{scope}:ip:{day_key}:{ip}"
        dev_key = f"rl:{scope}:device:{day_key}:{device_fp}"
        sess_chat_key = f"rl:{scope}:session:chat:{session_id}"
        sess_analysis_key = f"rl:{scope}:session:analysis:{session_id}"

        used_ip = self._read_counter(ip_key)
        used_device = self._read_counter(dev_key)
        used_session_chat = self._read_counter(sess_chat_key)
        used_session_analysis = self._read_counter(sess_analysis_key)

        rds = self._get_redis()
        sess_chat_ttl = 24 * 3600
        sess_analysis_ttl = 24 * 3600
        if rds is not None:
            try:
                ttl_chat = int(rds.ttl(sess_chat_key))
                if ttl_chat > 0:
                    sess_chat_ttl = ttl_chat
                ttl_analysis = int(rds.ttl(sess_analysis_key))
                if ttl_analysis > 0:
                    sess_analysis_ttl = ttl_analysis
            except Exception:
                pass

        return {
            "session_chat_remaining": max(0, settings.session_chat_limit - used_session_chat),
            "session_analysis_remaining": max(0, settings.session_analysis_limit - used_session_analysis),
            "device_daily_remaining": max(0, settings.device_daily_limit - used_device),
            "ip_daily_remaining": max(0, settings.ip_daily_limit - used_ip),
            "today_remaining": max(0, settings.device_daily_limit - used_device),
            "session_chat_used": used_session_chat,
            "session_analysis_used": used_session_analysis,
            "device_daily_used": used_device,
            "ip_daily_used": used_ip,
            "session_chat_reset_at": self._reset_at_from_ttl(sess_chat_ttl),
            "session_analysis_reset_at": self._reset_at_from_ttl(sess_analysis_ttl),
            "day_reset_at": self._reset_at_from_ttl(day_ttl),
        }

    def enforce(self, request: Request, scope: str = "interactive", session_bucket: str = "chat") -> None:
        settings = get_rate_limit_settings()
        if not settings.enabled:
            return

        day_key = _utc_day_key()
        day_ttl = _seconds_until_utc_midnight()
        ip, device_fp, session_id = _identity_tokens(request)

        self._check_counter(
            key=f"rl:{scope}:ip:{day_key}:{ip}",
            limit=settings.ip_daily_limit,
            ttl_seconds=day_ttl,
            limit_type="ip_daily",
        )
        self._check_counter(
            key=f"rl:{scope}:device:{day_key}:{device_fp}",
            limit=settings.device_daily_limit,
            ttl_seconds=day_ttl,
            limit_type="device_daily",
        )
        self._check_counter(
            key=f"rl:{scope}:session:{session_bucket}:{session_id}",
            limit=self._session_limit_for_bucket(settings, session_bucket),
            ttl_seconds=24 * 3600,
            limit_type=f"session_{session_bucket}",
        )


_RATE_LIMITER = RedisRateLimiter()


def enforce_rate_limits(request: Request, scope: str = "interactive", session_bucket: str = "chat") -> None:
    _RATE_LIMITER.enforce(request=request, scope=scope, session_bucket=session_bucket)


def get_rate_limit_usage(request: Request, scope: str = "interactive") -> dict[str, Any]:
    return _RATE_LIMITER.usage_snapshot(request=request, scope=scope)
