"""Discovery for HostAPI using mDNS/Zeroconf."""

import logging

from homeassistant.helpers.zeroconf import async_service_info_received

from . import DOMAIN

_LOGGER = logging.getLogger(__name__)

SERVICE_TYPE = "_hostapi._tcp.local."
SERVICE_TYPE_ALT = "_hostapi._http._tcp.local."


async def async_setup_entry(hass, entry):
    """Set up HostAPI from discovered zeroconf entry."""
    await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": "zeroconf"},
        data=entry,
    )
    return True


def from_zeroconf_zeroconf_service_info(service_info, hostname: str):
    """Convert zeroconf service info to config entry data."""
    host = service_info.hostname or hostname.replace(".local.", "")
    port = service_info.port or 8080
    return {
        "host": host,
        "port": port,
        "name": service_info.name,
    }