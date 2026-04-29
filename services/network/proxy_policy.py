import os


PROXY_ENV_KEYS = [
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
]


def disable_proxy_for_current_process():
    """
    当前 Python 进程内禁用代理。
    用于 AKShare / 国内行情源。
    """
    for key in PROXY_ENV_KEYS:
        os.environ.pop(key, None)

    os.environ["NO_PROXY"] = "*"
    os.environ["no_proxy"] = "*"


def apply_proxy_for_current_process(http_proxy_url: str | None = None):
    """
    当前 Python 进程内启用代理。
    用于 DeepSeek / 网页搜索等需要代理的模块。
    """
    if not http_proxy_url:
        return

    os.environ["HTTP_PROXY"] = http_proxy_url
    os.environ["HTTPS_PROXY"] = http_proxy_url
    os.environ["ALL_PROXY"] = http_proxy_url
    os.environ["http_proxy"] = http_proxy_url
    os.environ["https_proxy"] = http_proxy_url
    os.environ["all_proxy"] = http_proxy_url