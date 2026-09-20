"""Config flow for HostAPI."""

from homeassistant import config_entries
from homeassistant.config_entries import OptionsFlowWithReload
from homeassistant.const import CONF_API_KEY, CONF_HOST, CONF_PORT
from homeassistant.data_entry_flow import AbortFlow
import voluptuous as vol
import aiohttp

from . import DOMAIN

CONF_WAKE_ENTITY = "wake_entity"
CONF_HA_URL = "ha_url"

DEFAULT_WAKE_ENTITY = "switch.hal_switch_template"
DEFAULT_HA_URL = "http://homeassistant.local:8123"


class HostAPIConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for HostAPI."""

    VERSION = 2

    def __init__(self):
        self._data = {}

    async def async_step_user(self, user_input=None):
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
            step_id="user",
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

    @staticmethod
    def async_get_options_flow(config_entry):
        """Return the options flow for this config entry."""
        return HostAPIOptionsFlow(config_entry)

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


class HostAPIOptionsFlow(OptionsFlowWithReload):
    """Handle options flow for HostAPI."""

    def __init__(self, config_entry):
        self.config_entry = config_entry

    async def async_step_init(self, user_input=None):
        """Manage HostAPI options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_HA_URL,
                        default=self.config_entry.data.get(
                            CONF_HA_URL, DEFAULT_HA_URL
                        ),
                    ): str,
                }
            ),
        )