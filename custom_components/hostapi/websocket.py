"""Live service-state push from hostapi over the /ws hub.

Push is an optimization only: on every (re)connect the caller takes a full
REST snapshot (via the on_message callback wiring), so no event can be
lost permanently. A 300s fallback poll continues regardless.
"""

import asyncio
import json
import logging

import aiohttp

_LOGGER = logging.getLogger(__name__)

BACKOFF_MIN = 5.0
BACKOFF_MAX = 60.0
HEARTBEAT = 30.0


class ServiceStateListener:
    """Holds a persistent /ws connection to hostapi, reconnecting on drops."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        ws_url: str,
        token: str,
        on_message,
    ) -> None:
        self._session = session
        self._ws_url = ws_url
        self._token = token
        self._on_message = on_message
        self._task: asyncio.Task | None = None
        self._closing = False

    async def start(self) -> None:
        self._closing = False
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        self._closing = True
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _run(self) -> None:
        backoff = BACKOFF_MIN
        while not self._closing:
            try:
                async with self._session.ws_connect(
                    self._ws_url,
                    headers={"Authorization": f"Bearer {self._token}"},
                    heartbeat=HEARTBEAT,
                ) as ws:
                    _LOGGER.debug("hostapi ws connected: %s", self._ws_url)
                    backoff = BACKOFF_MIN
                    self._on_message({"type": "_connected"})
                    async for msg in ws:
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            try:
                                self._on_message(json.loads(msg.data))
                            except (ValueError, KeyError) as e:
                                _LOGGER.debug("hostapi ws bad message: %s", e)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                _LOGGER.debug("hostapi ws error (%s): %s", self._ws_url, e)
            if self._closing:
                return
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, BACKOFF_MAX)

    def _dispatch(self, message: dict) -> None:
        self._on_message(message)
