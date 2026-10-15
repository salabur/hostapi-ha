"""Config flow for HostAPI."""

import logging

import aiohttp
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import (
    ConfigSubentryFlow,
    OptionsFlow,
    OptionsFlowWithReload,
)
from homeassistant.const import CONF_API_KEY, CONF_HOST, CONF_PORT
from homeassistant.core import callback

from . import DOMAIN

_LOGGER = logging.getLogger(__name__)

CONF_WAKE_ENTITY = "wake_entity"
CONF_HA_URL = "ha_url"
CONF_WAKE_AUTOMATION = "wake_automation"
CONF_OPNSENSE_WOL_URL = "opnsense_wol_url"
CONF_OPNSENSE_API_KEY = "opnsense_api_key"
CONF_OPNSENSE_API_SECRET = "opnsense_api_secret"

# Host (generic SSH machine) config keys
CONF_KIND = "kind"
CONF_NAME = "name"
CONF_SSH_PORT = "ssh_port"
CONF_SSH_USER = "ssh_user"
CONF_SSH_PASSWORD = "ssh_password"
CONF_SSH_KEY = "ssh_key"
CONF_ALIVE_METHOD = "alive_method"
CONF_ALIVE_PORT = "alive_port"
CONF_POLL_INTERVAL = "poll_interval"
CONF_OFFLINE_THRESHOLD = "offline_threshold"
CONF_REBOOT_CMD = "reboot_cmd"
CONF_SHUTDOWN_CMD = "shutdown_cmd"
CONF_BOOT_OS_CMD = "boot_os_cmd"
CONF_GRUB_ENTRY_WINDOWS = "grub_entry_windows"
CONF_GRUB_ENTRY_LINUX = "grub_entry_linux"
CONF_WOL_MAC = "wol_mac"

# Run-command subentries (one button per user-defined command)
SUBENTRY_TYPE_COMMAND = "command"
CONF_LABEL = "label"
CONF_COMMAND = "command"
CONF_ICON = "icon"
DEFAULT_COMMAND_ICON = "mdi:console"

KIND_HOSTAPI = "hostapi"
KIND_HOST = "host"

DEFAULT_WAKE_ENTITY = "switch.hal_switch_template"
DEFAULT_HA_URL = "http://homeassistant.local:8123"

DEFAULT_SSH_PORT = 22
DEFAULT_SSH_USER = "root"
DEFAULT_ALIVE_METHOD = "tcp"
DEFAULT_POLL_INTERVAL = 30
DEFAULT_OFFLINE_THRESHOLD = 5
DEFAULT_REBOOT_CMD = "sudo systemctl reboot"
DEFAULT_SHUTDOWN_CMD = "sudo systemctl poweroff"
DEFAULT_BOOT_OS_CMD = "grub-reboot {entry} && sudo systemctl reboot"

HOST_AUTH_ERRORS = {
    "base": "cannot_connect",
}


class HostAPIConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for HostAPI."""

    VERSION = 2

    def __init__(self):
        self._data = {}
        self._host_data = {}

    async def async_step_user(self, user_input=None):
        """Entry point: choose between a hostapi instance and an SSH host."""
        errors = {}

        if user_input is not None:
            kind = user_input.get(CONF_KIND, KIND_HOSTAPI)
            if kind == KIND_HOST:
                self._host_data = {}
                return await self.async_step_host_connection()
            return await self.async_step_hostapi_connection()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_KIND, default=KIND_HOSTAPI): vol.In(
                        {KIND_HOSTAPI: "HostAPI instance (REST API)",
                         KIND_HOST: "Generic host (SSH)"}
                    ),
                }
            ),
            errors=errors,
        )

    # ---- host (generic SSH machine) flow -------------------------------
    async def async_step_host_connection(self, user_input=None):
        """Name, address and SSH credentials for the new host."""
        errors = {}

        if user_input is not None:
            name = user_input.get(CONF_NAME) or user_input.get(CONF_HOST)
            host = user_input.get(CONF_HOST)
            ssh_port = int(user_input.get(CONF_SSH_PORT, DEFAULT_SSH_PORT))

            await self.async_set_unique_id(f"hostapi_host_{host}")
            self._abort_if_unique_id_configured()

            ok, error = await self._validate_ssh(
                host, ssh_port,
                user_input.get(CONF_SSH_USER, DEFAULT_SSH_USER),
                user_input.get(CONF_SSH_PASSWORD),
                user_input.get(CONF_SSH_KEY),
            )
            if ok:
                self._host_data = {
                    CONF_KIND: KIND_HOST,
                    CONF_NAME: name,
                    CONF_HOST: host,
                    CONF_SSH_PORT: ssh_port,
                    CONF_SSH_USER: user_input.get(
                        CONF_SSH_USER, DEFAULT_SSH_USER),
                    CONF_SSH_PASSWORD: user_input.get(CONF_SSH_PASSWORD),
                    CONF_SSH_KEY: user_input.get(CONF_SSH_KEY),
                }
                return await self.async_step_host_alive()
            _LOGGER.warning(
                "Host %s validation failed: %s", host, error)
            errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="host_connection",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_NAME): str,
                    vol.Required(CONF_HOST): str,
                    vol.Required(CONF_SSH_PORT, default=DEFAULT_SSH_PORT): int,
                    vol.Required(CONF_SSH_USER, default=DEFAULT_SSH_USER): str,
                    vol.Optional(CONF_SSH_PASSWORD): str,
                    vol.Optional(
                        CONF_SSH_KEY,
                        description="Private key content or path",
                    ): str,
                }
            ),
            errors=errors,
        )

    async def async_step_host_alive(self, user_input=None):
        """Reachability check settings."""
        if user_input is not None:
            self._host_data.update(user_input)
            return await self.async_step_host_commands()

        return self.async_show_form(
            step_id="host_alive",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_ALIVE_METHOD, default=DEFAULT_ALIVE_METHOD
                    ): vol.In({"tcp": "TCP port probe",
                               "icmp": "ICMP ping"}),
                    vol.Optional(
                        CONF_ALIVE_PORT, default=DEFAULT_SSH_PORT): int,
                    vol.Optional(
                        CONF_POLL_INTERVAL,
                        default=DEFAULT_POLL_INTERVAL): int,
                    vol.Optional(
                        CONF_OFFLINE_THRESHOLD,
                        default=DEFAULT_OFFLINE_THRESHOLD): int,
                }
            ),
        )

    async def async_step_host_commands(self, user_input=None):
        """Reboot/shutdown/boot-to-OS command templates."""
        if user_input is not None:
            self._host_data.update(user_input)
            return await self.async_step_host_wake()

        return self.async_show_form(
            step_id="host_commands",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_REBOOT_CMD, default=DEFAULT_REBOOT_CMD): str,
                    vol.Required(
                        CONF_SHUTDOWN_CMD,
                        default=DEFAULT_SHUTDOWN_CMD): str,
                    vol.Required(
                        CONF_BOOT_OS_CMD,
                        default=DEFAULT_BOOT_OS_CMD): str,
                    vol.Required(
                        CONF_GRUB_ENTRY_WINDOWS, default="windows"): str,
                    vol.Required(
                        CONF_GRUB_ENTRY_LINUX, default="linux"): str,
                }
            ),
        )

    async def async_step_host_wake(self, user_input=None):
        """Optional wake settings; completes the host entry."""
        if user_input is not None:
            self._host_data.update(user_input)
            name = self._host_data.get(CONF_NAME)
            return self.async_create_entry(
                title=f"Host ({name})", data=self._host_data)

        return self.async_show_form(
            step_id="host_wake",
            data_schema=vol.Schema(
                {
                    vol.Optional(CONF_WOL_MAC, description="WOL MAC address",
                                 default=""): str,
                    vol.Optional(
                        CONF_WAKE_AUTOMATION,
                        description="HA automation/script entity to trigger",
                        default=""): str,
                    vol.Optional(CONF_OPNSENSE_WOL_URL, default=""): str,
                    vol.Optional(CONF_OPNSENSE_API_KEY, default=""): str,
                    vol.Optional(CONF_OPNSENSE_API_SECRET, default=""): str,
                }
            ),
        )

    @staticmethod
    async def _validate_ssh(host, port, user, password, key):
        from .ssh_client import SSHClient

        client = SSHClient(host, port, user, password=password, key=key)
        probe = await client.tcp_probe(port)
        if not probe.ok:
            return False, probe.error
        if password or key:
            auth = await client.check_auth()
            if not auth.ok:
                return False, auth.error
        return True, None

    async def async_step_hostapi_connection(self, user_input=None):
        """Original hostapi-instance connection form."""
        errors = {}

        if user_input is not None:
            host = user_input.get(CONF_HOST)
            port = user_input.get(CONF_PORT, 8080)
            api_key = user_input.get(CONF_API_KEY)

            unique_id = f"hostapi_{host}"

            await self.async_set_unique_id(unique_id)
            self._abort_if_unique_id_configured()

            if await self._validate_connection(host, port, api_key):
                return self.async_create_entry(
                    title=f"HostAPI ({host})",
                    data=user_input,
                )
            else:
                errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="hostapi_connection",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_HOST): str,
                    vol.Optional(CONF_PORT, default=8080): int,
                    vol.Required(CONF_API_KEY): str,
                    vol.Optional(
                        CONF_WAKE_ENTITY,
                        default=DEFAULT_WAKE_ENTITY,
                    ): str,
                    vol.Optional(
                        CONF_HA_URL,
                        default=self._default_ha_url(),
                    ): str,
                }
            ),
            errors=errors,
        )

    async def async_step_reconfigure(self, user_input=None):
        errors = {}

        entry = self._get_reconfigure_entry()

        if entry.data.get(CONF_KIND) == KIND_HOST:
            return await self._async_step_host_reconfigure(entry, user_input)

        self._data = dict(entry.data)

        if user_input is not None:
            host = user_input.get(CONF_HOST)
            port = user_input.get(CONF_PORT, 8080)
            api_key = user_input.get(CONF_API_KEY)

            if await self._validate_connection(host, port, api_key):
                self._data.update(user_input)
                return self.async_update_reload_and_abort(
                    entry,
                    data_updates=self._data,
                )
            else:
                errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_HOST, default=entry.data.get(CONF_HOST)): str,
                    vol.Optional(CONF_PORT, default=entry.data.get(CONF_PORT, 8080)): int,
                    vol.Required(CONF_API_KEY, default=entry.data.get(CONF_API_KEY)): str,
                    vol.Optional(
                        CONF_WAKE_ENTITY,
                        default=entry.data.get(CONF_WAKE_ENTITY, DEFAULT_WAKE_ENTITY),
                    ): str,
                    vol.Optional(
                        CONF_HA_URL,
                        default=entry.data.get(CONF_HA_URL, self._default_ha_url()),
                    ): str,
                }
            ),
            errors=errors,
        )

    def _default_ha_url(self) -> str:
        """Return the HA internal URL when known, else a sensible fallback."""
        config = getattr(self.hass, "config", None)
        internal_url = getattr(config, "internal_url", None) if config is not None else None
        return internal_url or DEFAULT_HA_URL

    @classmethod
    @callback
    def async_get_supported_subentry_types(cls, config_entry):
        """Only generic SSH hosts support per-host command sub-entries."""
        if config_entry.data.get(CONF_KIND) == KIND_HOST:
            return {SUBENTRY_TYPE_COMMAND: HostCommandSubentryFlow}
        return {}

    @staticmethod
    def async_get_options_flow(config_entry):
        """Return the options flow for this config entry."""
        if config_entry.data.get(CONF_KIND) == KIND_HOST:
            return HostOptionsFlow()
        return HostAPIOptionsFlow()

    async def _validate_connection(
        self, host: str, port: int, api_key: str
    ) -> bool:
        """Validate connection to hostapi server."""
        url = f"http://{host}:{port}/auth/password"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=5) as response:
                    return response.status == 200
        except Exception:
            return False

    async def _async_step_host_reconfigure(self, entry, user_input=None):
        """Reconfigure connection/auth of an SSH host entry."""
        errors = {}

        if user_input is not None:
            ok, _error = await self._validate_ssh(
                user_input.get(CONF_HOST),
                int(user_input.get(CONF_SSH_PORT, DEFAULT_SSH_PORT)),
                user_input.get(CONF_SSH_USER, DEFAULT_SSH_USER),
                user_input.get(CONF_SSH_PASSWORD),
                user_input.get(CONF_SSH_KEY),
            )
            if ok:
                data = dict(entry.data)
                data.update(user_input)
                return self.async_update_reload_and_abort(entry,
                                                          data_updates=data)
            errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="host_connection",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_NAME,
                        default=entry.data.get(CONF_NAME)): str,
                    vol.Required(
                        CONF_HOST,
                        default=entry.data.get(CONF_HOST)): str,
                    vol.Required(
                        CONF_SSH_PORT,
                        default=entry.data.get(
                            CONF_SSH_PORT, DEFAULT_SSH_PORT)): int,
                    vol.Required(
                        CONF_SSH_USER,
                        default=entry.data.get(
                            CONF_SSH_USER, DEFAULT_SSH_USER)): str,
                    vol.Optional(CONF_SSH_PASSWORD): str,
                    vol.Optional(CONF_SSH_KEY): str,
                }
            ),
            errors=errors,
        )


class HostAPIOptionsFlow(OptionsFlowWithReload):
    """Options flow for a HostAPI instance entry (auto-reloads)."""

    async def async_step_init(self, user_input=None):
        """Manage HostAPI options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        opts = self.config_entry.options
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_HA_URL,
                        default=opts.get(
                            CONF_HA_URL,
                            self.config_entry.data.get(CONF_HA_URL, DEFAULT_HA_URL),
                        ),
                    ): str,
                    vol.Optional(
                        CONF_WAKE_AUTOMATION,
                        description="HA automation/script entity to trigger on Wake",
                        default=opts.get(CONF_WAKE_AUTOMATION, ""),
                    ): str,
                    vol.Optional(
                        CONF_OPNSENSE_WOL_URL,
                        description="OPNsense WOL endpoint (POST, authenticated)",
                        default=opts.get(CONF_OPNSENSE_WOL_URL, ""),
                    ): str,
                    vol.Optional(
                        CONF_OPNSENSE_API_KEY,
                        default=opts.get(CONF_OPNSENSE_API_KEY, ""),
                    ): str,
                    vol.Optional(
                        CONF_OPNSENSE_API_SECRET,
                        default=opts.get(CONF_OPNSENSE_API_SECRET, ""),
                    ): str,
                }
            ),
        )

class HostOptionsFlow(OptionsFlow):
    """Options flow for a generic SSH host entry.

    Reloads are driven by the entry's update listener (registered in
    __init__.py), so this must not use OptionsFlowWithReload - Home Assistant
    rejects that combination.
    """

    async def async_step_init(self, user_input=None):
        """Options for an SSH host entry: polling + commands + wake."""
        entry = self.config_entry
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        data = entry.data
        opts = entry.options
        return self.async_show_form(
            step_id="host_options",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_ALIVE_METHOD,
                        default=opts.get(CONF_ALIVE_METHOD,
                                         data.get(CONF_ALIVE_METHOD,
                                                  DEFAULT_ALIVE_METHOD)),
                    ): vol.In({"tcp": "TCP port probe",
                               "icmp": "ICMP ping"}),
                    vol.Optional(
                        CONF_ALIVE_PORT,
                        default=opts.get(CONF_ALIVE_PORT,
                                         data.get(CONF_ALIVE_PORT,
                                                  DEFAULT_SSH_PORT)),
                    ): int,
                    vol.Optional(
                        CONF_POLL_INTERVAL,
                        default=opts.get(CONF_POLL_INTERVAL,
                                         data.get(CONF_POLL_INTERVAL,
                                                  DEFAULT_POLL_INTERVAL)),
                    ): int,
                    vol.Optional(
                        CONF_OFFLINE_THRESHOLD,
                        default=opts.get(
                            CONF_OFFLINE_THRESHOLD,
                            data.get(CONF_OFFLINE_THRESHOLD,
                                     DEFAULT_OFFLINE_THRESHOLD)),
                    ): int,
                    vol.Optional(
                        CONF_REBOOT_CMD,
                        default=opts.get(CONF_REBOOT_CMD,
                                         data.get(CONF_REBOOT_CMD,
                                                  DEFAULT_REBOOT_CMD)),
                    ): str,
                    vol.Optional(
                        CONF_SHUTDOWN_CMD,
                        default=opts.get(CONF_SHUTDOWN_CMD,
                                         data.get(CONF_SHUTDOWN_CMD,
                                                  DEFAULT_SHUTDOWN_CMD)),
                    ): str,
                    vol.Optional(
                        CONF_BOOT_OS_CMD,
                        default=opts.get(CONF_BOOT_OS_CMD,
                                         data.get(CONF_BOOT_OS_CMD,
                                                  DEFAULT_BOOT_OS_CMD)),
                    ): str,
                    vol.Optional(
                        CONF_WOL_MAC,
                        default=opts.get(CONF_WOL_MAC,
                                         data.get(CONF_WOL_MAC, "")),
                    ): str,
                    vol.Optional(
                        CONF_WAKE_AUTOMATION,
                        default=opts.get(CONF_WAKE_AUTOMATION, ""),
                    ): str,
                    vol.Optional(
                        CONF_OPNSENSE_WOL_URL,
                        default=opts.get(CONF_OPNSENSE_WOL_URL, ""),
                    ): str,
                    vol.Optional(
                        CONF_OPNSENSE_API_KEY,
                        default=opts.get(CONF_OPNSENSE_API_KEY, ""),
                    ): str,
                    vol.Optional(
                        CONF_OPNSENSE_API_SECRET,
                        default=opts.get(CONF_OPNSENSE_API_SECRET, ""),
                    ): str,
                }
            ),
        )


class HostCommandSubentryFlow(ConfigSubentryFlow):
    """Add or reconfigure one user-defined command on a host."""

    async def async_step_user(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(**self._entry_kwargs(user_input))

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_LABEL): str,
                    vol.Required(CONF_COMMAND): str,
                    vol.Optional(
                        CONF_ICON, default=DEFAULT_COMMAND_ICON): str,
                }
            ),
        )

    async def async_step_reconfigure(self, user_input=None):
        subentry = self._get_reconfigure_subentry()
        if user_input is not None:
            return self.async_update_and_abort(
                self._get_entry(), subentry,
                **self._entry_kwargs(user_input))

        data = subentry.data
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_LABEL, default=data.get(CONF_LABEL)): str,
                    vol.Required(
                        CONF_COMMAND, default=data.get(CONF_COMMAND)): str,
                    vol.Optional(
                        CONF_ICON,
                        default=data.get(CONF_ICON,
                                         DEFAULT_COMMAND_ICON)): str,
                }
            ),
        )

    @staticmethod
    def _entry_kwargs(user_input: dict) -> dict:
        """Build subentry title/unique_id/data from the flow input."""
        label = user_input[CONF_LABEL]
        return {
            "title": label,
            "unique_id": label.strip().lower(),
            "data": {
                CONF_LABEL: label,
                CONF_COMMAND: user_input[CONF_COMMAND],
                CONF_ICON: user_input.get(CONF_ICON) or DEFAULT_COMMAND_ICON,
            },
        }