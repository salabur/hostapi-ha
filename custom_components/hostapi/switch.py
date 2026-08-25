"""Switch platform for HostAPI - service control switches."""

import logging

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import CONF_HOST

from . import DOMAIN, get_device_info

_LOGGER = logging.getLogger(__name__)


class HostAPIServiceSwitch(SwitchEntity):
    """Switch to control systemd service state (start/stop)."""

    _attr_has_entity_name = True

    def __init__(self, entry, service_name: str):
        self.entry = entry
        self._service_name = service_name
        self._attr_name = service_name
        self._attr_unique_id = f"{entry.entry_id}_service_switch_{service_name}"
        self._attr_icon = "mdi:atom"
        self._attr_is_on = False

    @property
    def base_url(self) -> str:
        data = self.entry.runtime_data
        return f"http://{data.host}:{data.port}"

    @property
    def session(self):
        return self.entry.runtime_data.client

    @property
    def device_info(self) -> dict:
        return get_device_info(self.entry)

    async def async_turn_on(self) -> None:
        try:
            async with self.session.post(
                f"{self.base_url}/services/{self._service_name}/start",
                headers={"Authorization": f"Bearer {self.entry.runtime_data.api_token}"}
            ) as response:
                self._attr_is_on = response.status == 200 or response.status == 201
        except Exception as e:
            _LOGGER.error("Failed to start service %s: %s", self._service_name, e)

    async def async_turn_off(self) -> None:
        try:
            async with self.session.post(
                f"{self.base_url}/services/{self._service_name}/stop",
                headers={"Authorization": f"Bearer {self.entry.runtime_data.api_token}"}
            ) as response:
                self._attr_is_on = not (response.status == 200 or response.status == 201)
        except Exception as e:
            _LOGGER.error("Failed to stop service %s: %s", self._service_name, e)

    async def async_update(self) -> None:
        try:
            async with self.session.get(
                f"{self.base_url}/services/{self._service_name}/status",
                headers={"Authorization": f"Bearer {self.entry.runtime_data.api_token}"}
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    self._attr_is_on = data.get("active", False)
        except Exception as e:
            _LOGGER.error("Failed to update service %s status: %s", self._service_name, e)


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up HostAPI service switches from config entry."""
    entities = []

    data = entry.runtime_data
    session = data.client
    base_url = f"http://{data.host}:{data.port}"
    headers = {"Authorization": f"Bearer {data.api_token}"}

    try:
        async with session.get(f"{base_url}/services/", headers=headers) as response:
            if response.status == 200:
                services_data = await response.json()
                for svc in services_data.get("services", []):
                    svc_name = svc.get("name", "")
                    if svc_name:
                        entities.append(HostAPIServiceSwitch(entry, svc_name))
    except Exception as e:
        _LOGGER.error("Failed to discover services for switch: %s", e)

    if entities:
        async_add_entities(entities)