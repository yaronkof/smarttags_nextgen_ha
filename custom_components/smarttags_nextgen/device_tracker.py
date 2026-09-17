"""Device tracker entities for SmartThings Find NextGen."""

from __future__ import annotations

from typing import Any

from homeassistant.components.device_tracker import TrackerEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import SmartTagCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up SmartTag trackers and add newly discovered tags dynamically."""
    coordinator: SmartTagCoordinator = hass.data[DOMAIN][entry.entry_id]
    known_device_ids: set[str] = set()

    @callback
    def async_add_new_entities() -> None:
        data = coordinator.data or {}
        new_device_ids = set(data) - known_device_ids
        if not new_device_ids:
            return

        async_add_entities(
            [SmartTagTracker(coordinator, device_id) for device_id in new_device_ids]
        )
        known_device_ids.update(new_device_ids)

    async_add_new_entities()
    entry.async_on_unload(coordinator.async_add_listener(async_add_new_entities))


class SmartTagTracker(CoordinatorEntity[SmartTagCoordinator], TrackerEntity):
    """Representation of one Samsung SmartTag on the Home Assistant map."""

    _attr_icon = "mdi:tag-location"

    def __init__(self, coordinator: SmartTagCoordinator, device_id: str) -> None:
        super().__init__(coordinator)
        self.device_id = device_id
        self._attr_unique_id = f"smarttag_{device_id}"

    @property
    def tag_data(self) -> dict[str, Any]:
        """Return the latest data block for this SmartTag."""
        return (self.coordinator.data or {}).get(self.device_id, {})

    @property
    def name(self) -> str:
        """Return the user-facing SmartTag name."""
        return self.tag_data.get("name", "SmartTag")

    @property
    def latitude(self) -> float | None:
        """Return the last known latitude."""
        return self.tag_data.get("latitude")

    @property
    def longitude(self) -> float | None:
        """Return the last known longitude."""
        return self.tag_data.get("longitude")

    @property
    def battery_level(self) -> int | None:
        """Return an approximate battery percentage for backwards compatibility."""
        battery_map = {"HIGH": 100, "MEDIUM": 50, "LOW": 10}
        return battery_map.get(self.tag_data.get("battery", "UNKNOWN"))

    @property
    def device_info(self) -> DeviceInfo:
        """Group the tracker under a physical SmartTag device."""
        return DeviceInfo(
            identifiers={(DOMAIN, self.device_id)},
            name=self.name,
            manufacturer="Samsung",
            model=self.tag_data.get("model") or "SmartTag",
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose useful Samsung metadata without inventing precision."""
        return {
            "location_type": self.tag_data.get("location_type"),
            "last_seen": self.tag_data.get("last_seen"),
            "battery_state": self.tag_data.get("battery"),
        }
