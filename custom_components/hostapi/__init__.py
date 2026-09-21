"""HostAPI custom component for Home Assistant."""

import logging

import aiohttp
from homeassistant.core import HomeAssistant

from .coordinator import HostAPICoordinator, HostAPIData, ServiceStateCoordinator
from .websocket import ServiceStateListener

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

    service_coordinator = ServiceStateCoordinator(hass, entry, client_session)

    entry.runtime_data = HostAPIData(
        client=client_session,
        coordinator=coordinator,
        host=entry.data.get("host"),
        port=entry.data.get("port"),
        api_token=entry.data.get("api_key"),
        device_name=device_name,
        service_coordinator=service_coordinator,
    )

    ha_url = entry.data.get("ha_url") or entry.options.get("ha_url")
    if ha_url:
        try:
            async with client_session.put(
                f"http://{entry.data.get('host')}:{entry.data.get('port')}/settings/os-switch",
                json={"ha_url": ha_url},
                headers={"Authorization": f"Bearer {entry.data.get('api_key')}"},
            ) as resp:
                _LOGGER.debug("HA URL synced to hostapi: %s", resp.status)
        except Exception as e:
            _LOGGER.warning("Failed to sync HA URL to hostapi: %s", e)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Live push: hybrid model - ws events patch the service coordinator in
    # place; on every (re)connect the coordinator takes a full REST
    # snapshot, and its 300s poll is the fallback safety net.
    def _on_ws_message(message: dict) -> None:
        mtype = message.get("type")
        if mtype == "service":
            service_coordinator.apply_service_state(
                message.get("name"), bool(message.get("active"))
            )
        elif mtype in ("_connected", "services_changed"):
            # (re)connected or the managed set changed: full REST snapshot
            service_coordinator.async_refresh()

    token = entry.data.get("api_key")
    listener = ServiceStateListener(
        session=client_session,
        ws_url=f"ws://{entry.data.get('host')}:{entry.data.get('port')}/ws?token={token}",
        token=token,
        on_message=_on_ws_message,
    )
    entry.runtime_data.ws_listener = listener
    await listener.start()

    return True


async def async_unload_entry(hass: HomeAssistant, entry) -> bool:
    """Unload a config entry."""
    listener = getattr(entry.runtime_data, "ws_listener", None)
    if listener is not None:
        await listener.stop()
    await entry.runtime_data.coordinator.async_shutdown()
    await entry.runtime_data.client.close()

    return await hass.config_entries.async_unload_entries(
        entry, PLATFORMS
    )


async def async_reconfigure_entry(hass: HomeAssistant, entry) -> bool:
    """Handle reconfiguration of a config entry."""
    await hass.config_entries.async_reload(entry.entry_id)
    return True