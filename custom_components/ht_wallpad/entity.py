"""공통 엔티티 베이스."""
from __future__ import annotations

from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity

from .const import DOMAIN, SIGNAL_UPDATE


class WallpadEntity(Entity):
    _attr_should_poll = False
    _signal: str = ""

    def __init__(self, wallpad, object_id: str, name: str, domain: str) -> None:
        self.wp = wallpad
        self._attr_unique_id = f"{DOMAIN}_{object_id}"
        self._attr_name = name
        self.entity_id = f"{domain}.wallpad_{object_id}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "wallpad")},
            name="월패드 (현대HT HDHN-3500)",
            manufacturer="현대에이치티",
            model="HDHN-3500-TH",
        )

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(self.hass, f"{SIGNAL_UPDATE}_{self._signal}", self.async_write_ha_state)
        )
