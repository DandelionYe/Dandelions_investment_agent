"""速率限制器 — 供 main.py 和 auth router 共享使用，避免循环导入。"""

from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
