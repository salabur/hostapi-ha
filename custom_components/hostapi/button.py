"""Button platform for HostAPI."""

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.const import CONF_HOST
from homeassistant.helpers import entity_registry as er

from . import DOMAIN, get_device_info

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


class HostAPIStartServiceButton(ButtonEntity):
    """Button to start a systemd service."""

    def __init__(self, entry, service_name: str):
        self.entry = entry
        self._service_name = service_name
        self._attr_name = f"Start {service_name}"
        self._attr_unique_id = f"{entry.entry_id}_service_start_{service_name}"
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
                f"{self.base_url}/services/{self._service_name}/start",
                headers={"Authorization": f"Bearer {self.entry.runtime_data.api_token}"}
            ):
                pass
        except Exception as e:
            _LOGGER.error("Failed to start service %s: %s", self._service_name, e)


class HostAPIStopServiceButton(ButtonEntity):
    """Button to stop a systemd service."""

    def __init__(self, entry, service_name: str):
        self.entry = entry
        self._service_name = service_name
        self._attr_name = f"Stop {service_name}"
        self._attr_unique_id = f"{entry.entry_id}_service_stop_{service_name}"
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
            async with self.session.post(
                f"{self.base_url}/services/{self._service_name}/stop",
                headers={"Authorization": f"Bearer {self.entry.runtime_data.api_token}"}
            ):
                pass
        except Exception as e:
            _LOGGER.error("Failed to stop service %s: %s", self._service_name, e)


class HostAPIRestartServiceButton(ButtonEntity):
    """Button to restart a systemd service."""

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
    """Set up HostAPI buttons from config entry."""
    entities = []
    service_names = []
    discovered = False

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

    try:
        async with session.get(
            f"{base_url}/services/",
            headers=headers
        ) as response:
            if response.status == 200:
                services_data = await response.json()
                for svc in services_data.get("services", []):
                    if _is_managed_service(svc):
                        service_names.append(svc["name"])
                        entities.append(HostAPIStartServiceButton(entry, svc["name"]))
                        entities.append(HostAPIStopServiceButton(entry, svc["name"]))
                        entities.append(HostAPIRestartServiceButton(entry, svc["name"]))
                discovered = True
    except Exception as e:
        _LOGGER.error("Failed to discover services: %s", e)

    if discovered:
        _remove_stale_service_buttons(hass, entry, service_names)

    entities.append(HostAPIOsRestartButton(entry))
    entities.append(HostAPIOsShutdownButton(entry))

    if entities:
        async_add_entities(entities)


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


