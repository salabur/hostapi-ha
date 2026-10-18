"""Entities for generic SSH host devices (machines without hostapi)."""

import logging

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.components.button import ButtonEntity
from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import async_get_opnsense_config, get_device_info
from .button import async_opnsense_wake, trigger_service, wol_payload
from .config_flow import DEFAULT_COMMAND_ICON, SUBENTRY_TYPE_COMMAND
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
        if not self._cmd:
            # e.g. boot-to-OS switching left unconfigured
            _LOGGER.debug(
                "Skipping %s: no command configured",
                self._attr_name)
            return
        data = self.coordinator.data or {}
        if data.get("offline") and not host_setting(
                self.entry, "allow_offline_commands", False):
            _LOGGER.warning(
                "Skipping %s: host %s is offline (enable"
                " allow_offline_commands to run anyway)",
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
    def available(self) -> bool:
        # no boot-to-OS command configured -> entity shown but disabled
        return bool(host_setting(self.entry, "boot_os_cmd", ""))

    @property
    def _cmd(self) -> str:
        entry = self.entry
        template = host_setting(
            entry, "boot_os_cmd",
            "grub-reboot {entry} && sudo systemctl reboot")
        entry_name = host_setting(
            entry, f"grub_entry_{self._target_os}", self._target_os)
        return template.format(entry=entry_name)


class HostCommandButton(_HostSSHButton):
    """User-defined command from a 'command' config sub-entry."""

    def __init__(self, entry, coordinator, subentry):
        self.subentry = subentry
        super().__init__(
            entry,
            coordinator,
            subentry.data.get("label") or "Command",
            f"command_{subentry.subentry_id}",
            subentry.data.get("icon") or DEFAULT_COMMAND_ICON,
        )

    @property
    def _cmd(self) -> str:
        return self.subentry.data.get("command", "")


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
        configured = host_setting(self.entry, "wol_mac")
        if configured:
            return configured
        # ARP-discovered during the alive poll (HostStateCoordinator)
        coordinator = getattr(self.entry.runtime_data, "coordinator", None)
        data = getattr(coordinator, "data", None) or {}
        return data.get("mac")

    def _opnsense(self) -> dict | None:
        """Global OPNsense settings, resolved with this host's interface."""
        global_cfg = async_get_opnsense_config(self.hass)
        if global_cfg is None:
            return None
        interface = (host_setting(self.entry, "opnsense_interface")
                     or global_cfg.interface)
        if not all([global_cfg.url, global_cfg.api_key,
                    global_cfg.api_secret, interface]):
            return None
        return {
            "base_url": global_cfg.url,
            "api_key": global_cfg.api_key,
            "api_secret": global_cfg.api_secret,
            "interface": interface,
            "verify_ssl": global_cfg.verify_ssl,
        }

    @property
    def available(self) -> bool:
        opts = self.entry.options
        return bool(
            self._mac
            or opts.get("wake_automation")
            or self._opnsense()
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
            domain, service = trigger_service(automation)
            await self.hass.services.async_call(
                domain, service, {"entity_id": automation},
                blocking=False)

        self.hass.bus.async_fire("hostapi_wake", {
            "host": self.entry.data.get("host"), "mac": mac,
        })

        ops = self._opnsense()
        if ops:
            ok, error = await async_opnsense_wake(
                self.entry.runtime_data.client,
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
                    self.entry.data.get("host"), error)


def _send_udp_wol(mac: str) -> None:
    import socket

    payload = wol_payload(mac)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.sendto(payload, ("255.255.255.255", 9))


def _prune_stale_command_entities(hass, entry, command_subentries) -> None:
    """Remove buttons whose command sub-entry was deleted.

    Command buttons are added without ``config_subentry_id`` (so they stay
    on the host device instead of getting a device of their own), which
    means Home Assistant does not clean their registry entries up for us
    when the sub-entry is removed.
    """
    desired = {
        f"{entry.entry_id}_command_{sub.subentry_id}"
        for sub in command_subentries
    }
    prefix = f"{entry.entry_id}_command_"
    registry = er.async_get(hass)
    for reg_entry in er.async_entries_for_config_entry(
            registry, entry.entry_id):
        if (reg_entry.unique_id.startswith(prefix)
                and reg_entry.unique_id not in desired):
            registry.async_remove(reg_entry.entity_id)


def _host_command_subentries(entry):
    return [
        sub for sub in entry.subentries.values()
        if sub.subentry_type == SUBENTRY_TYPE_COMMAND
    ]


async def async_setup_binary_sensors(hass, entry, async_add_entities):
    """Platform setup: the alive binary sensor."""
    async_add_entities([
        HostAliveBinarySensor(entry, entry.runtime_data.coordinator)])


async def async_setup_sensors(hass, entry, async_add_entities):
    """Platform setup: the last-active sensor."""
    async_add_entities([
        HostLastActiveSensor(entry, entry.runtime_data.coordinator)])


async def async_setup_buttons(hass, entry, async_add_entities):
    """Platform setup: command + wake buttons."""
    coordinator = entry.runtime_data.coordinator
    command_subentries = _host_command_subentries(entry)

    async_add_entities([
        HostRebootButton(entry, coordinator),
        HostShutdownButton(entry, coordinator),
        HostBootOsButton(entry, coordinator, "windows"),
        HostBootOsButton(entry, coordinator, "linux"),
        HostWakeButton(hass, entry),
    ] + [HostCommandButton(entry, coordinator, sub)
         for sub in command_subentries])

    _prune_stale_command_entities(hass, entry, command_subentries)


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up all host entities (used directly by the mocked test suite)."""
    coordinator = entry.runtime_data.coordinator
    command_subentries = _host_command_subentries(entry)

    entities = [
        HostAliveBinarySensor(entry, coordinator),
        HostLastActiveSensor(entry, coordinator),
        HostRebootButton(entry, coordinator),
        HostShutdownButton(entry, coordinator),
        HostBootOsButton(entry, coordinator, "windows"),
        HostBootOsButton(entry, coordinator, "linux"),
        HostWakeButton(hass, entry),
    ]
    entities += [HostCommandButton(entry, coordinator, sub)
                 for sub in command_subentries]
    async_add_entities(entities)

    _prune_stale_command_entities(hass, entry, command_subentries)
