# HostAPI Home Assistant Integration

Home Assistant integration for [HostAPI](https://gitlab.x.asdfg.men/code/hostapi) - a REST API for host control and display management.

## Features

- **Health sensor** - alive/health status of the hostapi service
- **Display profile select** - switch display profiles from HA
- **Script buttons** - run configured scripts
- **Service controls** - start/stop/restart hostapi and systemd services
- **Host controls** - restart or shutdown the host machine
- **mDNS discovery** - hostapi advertises itself, HA auto-discovers it

## Installation (HACS)

1. In HACS, go to **Settings → Add custom repository**
2. Enter `https://github.com/salabur/hostapi-ha` as the repository URL
3. Select **Integration** as the category and click **ADD**
4. Search for "HostAPI" in HACS and install it
5. Restart Home Assistant

## Manual Installation

Copy the `custom_components/hostapi/` directory into HA's `config/custom_components/` and restart.

## Configuration

1. In HA: **Settings → Devices & Services → Add Integration → HostAPI**
2. It is auto-discovered via mDNS - enter the host, port (default 8080) and an API key
3. Create the API key in the HostAPI web UI (**API Keys** tab)
