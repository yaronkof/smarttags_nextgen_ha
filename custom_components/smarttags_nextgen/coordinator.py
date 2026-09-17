"""Data coordinator for SmartThings Find NextGen."""

from __future__ import annotations

from datetime import timedelta
import html
import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    SmartTagsAPI,
    SmartTagsAuthenticationError,
    SmartTagsConnectionError,
)
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

UPDATE_INTERVAL = timedelta(minutes=5)


class SmartTagCoordinator(DataUpdateCoordinator[dict[str, dict[str, Any]]]):
    """Fetch and normalize SmartTag data for Home Assistant entities."""

    def __init__(self, hass: HomeAssistant, jsession_id: str, region: str) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=UPDATE_INTERVAL,
            always_update=False,
        )
        self.api = SmartTagsAPI(async_get_clientsession(hass), jsession_id, region)

    async def _async_update_data(self) -> dict[str, dict[str, Any]]:
        """Refresh authentication, discover tags, and synchronize their states."""
        try:
            await self.api.refresh_csrf_token()
            devices = await self.api.get_devices()
        except SmartTagsAuthenticationError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except SmartTagsConnectionError as err:
            raise UpdateFailed(str(err)) from err

        tags = [device for device in devices if device.get("deviceType") == "TAG"]
        _LOGGER.debug("SmartThings Find identified %s SmartTags", len(tags))

        old_data = self.data or {}
        normalized_data: dict[str, dict[str, Any]] = {}

        for tag in tags:
            device_id = tag.get("dvceID")
            if not device_id:
                _LOGGER.warning("Ignoring a SmartTag without a device ID")
                continue

            raw_name = tag.get("nickName") or tag.get("modelName") or "SmartTag"
            name = html.unescape(html.unescape(str(raw_name)))
            old_tag_data = old_data.get(device_id, {})

            tag_data: dict[str, Any] = {
                "device_id": device_id,
                "name": name,
                "model": tag.get("modelName"),
                "latitude": old_tag_data.get("latitude"),
                "longitude": old_tag_data.get("longitude"),
                "battery": old_tag_data.get("battery"),
                "location_type": old_tag_data.get("location_type"),
                "last_seen": old_tag_data.get("last_seen"),
            }

            try:
                operations = await self.api.set_last_select(device_id)
            except SmartTagsAuthenticationError as err:
                raise ConfigEntryAuthFailed(str(err)) from err
            except SmartTagsConnectionError as err:
                # One device failing should not hide every other known tag.
                _LOGGER.warning("Failed to update SmartTag %s: %s", name, err)
                normalized_data[device_id] = tag_data
                continue

            for operation in operations:
                if not isinstance(operation, dict):
                    continue

                operation_type = operation.get("oprnType")
                if operation_type in ("LOCATION", "OFFLINE_LOC"):
                    latitude = _safe_float(operation.get("latitude"))
                    longitude = _safe_float(operation.get("longitude"))
                    if latitude is not None and longitude is not None:
                        tag_data["latitude"] = latitude
                        tag_data["longitude"] = longitude

                    tag_data["location_type"] = (
                        "offline"
                        if operation_type == "OFFLINE_LOC"
                        else operation.get("locationType", "gps")
                    )

                    timestamp = _extract_timestamp(operation)
                    if timestamp:
                        tag_data["last_seen"] = timestamp

                elif operation_type == "CHECK_CONNECTION":
                    tag_data["battery"] = operation.get("battery")

            _LOGGER.debug(
                "SmartTag update: %s lat=%s lon=%s last_seen=%s",
                name,
                tag_data["latitude"],
                tag_data["longitude"],
                tag_data["last_seen"],
            )
            normalized_data[device_id] = tag_data

        return normalized_data


def _safe_float(value: Any) -> float | None:
    """Convert Samsung coordinate values without failing the entire refresh."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _extract_timestamp(operation: dict[str, Any]) -> str | None:
    """Extract Samsung's GPS timestamp from known response shapes."""
    for key in ("extra", "encLocation"):
        block = operation.get(key)
        if isinstance(block, dict) and block.get("gpsUtcDt"):
            return str(block["gpsUtcDt"])
    return None
