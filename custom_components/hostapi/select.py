"""Select platform for HostAPI."""

import logging

from homeassistant.components.select import SelectEntity
from homeassistant.const import CONF_HOST

from . import DOMAIN, get_device_info

CONF_API_VERSION = "/api/v1"

_LOGGER = logging.getLogger(__name__)


class HostAPIDisplayProfileSelect(SelectEntity):
    """Select entity to switch display profile."""

    def __init__(self, entry, profiles: list):
        self.entry = entry
        self._profiles = profiles
        self._attr_name = f"HostAPI ({entry.data.get(CONF_HOST)}) Display Profile"
        self._attr_unique_id = f"{entry.entry_id}_display_profile_select"
        self._attr_icon = "mdi:monitor"
        self._attr_options = profiles
        self._current = None

    @property
    def device_info(self) -> dict:
        return get_device_info(self.entry)

    @property
    def base_url(self) -> str:
        data = self.entry.runtime_data
        return f"http://{data.host}:{data.port}"

    @property
    def session(self):
        return self.entry.runtime_data.client

    @property
    def state(self) -> str:
        return self._current

    async def async_update(self):
        try:
            async with self.session.get(
                f"{self.base_url}{CONF_API_VERSION}/info",
                headers={"Authorization": f"Bearer {self.entry.runtime_data.api_token}"}
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    self._current = data.get("display_profile")
        except Exception as e:
            _LOGGER.error("Failed to update profile: %s", e)

    async def async_select_option(self, option: str):
        try:
            async with self.session.post(
                f"{self.base_url}/display-profiles/{option}/switch",
                headers={"Authorization": f"Bearer {self.entry.runtime_data.api_token}"}
            ) as response:
                if response.status == 200:
                    self._current = option
        except Exception as e:
            _LOGGER.error("Failed to switch profile: %s", e)


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up HostAPI select entities from config entry."""
    data = entry.runtime_data
    session = data.client
    base_url = f"http://{data.host}:{data.port}"
    headers = {"Authorization": f"Bearer {data.api_token}"}

    try:
        async with session.get(
            f"{base_url}{CONF_API_VERSION}/info",
            headers=headers
        ) as response:
            if response.status == 200:
                info = await response.json()
                profiles = info.get("available_profiles", [])
                if profiles:
                    async_add_entities([HostAPIDisplayProfileSelect(entry, profiles)])
    except Exception as e:
        _LOGGER.error("Failed to discover profiles: %s", e)