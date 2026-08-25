"""Data coordinator for HostAPI."""

from __future__ import annotations

import logging
from dataclasses import dataclass
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
            update_interval=30,
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