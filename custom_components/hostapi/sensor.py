"""Sensor platform for HostAPI."""

import logging
from typing import Optional

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.const import CONF_HOST
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import DOMAIN, get_device_info

DOMAIN = "hostapi"
CONF_API_VERSION = "/api/v1"

_LOGGER = logging.getLogger(__name__)


class HostAPIHealthSensor(SensorEntity):
    """Health sensor for HostAPI."""

    def __init__(self, entry):
        self.entry = entry
        self._attr_name = f"HostAPI ({entry.data.get(CONF_HOST)}) Health"
        self._attr_unique_id = f"{entry.entry_id}_health"
        self._attr_icon = "mdi:heart-pulse"
        self._state = "unknown"

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
    def state(self) -> str:
        return self._state

    async def async_update(self):
        try:
            async with self.session.get(
                f"{self.base_url}/health",
                headers={"Authorization": f"Bearer {self.entry.runtime_data.api_token}"}
            ) as response:
                self._state = "ok" if response.status == 200 else "unavailable"
        except Exception:
            self._state = "unavailable"


class HostAPIDisplayProfileSensor(SensorEntity):
    """Display profile sensor."""

    def __init__(self, entry):
        self.entry = entry
        self._attr_name = f"HostAPI ({entry.data.get(CONF_HOST)}) Display Profile"
        self._attr_unique_id = f"{entry.entry_id}_display_profile"
        self._attr_icon = "mdi:monitor"
        self._state = None

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
    def state(self) -> Optional[str]:
        return self._state

    async def async_update(self):
        try:
            async with self.session.get(
                f"{self.base_url}{CONF_API_VERSION}/info",
                headers={"Authorization": f"Bearer {self.entry.runtime_data.api_token}"}
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    self._state = data.get("display_profile", "unknown")
        except Exception as e:
            _LOGGER.error("Failed to update display profile: %s", e)
            self._state = "unavailable"


class HostAPIScriptsSensor(SensorEntity):
    """Scripts sensor with state_class."""

    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, entry):
        self.entry = entry
        self._attr_name = f"HostAPI ({entry.data.get(CONF_HOST)}) Scripts"
        self._attr_unique_id = f"{entry.entry_id}_scripts"
        self._attr_icon = "mdi:script"
        self._state = []

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
    def state(self) -> str:
        return str(len(self._state))

    @property
    def extra_state_attributes(self) -> dict:
        return {"scripts": self._state}

    async def async_update(self):
        try:
            async with self.session.get(
                f"{self.base_url}{CONF_API_VERSION}/info",
                headers={"Authorization": f"Bearer {self.entry.runtime_data.api_token}"}
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    self._state = data.get("scripts", [])
        except Exception as e:
            _LOGGER.error("Failed to update scripts: %s", e)
            self._state = []


class HostAPIServicesSensor(CoordinatorEntity, SensorEntity):
    """Services sensor - reads from the ServiceStateCoordinator (ws + 300s)."""

    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, entry, service_coordinator):
        self.entry = entry
        self._service_coordinator = service_coordinator
        self._attr_name = f"HostAPI ({entry.data.get(CONF_HOST)}) Services"
        self._attr_unique_id = f"{entry.entry_id}_services"
        self._attr_icon = "mdi:format-list-bulleted"
        CoordinatorEntity.__init__(self, service_coordinator)

    @property
    def device_info(self) -> dict:
        return get_device_info(self.entry)

    @property
    def state(self) -> str:
        data = self._service_coordinator.data or {}
        return str(len(data.get("services", [])))

    @property
    def extra_state_attributes(self) -> dict:
        data = self._service_coordinator.data or {}
        return {"services": data.get("services", [])}


class HostAPITasksSensor(SensorEntity):
    """Tasks sensor - shows running task count."""

    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, entry):
        self.entry = entry
        self._attr_name = f"HostAPI ({entry.data.get(CONF_HOST)}) Tasks"
        self._attr_unique_id = f"{entry.entry_id}_tasks"
        self._attr_icon = "mdi:clipboard-list"
        self._state = []

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
    def state(self) -> str:
        return str(len(self._state))

    @property
    def extra_state_attributes(self) -> dict:
        return {"tasks": self._state}

    async def async_update(self):
        try:
            async with self.session.get(
                f"{self.base_url}/tasks/",
                headers={"Authorization": f"Bearer {self.entry.runtime_data.api_token}"}
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    self._state = data.get("tasks", [])
        except Exception as e:
            _LOGGER.error("Failed to update tasks: %s", e)
            self._state = []


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up HostAPI sensors from config entry."""
    entities = [
        HostAPIHealthSensor(entry),
        HostAPIDisplayProfileSensor(entry),
        HostAPIScriptsSensor(entry),
        HostAPIServicesSensor(entry, entry.runtime_data.service_coordinator),
        HostAPITasksSensor(entry),
    ]
    async_add_entities(entities)