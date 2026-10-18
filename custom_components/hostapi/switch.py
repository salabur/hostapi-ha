"""Switch platform for HostAPI - service control switches.

State lives in the ServiceStateCoordinator (one REST call per 300s for all
managed services, patched live by the /ws push listener) - switches do not
poll the hostapi individually.
"""

import logging

from homeassistant.components.switch import SwitchEntity
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import get_device_info
from .service_entities import make_service_entity_sync, managed_services

_LOGGER = logging.getLogger(__name__)


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
    """Set up HostAPI service switches from config entry.

    Entities are dynamic: a listener on the service coordinator adds a
    switch when a service is favorited and removes it on unfavorite -
    within ~1s of the web UI toggle, no entry reload needed.
    """
    data = entry.runtime_data
    coordinator = data.service_coordinator

    # Make sure we have fresh managed-service data before diffing
    await coordinator.async_refresh()

    # One-time registry cleanup for entities created by older versions
    _remove_stale_service_entities(
        hass,
        entry,
        "switch",
        list(managed_services(coordinator)),
        "_service_switch_",
    )

    created: dict = {}

    def build(name, kind, svc):
        return HostAPIServiceSwitch(entry, name, coordinator)

    sync = make_service_entity_sync(
        hass,
        coordinator,
        async_add_entities,
        kinds_for=lambda svc: ("switch",),
        build=build,
        created=created,
    )
    sync()
    entry.async_on_unload(coordinator.async_add_listener(sync))


def _remove_stale_service_entities(
    hass, entry, domain: str, service_names: list, marker: str
) -> None:
    """Remove previously-created service entities that are no longer managed.

    Keeps HA from polling service statuses that the user un-favorited.
    """
    registry = er.async_get(hass)
    wanted = {f"{entry.entry_id}{marker}{name}" for name in service_names}
    for entity_entry in er.async_entries_for_config_entry(
            registry, entry.entry_id):
        if entity_entry.domain != domain:
            continue
        uid = entity_entry.unique_id
        if uid.startswith(f"{entry.entry_id}{marker}") and uid not in wanted:
            registry.async_remove(entity_entry.entity_id)
