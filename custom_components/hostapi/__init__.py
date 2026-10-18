"""HostAPI custom component for Home Assistant."""

import logging
from dataclasses import dataclass

import aiohttp
import voluptuous as vol
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv

from .coordinator import HostAPICoordinator, HostAPIData, ServiceStateCoordinator
from .host_coordinator import HostEntryData, HostStateCoordinator
from .websocket import ServiceStateListener

DOMAIN = "hostapi"

_LOGGER = logging.getLogger(__name__)

KIND_HOSTAPI = "hostapi"
KIND_HOST = "host"
KIND_OPNSENSE = "opnsense"
OPNSENSE_CACHE_KEY = "opnsense_config"


@dataclass
class OpnsenseData:
    """Global OPNsense Wake-on-LAN settings."""

    url: str = ""
    api_key: str = ""
    api_secret: str = ""
    interface: str = ""
    verify_ssl: bool = True


def _walk_opnsense_config(hass: HomeAssistant) -> OpnsenseData | None:
    """Resolve the global OPNsense config by walking the entries."""
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.disabled_by:
            continue
        if entry.data.get("kind") != KIND_OPNSENSE:
            continue
        merged = {**entry.data, **entry.options}
        return OpnsenseData(
            url=merged.get("opnsense_url", ""),
            api_key=merged.get("opnsense_api_key", ""),
            api_secret=merged.get("opnsense_api_secret", ""),
            interface=merged.get("opnsense_interface", ""),
            verify_ssl=merged.get("opnsense_verify_ssl", True),
        )
    return None


def async_get_opnsense_config(hass: HomeAssistant) -> OpnsenseData | None:
    """Return the global OPNsense config, if a kind=opnsense entry exists.

    Cached in hass.data (written by the opnsense entry's setup, which
    re-runs on every reload) because ``available`` is polled per entity
    per refresh; the entry walk is the fallback.
    """
    cached = None
    store = hass.data.get(DOMAIN)
    if isinstance(store, dict):
        cached = store.get(OPNSENSE_CACHE_KEY)
    if cached is not None:
        return cached
    return _walk_opnsense_config(hass)


def _set_opnsense_cache(hass, config: OpnsenseData | None) -> None:
    store = hass.data.setdefault(DOMAIN, {})
    if config is None:
        store.pop(OPNSENSE_CACHE_KEY, None)
    else:
        store[OPNSENSE_CACHE_KEY] = config


def get_device_info(entry) -> dict:
    """Return HA device info using the hostapi device name (hostname-os)."""
    if entry.data.get("kind") == KIND_HOST:
        name = entry.data.get("name") or f"Host ({entry.data.get('host')})"
    else:
        name = (getattr(entry.runtime_data, "device_name", None)
                or f"HostAPI ({entry.data.get('host', 'unknown')})")
    return {
        "identifiers": {(DOMAIN, entry.entry_id)},
        "name": name,
        "manufacturer": "HostAPI",
    }

PLATFORMS = ["sensor", "switch", "button", "select"]
HOST_PLATFORMS = ["binary_sensor", "sensor", "button"]


async def async_setup(hass, config):
    """Set up integration-level services."""
    _register_run_command_service(hass)
    return True


def _register_run_command_service(hass) -> None:
    from .ssh_client import SSHResult

    async def _handle_run_command(call) -> None:
        """Run one SSH command on a generic host entry."""
        entry = hass.config_entries.async_get_entry(call.data["entry_id"])
        if entry is None or entry.data.get("kind") != KIND_HOST:
            _LOGGER.warning(
                "run_command: no generic host entry %s",
                call.data["entry_id"])
            return
        coordinator = getattr(entry.runtime_data, "coordinator", None)
        if coordinator is None:
            _LOGGER.warning(
                "run_command: entry %s is not loaded", entry.entry_id)
            return
        result: SSHResult = await coordinator.ssh.run(call.data["command"])
        if not result.ok:
            _LOGGER.error(
                "run_command on %s failed: %s",
                entry.data.get("host"),
                result.error or result.stderr)
        elif result.stderr.strip():
            _LOGGER.info(
                "run_command on %s finished with stderr: %s",
                entry.data.get("host"), result.stderr)

    hass.services.async_register(
        DOMAIN, "run_command", _handle_run_command,
        schema=vol.Schema({
            vol.Required("entry_id"): cv.string,
            vol.Required("command"): cv.string,
        }),
    )


async def async_migrate_entry(hass, entry) -> bool:
    """Migrate pre-v2 config entries.

    The flow declares VERSION = 2 (since 0.4.5, for sub-entry support)
    but entries created by older flows are version 1 with an unchanged
    data layout - without this handler their setup fails with
    "Migration handler not found".
    """
    if entry.version > 2:
        return False
    if entry.version < 2:
        hass.config_entries.async_update_entry(
            entry, version=2, minor_version=1)
    return True


async def _async_reload_entry(hass, entry) -> None:
    """Reload the entry when its data/options/sub-entries change.

    Update listeners must be coroutine functions (HA wraps them in
    ``async_create_task``), but ``async_schedule_reload`` itself is a
    synchronous callback - awaiting it was ``await None``. It also
    coalesces the double fire from a reconfigure (reload helper +
    update listener).
    """
    hass.config_entries.async_schedule_reload(entry.entry_id)


async def async_setup_entry(hass: HomeAssistant, entry) -> bool:
    """Set up a config entry."""
    if entry.data.get("kind") == KIND_OPNSENSE:
        # Config-only entry: it stores the global OPNsense settings that the
        # wake buttons of every host read; no entities, no platforms.
        # Compute fresh (the cache would be the pre-reload value).
        entry.runtime_data = _walk_opnsense_config(hass) or OpnsenseData()
        _set_opnsense_cache(hass, entry.runtime_data)
        return True

    client_session = aiohttp.ClientSession()

    try:
        return await _async_setup_network_entry(hass, entry, client_session)
    except Exception:
        # HA retries the setup; without closing here every retry leaks
        # another ClientSession.
        await client_session.close()
        raise


async def _async_setup_network_entry(hass, entry, client_session) -> bool:
    """Set up the networked entry kinds (host + hostapi)."""

    if entry.data.get("kind") == KIND_HOST:
        coordinator = HostStateCoordinator(hass, entry, client_session)
        entry.runtime_data = HostEntryData(
            client=client_session, coordinator=coordinator)
        await coordinator.async_config_entry_first_refresh()
        await hass.config_entries.async_forward_entry_setups(
            entry, HOST_PLATFORMS)
        # Command sub-entries added/removed/reconfigured at runtime fire the
        # entry's update listeners; reload so the button set matches. This is
        # why host entries use the plain OptionsFlow (no OptionsFlowWithReload).
        entry.async_on_unload(
            entry.add_update_listener(_async_reload_entry))
        return True

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
            hass.async_create_task(service_coordinator.async_refresh())

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
    if entry.data.get("kind") == KIND_OPNSENSE:
        _set_opnsense_cache(hass, None)
        return True
    platforms = (HOST_PLATFORMS
                 if entry.data.get("kind") == KIND_HOST else PLATFORMS)
    listener = getattr(entry.runtime_data, "ws_listener", None)
    if listener is not None:
        await listener.stop()
    await entry.runtime_data.coordinator.async_shutdown()
    await entry.runtime_data.client.close()

    return await hass.config_entries.async_unload_platforms(
        entry, platforms
    )


async def async_reconfigure_entry(hass: HomeAssistant, entry) -> bool:
    """Handle reconfiguration of a config entry."""
    await hass.config_entries.async_reload(entry.entry_id)
    return True