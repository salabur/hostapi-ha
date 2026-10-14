"""Entities for generic SSH host devices (machines without hostapi)."""

import logging

import aiohttp
from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.components.button import ButtonEntity
from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import get_device_info
from .button import wol_payload
from .host_coordinator import host_setting

_LOGGER = logging.getLogger(__name__)


class HostAliveBinarySensor(CoordinatorEntity, BinarySensorEntity):
    """'is alive?' - on until `offline_threshold` consecutive misses."""

    _attr_device_class = "connectivity"
    _attr_icon = "mdi:lan-connect"

    def __init__(self, entry, coordinator):
        super().__init__(coordinator)
        self.entry = entry
        self._attr_name = f"{entry.data.get('name')} Alive"
        self._attr_unique_id = f"{entry.entry_id}_alive"

    @property
    def device_info(self) -> dict:
        return get_device_info(self.entry)

    @property
    def is_on(self) -> bool:
        data = self.coordinator.data or {}
        return not data.get("offline", True)

    @property
    def extra_state_attributes(self) -> dict:
        data = self.coordinator.data or {}
        return {
            "missed_answers": data.get("missed", 0),
            "last_error": data.get("last_error"),
            "check_method": self.coordinator.alive_method,
        }


class HostLastActiveSensor(CoordinatorEntity, SensorEntity):
    """Timestamp of the last successful reachability check."""

    _attr_device_class = "timestamp"
    _attr_icon = "mdi:clock-check-outline"

    def __init__(self, entry, coordinator):
        super().__init__(coordinator)
        self.entry = entry
        self._attr_name = f"{entry.data.get('name')} Last Active"
        self._attr_unique_id = f"{entry.entry_id}_last_active"

    @property
    def device_info(self) -> dict:
        return get_device_info(self.entry)

    @property
    def state(self) -> str | None:
        return (self.coordinator.data or {}).get("last_active")


class _HostSSHButton(CoordinatorEntity, ButtonEntity):
    """Base for buttons that run a configured command over SSH."""

    def __init__(self, entry, coordinator, name, unique_suffix, icon):
        super().__init__(coordinator)
        self.entry = entry
        self._attr_name = f"{entry.data.get('name')} {name}"
        self._attr_unique_id = f"{entry.entry_id}_{unique_suffix}"
        self._attr_icon = icon

    @property
    def device_info(self) -> dict:
        return get_device_info(self.entry)

    @property
    def _cmd(self) -> str:
        raise NotImplementedError

    async def async_press(self):
        data = self.coordinator.data or {}
        if data.get("offline"):
            _LOGGER.warning(
                "Skipping %s: host %s is offline",
                self._attr_name, self.entry.data.get("host"))
            return
        result = await self.coordinator.ssh.run(self._cmd)
        if not result.ok:
            _LOGGER.error(
                "%s failed on %s: %s",
                self._attr_name, self.entry.data.get("host"),
                result.error or result.stderr)
        elif result.stderr.strip():
            _LOGGER.info(
                "%s on %s finished with stderr: %s",
                self._attr_name, self.entry.data.get("host"), result.stderr)


class HostRebootButton(_HostSSHButton):
    def __init__(self, entry, coordinator):
        super().__init__(entry, coordinator, "Reboot", "reboot", "mdi:restart")

    @property
    def _cmd(self) -> str:
        return host_setting(self.entry, "reboot_cmd", "sudo systemctl reboot")


class HostShutdownButton(_HostSSHButton):
    def __init__(self, entry, coordinator):
        super().__init__(entry, coordinator, "Shutdown",
                         "shutdown", "mdi:power")

    @property
    def _cmd(self) -> str:
        return host_setting(self.entry, "shutdown_cmd",
                            "sudo systemctl poweroff")


class HostBootOsButton(_HostSSHButton):
    """Reboot into the given OS via a configurable command template."""

    def __init__(self, entry, coordinator, target_os: str):
        self._target_os = target_os
        super().__init__(entry, coordinator, f"Boot to {target_os.title()}",
                         f"boot_to_{target_os}",
                         "mdi:microsoft-windows"
                         if target_os == "windows" else "mdi:linux")

    @property
    def _cmd(self) -> str:
        entry = self.entry
        template = host_setting(
            entry, "boot_os_cmd",
            "grub-reboot {entry} && sudo systemctl reboot")
        entry_name = host_setting(
            entry, f"grub_entry_{self._target_os}", self._target_os)
        return template.format(entry=entry_name)


class HostWakeButton(ButtonEntity):
    """Wake the host: WOL (HA service or raw UDP), automation, OPNsense."""

    _attr_icon = "mdi:power-on"

    def __init__(self, hass, entry):
        self.hass = hass
        self.entry = entry
        self._attr_name = f"{entry.data.get('name')} Wake"
        self._attr_unique_id = f"{entry.entry_id}_wake"

    @property
    def device_info(self) -> dict:
        return get_device_info(self.entry)

    @property
    def _mac(self):
        return host_setting(self.entry, "wol_mac")

    @property
    def available(self) -> bool:
        opts = self.entry.options
        return bool(
            self._mac
            or opts.get("wake_automation")
            or opts.get("opnsense_wol_url")
        )

    async def async_press(self):
        mac = self._mac
        opts = self.entry.options

        if mac and self.hass.services.has_service(
                "wake_onlan", "send_magic_packet"):
            await self.hass.services.async_call(
                "wake_onlan", "send_magic_packet", {"mac": mac},
                blocking=False)
        elif mac:
            await self.hass.async_add_executor_job(_send_udp_wol, mac)

        automation = opts.get("wake_automation")
        if automation:
            await self.hass.services.async_call(
                "automation", "trigger", {"entity_id": automation},
                blocking=False)

        self.hass.bus.async_fire("hostapi_wake", {
            "host": self.entry.data.get("host"), "mac": mac,
        })

        if opts.get("opnsense_wol_url"):
            await self._wake_opnsense(opts.get("opnsense_wol_url"), opts, mac)

    async def _wake_opnsense(self, url: str, opts: dict, mac):
        key = opts.get("opnsense_api_key")
        secret = opts.get("opnsense_api_secret")
        auth = aiohttp.BasicAuth(key, secret) if key and secret else None
        try:
            async with self.entry.runtime_data.client.post(
                url,
                json={"mac": mac, "host": self.entry.data.get("host")},
                auth=auth,
            ):
                pass
        except Exception as e:
            _LOGGER.error("Failed to call OPNsense WOL endpoint: %s", e)


def _send_udp_wol(mac: str) -> None:
    import socket

    payload = wol_payload(mac)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.sendto(payload, ("255.255.255.255", 9))


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up host entities from a 'host' config entry."""
    coordinator = entry.runtime_data.coordinator

    entities = [
        HostAliveBinarySensor(entry, coordinator),
        HostLastActiveSensor(entry, coordinator),
        HostRebootButton(entry, coordinator),
        HostShutdownButton(entry, coordinator),
        HostBootOsButton(entry, coordinator, "windows"),
        HostBootOsButton(entry, coordinator, "linux"),
        HostWakeButton(hass, entry),
    ]
    async_add_entities(entities)
