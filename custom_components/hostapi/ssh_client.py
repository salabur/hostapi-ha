"""SSH + reachability helpers for generic HostAPI host devices.

A "host" entry manages a machine that does not run hostapi: reachability
is checked with a TCP probe or ICMP ping, and commands (reboot/shutdown/
boot-to-OS) are executed over SSH. A fresh connection is opened per
command - commands are rare, so there is no keepalive/reconnect logic.

Security notes:
- known_hosts checking is disabled (no TOFU store inside the HA
  container); scope this to trusted LANs.
- The private key may be given as PEM content or as a path.
"""

import asyncio
import logging
from dataclasses import dataclass

_LOGGER = logging.getLogger(__name__)

CONNECT_TIMEOUT = 10
COMMAND_TIMEOUT = 60
PROBE_TIMEOUT = 5


@dataclass
class SSHResult:
    """Outcome of an SSH command."""

    ok: bool
    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    error: str | None = None


@dataclass
class ProbeResult:
    """Outcome of a reachability probe."""

    ok: bool
    error: str | None = None


class SSHClient:
    """One-shot SSH connection + reachability probes for one host."""

    def __init__(
        self,
        host: str,
        port: int,
        username: str,
        password: str | None = None,
        key: str | None = None,
    ):
        self._host = host
        self._port = int(port)
        self._username = username
        self._password = password
        self._key = key

    # ---- reachability -------------------------------------------------
    async def tcp_probe(self, port: int | None = None,
                        timeout: float = PROBE_TIMEOUT) -> ProbeResult:
        """Try a TCP connect to the (SSH) port - no privileges needed."""
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(self._host, port or self._port),
                timeout,
            )
            writer.close()
            return ProbeResult(ok=True)
        except (OSError, asyncio.TimeoutError) as e:
            return ProbeResult(ok=False, error=str(e) or type(e).__name__)

    async def icmp_ping(self, timeout: float = PROBE_TIMEOUT) -> ProbeResult:
        """Unprivileged ping via the system ping binary."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "ping", "-c", "1", "-W", str(int(timeout)), self._host,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr_b = await asyncio.wait_for(
                proc.communicate(), timeout + 3)
            if proc.returncode == 0:
                return ProbeResult(ok=True)
            return ProbeResult(
                ok=False,
                error=(stderr_b or b"").decode("utf-8", "replace").strip()
                or f"ping exit {proc.returncode}",
            )
        except FileNotFoundError:
            return ProbeResult(ok=False, error="ping binary not available")
        except asyncio.TimeoutError:
            return ProbeResult(ok=False, error="ping timed out")

    # ---- SSH ----------------------------------------------------------
    def _connect_kwargs(self) -> dict:
        kwargs = {
            "host": self._host,
            "port": self._port,
            "username": self._username,
            "known_hosts": None,
        }
        if self._password:
            kwargs["password"] = self._password
        if self._key:
            kwargs["client_keys"] = [self._load_key()]
        return kwargs

    def _load_key(self):
        """Key content (PEM) as key object, else treated as path."""
        import asyncssh

        key = self._key or ""
        if "-----BEGIN" in key:
            return asyncssh.import_private_key(key)
        return key  # assume file path

    async def check_auth(self, timeout: float = CONNECT_TIMEOUT) -> ProbeResult:
        """Open an SSH connection (no command) to verify credentials."""
        try:
            import asyncssh  # noqa: F401
        except ImportError:
            return ProbeResult(ok=False, error="asyncssh not installed")
        try:
            conn = await asyncio.wait_for(
                asyncssh.connect(**self._connect_kwargs()), timeout)
        except asyncio.TimeoutError:
            return ProbeResult(ok=False, error="SSH connection timed out")
        except Exception as e:
            return ProbeResult(ok=False, error=str(e) or type(e).__name__)

        # asyncssh's SSHConnection.close() is synchronous (only wait_closed()
        # is a coroutine) - awaiting it raised "'NoneType' object can't be
        # awaited" and turned every validation into cannot_connect.
        conn.close()
        return ProbeResult(ok=True)

    async def run(self, command: str,
                  timeout: float = COMMAND_TIMEOUT) -> SSHResult:
        """Run one command on the host via a fresh SSH connection."""
        try:
            import asyncssh  # noqa: F401
        except ImportError:
            return SSHResult(ok=False, error="asyncssh not installed")
        try:
            async with asyncssh.connect(**self._connect_kwargs()) as conn:
                result = await asyncio.wait_for(conn.run(command), timeout)
                stdout = result.stdout or ""
                stderr = result.stderr or ""
                exit_code = result.exit_status
                if exit_code == 0:
                    return SSHResult(ok=True, exit_code=0,
                                     stdout=stdout, stderr=stderr)
                return SSHResult(
                    ok=False, exit_code=exit_code, stdout=stdout,
                    stderr=stderr,
                    error=f"exit {exit_code}"
                    + (f": {stderr.strip()}" if stderr.strip() else ""),
                )
        except asyncio.TimeoutError:
            return SSHResult(ok=False, error=f"command timed out ({timeout}s)")
        except Exception as e:
            return SSHResult(ok=False, error=str(e) or type(e).__name__)
