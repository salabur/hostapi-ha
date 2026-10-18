"""Diagnostics support for HostAPI."""

from typing import Any

from homeassistant.components.diagnostics.util import async_redact_data
from homeassistant.core import HomeAssistant

from . import KIND_HOST, KIND_OPNSENSE

TO_REDACT = {
    "api_key",
    "api_secret",
    "opnsense_api_key",
    "opnsense_api_secret",
    "ssh_password",
    "ssh_key",
    "password",
    "ha_token",
    "token",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry
) -> dict[str, Any]:
    """Return diagnostics for a config entry, with secrets redacted."""
    data: dict[str, Any] = {
        "config": async_redact_data(dict(entry.data), TO_REDACT),
        "options": async_redact_data(dict(entry.options), TO_REDACT),
        "entry": {
            "entry_id": entry.entry_id,
            "version": entry.version,
            "kind": entry.data.get("kind"),
            "subentries": [
                {
                    "subentry_id": sub.subentry_id,
                    "subentry_type": sub.subentry_type,
                    "data": async_redact_data(dict(sub.data), TO_REDACT),
                }
                for sub in entry.subentries.values()
            ],
        },
    }

    if entry.data.get("kind") == KIND_HOST:
        coordinator = getattr(entry.runtime_data, "coordinator", None)
        state = getattr(coordinator, "data", None) or {}
        data["state"] = {
            "alive": state.get("alive"),
            "offline": state.get("offline"),
            "missed": state.get("missed"),
            "last_active": state.get("last_active"),
            "last_error": state.get("last_error"),
            "mac": state.get("mac"),
        }
    elif entry.data.get("kind") != KIND_OPNSENSE:
        coordinator = getattr(entry.runtime_data, "coordinator", None)
        data["state"] = {
            "device_name": getattr(coordinator, "data", None)
            and coordinator.data.get("device_name"),
        }

    return data
