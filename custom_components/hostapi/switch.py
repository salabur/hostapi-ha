"""Switch platform for HostAPI - service control switches.

State lives in the ServiceStateCoordinator (one REST call per 300s for all
managed services, patched live by the /ws push listener) - switches do not
poll the hostapi individually.
"""

import logging

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import CONF_HOST
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import DOMAIN, get_device_info

_LOGGER = logging.getLogger(__name__)


def _is_managed_service(svc: dict) -> bool:
    """Only favorites and tab-created services get entities (and polling)."""
    return bool(svc.get("name") and (svc.get("favorite") or svc.get("custom")))


class HostAPIServiceSwitch(CoordinatorEntity, SwitchEntity):
    """Switch to control systemd service state (start/stop)."""

    _attr_has_entity_name = True

    def __init__(self, entry, service_name: str, service_coordinator):
        self.entry = entry
        self._service_name = service_name
        self._service_coordinator = service_coordinator
        self._attr_name = service_name
        self._attr_unique_id = f"{entry.entry_id}_service_switch_{service_name}"
        self._attr_icon = "mdi:atom"
        CoordinatorEntity.__init__(self, service_coordinator)

    @property
    def available(self) -> bool:
        return self._service_coordinator.last_update_success

    @property
    def is_on(self) -> bool:
        data = self._service_coordinator.data or {}
        for svc in data.get("services", []):
            if svc.get("name") == self._service_name:
                return bool(svc.get("active"))
        return False

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

    async def _set_state(self, active: bool) -> None:
        self._service_coordinator.apply_service_state(self._service_name, active)

    async def async_turn_on(self) -> None:
        try:
            async with self.session.post(
                f"{self.base_url}/services/{self._service_name}/start",
                headers={"Authorization": f"Bearer {self.entry.runtime_data.api_token}"}
            ) as response:
                if response.status in (200, 201):
                    await self._set_state(True)
        except Exception as e:
            _LOGGER.error("Failed to start service %s: %s", self._service_name, e)

    async def async_turn_off(self) -> None:
        try:
            async with self.session.post(
                f"{self.base_url}/services/{self._service_name}/stop",
                headers={"Authorization": f"Bearer {self.entry.runtime_data.api_token}"}
            ) as response:
                if response.status in (200, 201):
                    await self._set_state(False)
        except Exception as e:
            _LOGGER.error("Failed to stop service %s: %s", self._service_name, e)


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up HostAPI service switches from config entry."""
    entities = []
    service_names = []
    discovered = False

    data = entry.runtime_data
    session = data.client
    base_url = f"http://{data.host}:{data.port}"
    headers = {"Authorization": f"Bearer {data.api_token}"}

    try:
        async with session.get(f"{base_url}/services/", headers=headers) as response:
            if response.status == 200:
                services_data = await response.json()
                for svc in services_data.get("services", []):
                    if _is_managed_service(svc):
                        service_names.append(svc["name"])
                        entities.append(
                            HostAPIServiceSwitch(
                                entry, svc["name"], data.service_coordinator
                            )
                        )
                discovered = True
    except Exception as e:
        _LOGGER.error("Failed to discover services for switch: %s", e)

    if discovered:
        _remove_stale_service_entities(
            hass, entry, "switch", service_names, "_service_switch_"
        )

    if entities:
        async_add_entities(entities)


def _remove_stale_service_entities(
    hass, entry, domain: str, service_names: list, marker: str
) -> None:
    """Remove previously-created service entities that are no longer managed.

    Keeps HA from polling service statuses that the user un-favorited.
    """
    registry = er.async_get(hass)
    wanted = {f"{entry.entry_id}{marker}{name}" for name in service_names}
    for entity_entry in registry.async_entries_for_config_entry(entry.entry_id):
        if entity_entry.domain != domain:
            continue
        uid = entity_entry.unique_id
        if uid.startswith(f"{entry.entry_id}{marker}") and uid not in wanted:
            registry.async_remove(entity_entry.entity_id)
