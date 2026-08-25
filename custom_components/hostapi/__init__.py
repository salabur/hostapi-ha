"""HostAPI custom component for Home Assistant."""

import logging

import aiohttp
from homeassistant.core import HomeAssistant

from .coordinator import HostAPICoordinator, HostAPIData

DOMAIN = "hostapi"

_LOGGER = logging.getLogger(__name__)


def get_device_info(entry) -> dict:
    """Return HA device info using the hostapi device name (hostname-os)."""
    return {
        "identifiers": {(DOMAIN, entry.entry_id)},
        "name": getattr(entry.runtime_data, "device_name", None)
        or f"HostAPI ({entry.data.get('host', 'unknown')})",
        "manufacturer": "HostAPI",
    }

PLATFORMS = ["sensor", "switch", "button", "select"]


async def async_setup(hass, config):
    return True


async def async_setup_entry(hass: HomeAssistant, entry) -> bool:
    """Set up a config entry."""
    client_session = aiohttp.ClientSession()

    coordinator = HostAPICoordinator(hass, entry, client_session)
    await coordinator.async_config_entry_first_refresh()

    device_name = None
    if coordinator.data:
        device_name = coordinator.data.get("device_name")

    entry.runtime_data = HostAPIData(
        client=client_session,
        coordinator=coordinator,
        host=entry.data.get("host"),
        port=entry.data.get("port"),
        api_token=entry.data.get("api_key"),
        device_name=device_name,
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry) -> bool:
    """Unload a config entry."""
    await entry.runtime_data.coordinator.async_shutdown()
    await entry.runtime_data.client.close()

    return await hass.config_entries.async_unload_entries(
        entry, PLATFORMS
    )


async def async_reconfigure_entry(hass: HomeAssistant, entry) -> bool:
    """Handle reconfiguration of a config entry."""
    await hass.config_entries.async_reload(entry.entry_id)
    return True