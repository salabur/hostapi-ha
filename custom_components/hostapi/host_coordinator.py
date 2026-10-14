"""Alive-polling coordinator for generic SSH host devices."""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .ssh_client import SSHClient

if TYPE_CHECKING:
    pass

_LOGGER = logging.getLogger(__name__)

DEFAULT_ALIVE_METHOD = "tcp"
DEFAULT_POLL_INTERVAL = 30
DEFAULT_OFFLINE_THRESHOLD = 5
MIN_POLL_INTERVAL = 5


def host_setting(entry, key: str, default=None):
    """Options override entry data (options flow edits live settings)."""
    return entry.options.get(key, entry.data.get(key, default))


@dataclass
class HostEntryData:
    """Runtime data stored per 'host' config entry."""

    client: object
    coordinator: DataUpdateCoordinator


class HostStateCoordinator(DataUpdateCoordinator):
    """Polls one SSH host for reachability.

    Every poll_interval a TCP probe (default) or ICMP ping runs. Each
    failure increments `missed`; the host counts as offline only after
    `offline_threshold` consecutive misses (single blips don't flap the
    binary sensor). Every success resets the counter and stamps
    `last_active`.
    """

    def __init__(self, hass, entry, client):
        self.entry = entry
        self._client = client  # aiohttp session (wake/opnsense POSTs)
        data = entry.data
        self._alive_method = host_setting(entry, "alive_method",
                                          DEFAULT_ALIVE_METHOD)
        self._alive_port = int(host_setting(entry, "alive_port")
                               or data.get("ssh_port", 22))
        self._offline_threshold = int(
            host_setting(entry, "offline_threshold",
                         DEFAULT_OFFLINE_THRESHOLD))
        self.ssh = SSHClient(
            host=data.get("host"),
            port=data.get("ssh_port", 22),
            username=data.get("ssh_user", "root"),
            password=data.get("ssh_password"),
            key=data.get("ssh_key"),
        )
        poll = max(
            MIN_POLL_INTERVAL,
            int(host_setting(entry, "poll_interval", DEFAULT_POLL_INTERVAL)),
        )
        super().__init__(
            hass,
            _LOGGER,
            name=f"hostapi_host_{data.get('host')}",
            update_interval=timedelta(seconds=poll),
        )
        # Seed before the first refresh so entities render immediately
        self.data = {
            "alive": False,
            "offline": True,
            "missed": 0,
            "last_active": None,
            "last_error": None,
        }

    @property
    def alive_method(self) -> str:
        return self._alive_method

    @property
    def alive_port(self) -> int:
        return self._alive_port

    async def _async_update_data(self):
        return await self.poll_once()

    async def poll_once(self) -> dict:
        """One reachability check; returns the (new) coordinator data."""
        if self._alive_method == "icmp":
            probe = await self.ssh.icmp_ping()
        else:
            probe = await self.ssh.tcp_probe(self._alive_port)

        data = dict(self.data or {})
        if probe.ok:
            data.update(
                alive=True,
                offline=False,
                missed=0,
                last_error=None,
                last_active=datetime.now(timezone.utc).isoformat(),
            )
        else:
            missed = int(data.get("missed", 0)) + 1
            data.update(
                alive=False,
                missed=missed,
                last_error=probe.error,
                offline=missed >= self._offline_threshold,
            )
        self.async_set_updated_data(data)
        return data
