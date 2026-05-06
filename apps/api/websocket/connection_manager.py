"""WebSocket 连接管理器。

管理活跃的 WebSocket 连接，支持按频道广播消息。
在本架构中作为备选方案保留 — 主路径为 Redis Pub/Sub 直连。
"""

from fastapi import WebSocket


class ConnectionManager:
    """管理活跃的 WebSocket 连接，按频道分组。"""

    def __init__(self):
        self._connections: dict[str, set[WebSocket]] = {}

    async def connect(self, channel: str, websocket: WebSocket) -> None:
        """接受 WebSocket 连接并注册到频道。"""
        await websocket.accept()
        self._connections.setdefault(channel, set()).add(websocket)

    def disconnect(self, channel: str, websocket: WebSocket) -> None:
        """从频道中移除 WebSocket 连接。"""
        if channel in self._connections:
            self._connections[channel].discard(websocket)
            if not self._connections[channel]:
                del self._connections[channel]

    async def broadcast(self, channel: str, message: dict) -> None:
        """向订阅了指定频道的所有客户端推送 JSON 消息。"""
        for ws in self._connections.get(channel, set()).copy():
            try:
                await ws.send_json(message)
            except Exception:
                self.disconnect(channel, ws)

    @property
    def active_channels(self) -> list[str]:
        """返回当前有活跃连接的频道列表。"""
        return list(self._connections.keys())

    @property
    def connection_count(self) -> int:
        """返回所有频道的连接总数。"""
        return sum(len(v) for v in self._connections.values())


# 模块级单例
manager = ConnectionManager()
