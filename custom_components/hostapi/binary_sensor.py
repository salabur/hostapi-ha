"""Binary sensor platform for HostAPI - alive check of generic SSH hosts."""

from . import KIND_HOST
from .host_entities import async_setup_binary_sensors


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up the alive binary sensor for a generic SSH host entry."""
    if entry.data.get("kind") != KIND_HOST:
        return
    await async_setup_binary_sensors(hass, entry, async_add_entities)
