"""Sensor platform for HostAPI."""

import logging
from typing import Optional

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.const import CONF_HOST
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import get_device_info

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


class HostAPIOsSensor(CoordinatorEntity, SensorEntity):
    """Currently booted OS (linux/windows) from /api/v1/info."""

    _ICONS = {"windows": "mdi:microsoft-windows", "linux": "mdi:linux"}

    def __init__(self, entry, coordinator):
        super().__init__(coordinator)
        self.entry = entry
        self._attr_name = "Current OS"
        self._attr_unique_id = f"{entry.entry_id}_current_os"

    @property
    def device_info(self) -> dict:
        return get_device_info(self.entry)

    @property
    def state(self) -> str:
        data = self.coordinator.data or {}
        return data.get("current_os") or "unknown"

    @property
    def icon(self) -> str:
        return self._ICONS.get(self.state, "mdi:restart")


class HostAPIOsStatusSensor(CoordinatorEntity, SensorEntity):
    """OS switch status (current OS / pending switch) from /api/v1/info."""

    def __init__(self, entry, coordinator):
        super().__init__(coordinator)
        self.entry = entry
        self._attr_name = "OS Switch Status"
        self._attr_unique_id = f"{entry.entry_id}_os_status"
        self._attr_icon = "mdi:harddisk"

    @property
    def device_info(self) -> dict:
        return get_device_info(self.entry)

    @property
    def state(self) -> str:
        data = self.coordinator.data or {}
        return data.get("os_status") or "unknown"

    @property
    def extra_state_attributes(self) -> dict:
        data = self.coordinator.data or {}
        return {
            "current_os": data.get("current_os"),
            "mac": data.get("mac"),
            "switch_error": data.get("switch_error"),
        }


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up HostAPI sensors from config entry."""
    entities = [
        HostAPIHealthSensor(entry),
        HostAPIDisplayProfileSensor(entry),
        HostAPIScriptsSensor(entry),
        HostAPIServicesSensor(entry, entry.runtime_data.service_coordinator),
        HostAPITasksSensor(entry),
        HostAPIOsSensor(entry, entry.runtime_data.coordinator),
        HostAPIOsStatusSensor(entry, entry.runtime_data.coordinator),
    ]
    async_add_entities(entities)

    # Dynamic per-service state sensors (opt-in via HA entity shape)
    from .service_entities import make_service_entity_sync

    coordinator = entry.runtime_data.service_coordinator
    await coordinator.async_refresh()

    created: dict = {}

    def build(name, kind, svc):
        return HostAPIServiceStateSensor(entry, name, coordinator)

    sync = make_service_entity_sync(
        hass,
        coordinator,
        async_add_entities,
        kinds_for=lambda svc: ("sensor",) if svc.get("ha_sensor") else (),
        build=build,
        created=created,
    )
    sync()
    entry.async_on_unload(coordinator.async_add_listener(sync))


class HostAPIServiceStateSensor(CoordinatorEntity, SensorEntity):
    """Per-service state sensor (opt-in via the web UI detail panel)."""

    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:atom"

    def __init__(self, entry, service_name: str, service_coordinator):
        self.entry = entry
        self._service_name = service_name
        self._service_coordinator = service_coordinator
        self._attr_name = f"Service {service_name}"
        self._attr_unique_id = f"{entry.entry_id}_service_sensor_{service_name}"
        CoordinatorEntity.__init__(self, service_coordinator)

    @property
    def device_info(self) -> dict:
        return get_device_info(self.entry)

    @property
    def available(self) -> bool:
        return self._service_coordinator.last_update_success

    @property
    def state(self) -> str:
        data = self._service_coordinator.data or {}
        for svc in data.get("services", []):
            if svc.get("name") == self._service_name:
                return "on" if svc.get("active") else "off"
        return "unknown"