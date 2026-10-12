"""Runtime-dynamic service entity management for the HA component.

A favorited service must appear in HA within ~1s of the toggle (and vanish
on unfavorite) without an entry reload. The service coordinator's data IS
the source of truth: /services/?managed=true returns name + favorite/custom
+ ha_restart_button/ha_sensor flags, and the /ws push (services_changed)
triggers coordinator refresh -> the platform listeners below diff the
managed set against created entities and add/remove accordingly.
"""

from __future__ import annotations

import logging

_LOGGER = logging.getLogger(__name__)


def managed_services(coordinator) -> dict:
    """name -> service entry dict from the coordinator's latest data."""
    services = {}
    for svc in (coordinator.data or {}).get("services", []):
        if svc.get("name"):
            services[svc["name"]] = svc
    return services


def make_service_entity_sync(
    hass,
    coordinator,
    async_add_entities,
    kinds_for,
    build,
    created: dict,
):
    """Build the per-platform diff callback.

    kinds_for(svc) -> iterable of entity kinds for that service; build(name,
    kind, svc) -> entity or None. created maps (name, kind) -> entity and is
    owned by the caller (one dict per platform).
    """

    def _sync():
        services = managed_services(coordinator)

        wanted = set()
        for name, svc in services.items():
            for kind in kinds_for(svc):
                wanted.add((name, kind))

        # add new (in coordinator data order - favorites first)
        new = []
        for name, svc in services.items():
            for kind in kinds_for(svc):
                key = (name, kind)
                if key in created:
                    continue
                entity = build(name, kind, svc)
                if entity is not None:
                    created[key] = entity
                    new.append(entity)
        if new:
            async_add_entities(new)

        # remove stale
        for key in list(created):
            if key not in wanted:
                entity = created.pop(key)
                hass.async_create_task(entity.async_remove())

    return _sync
