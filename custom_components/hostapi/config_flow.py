"""Config flow for HostAPI."""

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PORT, CONF_API_KEY, CONF_API_TOKEN
from homeassistant.data_entry_flow import AbortFlow
import voluptuous as vol
import aiohttp


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
                }
            ),
            errors=errors,
        )

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