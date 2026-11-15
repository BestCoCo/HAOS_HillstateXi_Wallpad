"""공통 엔티티 베이스."""
from __future__ import annotations

from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity

from .const import DOMAIN, SIGNAL_UPDATE


class WallpadEntity(Entity):
    _attr_should_poll = False
    _signal: str = ""

    def __init__(self, wallpad, object_id: str, name: str, domain: str, device: str = "main") -> None:
        """device: 방 id(rooms 의 id), "fan", "main" — 기기와 영역(suggested_area)을 정한다."""
        self.wp = wallpad
        self._attr_unique_id = f"{DOMAIN}_{object_id}"
        self._attr_name = name
        self.entity_id = f"{domain}.wallpad_{object_id}"
        dev_name, area = wallpad.device_meta(device)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"wallpad_{device}")},
            name=dev_name,
            manufacturer="현대에이치티",
            model="HDHN-3500-TH",
            suggested_area=area,
        )

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(self.hass, f"{SIGNAL_UPDATE}_{self._signal}", self.async_write_ha_state)
        )
