"""Data coordinator for HostAPI."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

_LOGGER = logging.getLogger(__name__)

CONF_API_VERSION = "/api/v1"


class UpdateFailed(Exception):
    """Exception raised when data update fails."""
    pass


@dataclass
class HostAPIData:
    """Runtime data stored per config entry."""

    client: aiohttp.ClientSession
    coordinator: DataUpdateCoordinator
    host: str
    port: int
    api_token: str
    device_name: str | None = None
    service_coordinator: DataUpdateCoordinator | None = None
    ws_listener: object | None = None


class HostAPICoordinator(DataUpdateCoordinator):
    """Coordinates data fetching for a single hostapi instance."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: aiohttp.ClientSession,
    ) -> None:
        self.client = client
        self.entry = entry
        self._base_url = f"http://{entry.data.get('host')}:{entry.data.get('port')}"
        self._api_token = entry.data.get("api_key")

        super().__init__(
            hass,
            _LOGGER,
            name=f"hostapi_{entry.data.get('host')}",
            update_interval=timedelta(seconds=30),
        )

    @property
    def base_url(self) -> str:
        return self._base_url

    @property
    def api_headers(self) -> dict:
        return {"Authorization": f"Bearer {self._api_token}"}

    async def _async_update_data(self):
        """Fetch data from hostapi server."""
        url = f"{self._base_url}{CONF_API_VERSION}/info"
        try:
            async with self.client.get(url, headers=self.api_headers) as response:
                if response.status == 200:
                    return await response.json()
                elif response.status == 401:
                    raise UpdateFailed("Invalid API token")
                else:
                    raise UpdateFailed(f"HTTP {response.status}")
        except aiohttp.ClientError as e:
            raise UpdateFailed(f"Connection error: {e}") from e

    async def async_refresh(self):
        """Refresh data and notify listeners."""
        await super().async_refresh()

    async def async_request_refresh(self):
        """Request an async refresh at next opportunity."""
        await super().async_request_refresh()


class ServiceStateCoordinator(DataUpdateCoordinator):
    """Polls favorite/custom service states; ws events patch its data.

    One cheap REST call per interval for ALL managed services (instead of
    one call per switch entity every 30s). WebSocket push from hostapi
    patches the data in place via apply_service_state().
    """

    def __init__(self, hass, entry, client) -> None:
        self.client = client
        self.entry = entry
        self._base_url = f"http://{entry.data.get('host')}:{entry.data.get('port')}"
        self._api_token = entry.data.get("api_key")
        super().__init__(
            hass,
            _LOGGER,
            name=f"hostapi_services_{entry.data.get('host')}",
            update_interval=timedelta(seconds=300),
        )

    @property
    def base_url(self) -> str:
        return self._base_url

    @property
    def api_headers(self) -> dict:
        return {"Authorization": f"Bearer {self._api_token}"}

    async def _async_update_data(self):
        """Fetch managed service states (favorite + custom only)."""
        url = f"{self._base_url}/services/?managed=true"
        try:
            async with self.client.get(url, headers=self.api_headers) as response:
                if response.status == 200:
                    return await response.json()
                elif response.status == 401:
                    raise UpdateFailed("Invalid API token")
                else:
                    raise UpdateFailed(f"HTTP {response.status}")
        except aiohttp.ClientError as e:
            raise UpdateFailed(f"Connection error: {e}") from e

    def apply_service_state(self, service_name: str, active: bool) -> None:
        """Patch one service's state in place (ws push event)."""
        data = self.data or {"services": []}
        services = [dict(s) for s in data.get("services", [])]
        for svc in services:
            if svc.get("name") == service_name:
                svc["active"] = active
                break
        else:
            services.append({"name": service_name, "active": active})
        self.async_set_updated_data({"services": services})