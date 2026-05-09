import os
import threading

PROXY_ENV_KEYS = [
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
]

_no_proxy_override = threading.local()


def _is_proxy_disabled_for_thread() -> bool:
    return getattr(_no_proxy_override, "active", False)


def disable_proxy_for_current_process():
    """
    当前线程内禁用代理。用于 AKShare / 国内行情源。

    注意：此函数修改 os.environ，在多线程环境下会影响所有线程。
    本项目 Celery 使用 --pool=solo 单线程模式，此限制不构成实际问题。
    """
    _no_proxy_override.active = True
    for key in PROXY_ENV_KEYS:
        os.environ.pop(key, None)
    os.environ["NO_PROXY"] = "*"
    os.environ["no_proxy"] = "*"


def apply_proxy_for_current_process(http_proxy_url: str | None = None):
    """
    当前线程内启用代理。用于 DeepSeek / 网页搜索等需要代理的模块。

    注意：此函数修改 os.environ，在多线程环境下会影响所有线程。
    本项目 Celery 使用 --pool=solo 单线程模式，此限制不构成实际问题。
    """
    if not http_proxy_url:
        return
    _no_proxy_override.active = False
    os.environ["HTTP_PROXY"] = http_proxy_url
    os.environ["HTTPS_PROXY"] = http_proxy_url
    os.environ["ALL_PROXY"] = http_proxy_url
    os.environ["http_proxy"] = http_proxy_url
    os.environ["https_proxy"] = http_proxy_url
    os.environ["all_proxy"] = http_proxy_url

    for key in ("NO_PROXY", "no_proxy"):
        os.environ.pop(key, None)