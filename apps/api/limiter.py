"""Shared SlowAPI rate limiter configuration."""

import os

from slowapi import Limiter
from slowapi.util import get_remote_address


def _csv_env(name: str) -> set[str]:
    return {
        item.strip()
        for item in os.getenv(name, "").split(",")
        if item.strip()
    }


def _first_forwarded_ip(value: str | None) -> str | None:
    if not value:
        return None
    first = value.split(",", 1)[0].strip()
    return first or None


def rate_limit_key_func(request) -> str:
    """Return a rate-limit key, trusting forwarded headers only from known proxies."""
    remote_addr = get_remote_address(request)
    trusted_proxies = _csv_env("TRUSTED_PROXY_IPS")
    header_name = os.getenv("RATE_LIMIT_CLIENT_IP_HEADER", "").strip()

    if (
        header_name
        and remote_addr
        and (remote_addr in trusted_proxies or "*" in trusted_proxies)
    ):
        forwarded_ip = _first_forwarded_ip(request.headers.get(header_name))
        if forwarded_ip:
            return forwarded_ip

    return remote_addr or "unknown"


limiter = Limiter(key_func=rate_limit_key_func)
