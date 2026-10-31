import asyncio
import json
import uuid


class ConnectionStore:
    def __init__(self):
        self._connections: dict[uuid.UUID, list[asyncio.Queue]] = {}

    def add(self, user_id: uuid.UUID, queue: asyncio.Queue):
        if user_id not in self._connections:
            self._connections[user_id] = []
        self._connections[user_id].append(queue)

    def remove(self, user_id: uuid.UUID, queue: asyncio.Queue):
        if user_id in self._connections:
            if queue in self._connections[user_id]:
                self._connections[user_id].remove(queue)

            if not self._connections[user_id]:
                del self._connections[user_id]

    def get(self, user_id: uuid.UUID) -> list[asyncio.Queue]:
        return self._connections.get(user_id, [])


notification_store = ConnectionStore()


class SSEConnectionService:
    def __init__(self, store: ConnectionStore):
        self.store = store

    async def connect(self, user_id: uuid.UUID) -> asyncio.Queue:
        queue = asyncio.Queue()
        self.store.add(user_id, queue)
        return queue

    def disconnect(self, user_id: uuid.UUID, queue: asyncio.Queue) -> None:
        self.store.remove(user_id, queue)


class SSEService:
    def __init__(self, manager: SSEConnectionService):
        self.manager = manager

    async def stream(self, user_id, request):
        queue = await self.manager.connect(user_id)

        try:
            while True:
                if await request.is_disconnected():
                    break

                try:
                    data = await asyncio.wait_for(queue.get(), timeout=15)

                    yield {"event": "notification", "data": json.dumps(data)}

                except TimeoutError:
                    yield {"event": "ping", "data": "keep-alive"}

        finally:
            self.manager.disconnect(user_id, queue)
