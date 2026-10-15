"""Button platform for HostAPI."""

import json
import logging

import aiohttp
from homeassistant.components.button import ButtonEntity
from homeassistant.helpers import entity_registry as er

from . import get_device_info

CONF_API_VERSION = "/api/v1"

_LOGGER = logging.getLogger(__name__)


class HostAPIButtonEntity(ButtonEntity):
    """Button to run a script."""

    def __init__(self, entry, script_name: str):
        self.entry = entry
        self._script_name = script_name
        self._attr_name = f"Run {script_name}"
        self._attr_unique_id = f"{entry.entry_id}_script_{script_name}"
        self._attr_icon = "mdi:play"

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

    async def async_press(self):
        try:
            async with self.session.post(
                f"{self.base_url}/scripts/run/{self._script_name}",
                json={},
                headers={"Authorization": f"Bearer {self.entry.runtime_data.api_token}"}
            ):
                pass
        except Exception as e:
            _LOGGER.error("Failed to run script %s: %s", self._script_name, e)


class HostAPIRestartServiceButton(ButtonEntity):
    """Button to restart a systemd service (opt-in via HA entity shape)."""

    def __init__(self, entry, service_name: str):
        self.entry = entry
        self._service_name = service_name
        self._attr_name = f"Restart {service_name}"
        self._attr_unique_id = f"{entry.entry_id}_service_restart_{service_name}"
        self._attr_icon = "mdi:restart"

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

    async def async_press(self):
        try:
            async with self.session.post(
                f"{self.base_url}/services/{self._service_name}/restart",
                headers={"Authorization": f"Bearer {self.entry.runtime_data.api_token}"}
            ):
                pass
        except Exception as e:
            _LOGGER.error("Failed to restart service %s: %s", self._service_name, e)


class HostAPIStopTaskButton(ButtonEntity):
    """Button to stop a background task."""

    def __init__(self, entry, task_id: str):
        self.entry = entry
        self._task_id = task_id
        self._attr_name = f"Stop Task {task_id[:8]}"
        self._attr_unique_id = f"{entry.entry_id}_task_stop_{task_id}"
        self._attr_icon = "mdi:stop"

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

    async def async_press(self):
        try:
            await self.session.delete(
                f"{self.base_url}/tasks/{self._task_id}",
                headers={"Authorization": f"Bearer {self.entry.runtime_data.api_token}"}
            )
        except Exception as e:
            _LOGGER.error("Failed to stop task %s: %s", self._task_id, e)


_SERVICE_BUTTON_MARKERS = (
    "_service_start_",
    "_service_stop_",
    "_service_restart_",
)


def _is_managed_service(svc: dict) -> bool:
    """Only favorites and tab-created services get entities."""
    return bool(svc.get("name") and (svc.get("favorite") or svc.get("custom")))


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up HostAPI buttons from config entry.

    Per-service buttons are shape-driven and dynamic: only the restart
    button exists, and only when the user enabled it in the web UI
    (service detail panel). The switch already covers start/stop.
    """
    from .service_entities import make_service_entity_sync, managed_services

    entities = []

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
                for script in info.get("scripts", []):
                    entities.append(HostAPIButtonEntity(entry, script))
    except Exception as e:
        _LOGGER.error("Failed to discover scripts: %s", e)

    entities.append(HostAPIOsRestartButton(entry))
    entities.append(HostAPIOsShutdownButton(entry))
    entities.append(HostAPIRebootToOsButton(entry, "windows"))
    entities.append(HostAPIRebootToOsButton(entry, "linux"))
    entities.append(HostAPICancelOsSwitchButton(entry))
    entities.append(HostAPIWakeButton(hass, entry))
    async_add_entities(entities)

    # Dynamic restart buttons for favorited services (shape opt-in)
    coordinator = data.service_coordinator
    await coordinator.async_refresh()

    created: dict = {}

    def build(name, kind, svc):
        return HostAPIRestartServiceButton(entry, name)

    sync = make_service_entity_sync(
        hass,
        coordinator,
        async_add_entities,
        kinds_for=lambda svc: ("restart",) if svc.get("ha_restart_button") else (),
        build=build,
        created=created,
    )
    sync()
    entry.async_on_unload(coordinator.async_add_listener(sync))

    # One-time registry cleanup for buttons created by older versions
    _remove_stale_service_buttons(hass, entry, list(managed_services(coordinator)))


def _remove_stale_service_buttons(hass, entry, service_names: list) -> None:
    """Remove previously-created service buttons that are no longer managed."""
    registry = er.async_get(hass)
    wanted = {
        f"{entry.entry_id}{marker}{name}"
        for marker in _SERVICE_BUTTON_MARKERS
        for name in service_names
    }
    for entity_entry in registry.async_entries_for_config_entry(entry.entry_id):
        if entity_entry.domain != "button":
            continue
        uid = entity_entry.unique_id
        if any(
            uid.startswith(f"{entry.entry_id}{marker}") for marker in _SERVICE_BUTTON_MARKERS
        ) and uid not in wanted:
            registry.async_remove(entity_entry.entity_id)


class HostAPIOsRestartButton(ButtonEntity):
    """Button to restart the host machine."""

    def __init__(self, entry):
        self.entry = entry
        self._attr_name = "Restart Host"
        self._attr_unique_id = f"{entry.entry_id}_os_restart"
        self._attr_icon = "mdi:restart"

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

    async def async_press(self):
        try:
            async with self.session.post(
                f"{self.base_url}/os/restart",
                headers={"Authorization": f"Bearer {self.entry.runtime_data.api_token}"}
            ):
                pass
        except Exception as e:
            _LOGGER.error("Failed to restart host: %s", e)


class HostAPIOsShutdownButton(ButtonEntity):
    """Button to shutdown the host machine."""

    def __init__(self, entry):
        self.entry = entry
        self._attr_name = "Shutdown Host"
        self._attr_unique_id = f"{entry.entry_id}_os_shutdown"
        self._attr_icon = "mdi:power"

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

    async def async_press(self):
        try:
            async with self.session.post(
                f"{self.base_url}/os/shutdown",
                headers={"Authorization": f"Bearer {self.entry.runtime_data.api_token}"}
            ):
                pass
        except Exception as e:
            _LOGGER.error("Failed to shutdown host: %s", e)


class HostAPIRebootToOsButton(ButtonEntity):
    """Button to reboot straight into the other OS (os_switch module)."""

    _TITLES = {"windows": "Reboot to Windows", "linux": "Reboot to Linux"}
    _ICONS = {"windows": "mdi:microsoft-windows", "linux": "mdi:linux"}

    def __init__(self, entry, target_os: str):
        self.entry = entry
        self._target_os = target_os
        self._attr_name = self._TITLES.get(target_os, f"Reboot to {target_os}")
        self._attr_unique_id = f"{entry.entry_id}_reboot_to_{target_os}"
        self._attr_icon = self._ICONS.get(target_os, "mdi:restart")

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
    def available(self) -> bool:
        """Hide switching to the OS the host is already on."""
        coordinator = self.entry.runtime_data.coordinator
        if not getattr(coordinator, "last_update_success", True):
            return False
        data = coordinator.data or {}
        return data.get("current_os") != self._target_os

    async def async_press(self):
        try:
            async with self.session.post(
                f"{self.base_url}{CONF_API_VERSION}/os/switch",
                json={"target": self._target_os},
                headers={"Authorization": f"Bearer {self.entry.runtime_data.api_token}"}
            ) as response:
                if response.status == 200:
                    body = await response.json()
                    if not body.get("success"):
                        _LOGGER.error(
                            "Reboot to %s rejected: %s",
                            self._target_os, body.get("error"))
                else:
                    _LOGGER.error(
                        "Reboot to %s failed: HTTP %s",
                        self._target_os, response.status)
        except Exception as e:
            _LOGGER.error("Failed to schedule reboot to %s: %s", self._target_os, e)


class HostAPICancelOsSwitchButton(ButtonEntity):
    """Cancels a pending OS switch (enabled only while a switch is pending)."""

    def __init__(self, entry):
        self.entry = entry
        self._attr_name = "Cancel OS Switch"
        self._attr_unique_id = f"{entry.entry_id}_os_switch_cancel"
        self._attr_icon = "mdi:close-octagon"

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
    def available(self) -> bool:
        coordinator = self.entry.runtime_data.coordinator
        if not getattr(coordinator, "last_update_success", True):
            return False
        data = coordinator.data or {}
        return data.get("os_status") == "pending"

    async def async_press(self):
        try:
            async with self.session.post(
                f"{self.base_url}{CONF_API_VERSION}/os/switch/cancel",
                headers={"Authorization": f"Bearer {self.entry.runtime_data.api_token}"}
            ) as response:
                if response.status == 200:
                    body = await response.json()
                    if not body.get("success"):
                        _LOGGER.error(
                            "Cancel OS switch rejected: %s", body.get("error"))
                else:
                    _LOGGER.error(
                        "Cancel OS switch failed: HTTP %s", response.status)
        except Exception as e:
            _LOGGER.error("Failed to cancel OS switch: %s", e)


def wol_payload(mac: str) -> bytes:
    """Build a Wake-on-LAN magic packet from a MAC string."""
    clean = mac.replace(":", "").replace("-", "").lower()
    if len(clean) != 12:
        raise ValueError(f"invalid MAC: {mac}")
    return b"\xff" * 6 + bytes.fromhex(clean) * 16


def _send_udp_wol(mac: str) -> None:
    """Fire a raw WOL packet (fallback when HA's wake_onlan isn't set up)."""
    import socket

    payload = wol_payload(mac)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.sendto(payload, ("255.255.255.255", 9))


OPNSENSE_WOL_PATH = "/api/wol/wol/set"


def opnsense_wol_endpoint(base_url: str) -> str:
    """Return the os-wol API endpoint for an OPNsense base URL."""
    base = (base_url or "").strip().rstrip("/")
    if base.endswith(OPNSENSE_WOL_PATH):
        return base
    return base + OPNSENSE_WOL_PATH


async def async_opnsense_wake(
    session, base_url, *, api_key, api_secret, interface, mac, verify_ssl=True
) -> tuple[bool, str]:
    """Ask OPNsense's os-wol plugin to send a magic packet.

    Returns ``(ok, error)``. OPNsense answers ``{"status": "OK"}`` on
    success and an empty array when the interface/MAC pair is rejected, so
    HTTP 200 alone is not enough.
    """
    endpoint = opnsense_wol_endpoint(base_url)
    payload = {"wake": {"interface": interface, "mac": mac}}
    auth = aiohttp.BasicAuth(api_key, api_secret)
    try:
        async with session.post(
            endpoint, json=payload, auth=auth, ssl=verify_ssl
        ) as resp:
            status = resp.status
            text = await resp.text()
    except Exception as e:
        return False, str(e) or type(e).__name__

    if status != 200:
        return False, f"OPNsense returned HTTP {status}"
    try:
        body = json.loads(text) if text.strip() else {}
    except ValueError:
        body = None
    if isinstance(body, dict) and body.get("status") == "OK":
        return True, ""
    return False, (
        "OPNsense rejected the wake request (check the interface name): "
        f"{text.strip()[:200] or 'empty response'}"
    )


class HostAPIWakeButton(ButtonEntity):
    """Wake the host via WOL - configurable per entry (options flow):

    - native/HA magic packet (default; uses HA's wake_onlan service when
      set up, raw UDP otherwise)
    - user-selectable HA automation (plus the hostapi_wake event)
    - OPNsense os-wol plugin (API key/secret + interface name)
    """

    def __init__(self, hass, entry):
        self.hass = hass
        self.entry = entry
        self._attr_name = "Wake"
        self._attr_unique_id = f"{entry.entry_id}_wake"
        self._attr_icon = "mdi:power-on"

    @property
    def device_info(self) -> dict:
        return get_device_info(self.entry)

    @property
    def _mac(self):
        coordinator = self.entry.runtime_data.coordinator
        data = getattr(coordinator, "data", None) or {}
        return data.get("mac")

    @property
    def _opnsense(self) -> dict:
        opts = self.entry.options
        return {
            "base_url": opts.get("opnsense_url"),
            "api_key": opts.get("opnsense_api_key"),
            "api_secret": opts.get("opnsense_api_secret"),
            "interface": opts.get("opnsense_interface"),
            "verify_ssl": opts.get("opnsense_verify_ssl", True),
        }

    @property
    def available(self) -> bool:
        opts = self.entry.options
        ops = self._opnsense
        opnsense_ready = all(
            ops[k] for k in ("base_url", "api_key", "api_secret", "interface"))
        return bool(
            self._mac
            or opts.get("wake_automation")
            or opnsense_ready
        )

    async def async_press(self):
        mac = self._mac
        opts = self.entry.options
        automation = opts.get("wake_automation")

        if mac and self.hass.services.has_service("wake_onlan", "send_magic_packet"):
            await self.hass.services.async_call(
                "wake_onlan", "send_magic_packet", {"mac": mac}, blocking=False
            )
        elif mac:
            await self.hass.async_add_executor_job(_send_udp_wol, mac)

        if automation:
            await self.hass.services.async_call(
                "automation", "trigger", {"entity_id": automation}, blocking=False
            )

        # event so any user automation can react without the options picker
        self.hass.bus.async_fire("hostapi_wake", {
            "host": self.entry.runtime_data.host, "mac": mac,
        })

        ops = self._opnsense
        if ops["base_url"]:
            ok, error = await async_opnsense_wake(
                self.session,
                base_url=ops["base_url"],
                api_key=ops["api_key"],
                api_secret=ops["api_secret"],
                interface=ops["interface"],
                mac=mac,
                verify_ssl=ops["verify_ssl"],
            )
            if not ok:
                _LOGGER.error(
                    "OPNsense wake failed for %s: %s",
                    self.entry.runtime_data.host, error)


    @property
    def session(self):
        return self.entry.runtime_data.client


