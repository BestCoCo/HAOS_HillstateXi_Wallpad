"""이진 센서: 엘리베이터 호출 중, 일괄소등 설정."""
from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity

from .const import DOMAIN
from .entity import WallpadEntity


async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    wp = hass.data[DOMAIN]
    async_add_entities([ElevatorCalling(wp), BatchOff(wp)])


class ElevatorCalling(WallpadEntity, BinarySensorEntity):
    _signal = "elevator"
    _attr_icon = "mdi:elevator"

    def __init__(self, wp) -> None:
        super().__init__(wp, "elevator_calling", "엘리베이터 호출 중", "binary_sensor")

    @property
    def is_on(self):
        return self.wp.state.ev_calling


class BatchOff(WallpadEntity, BinarySensorEntity):
    _signal = "batch"
    _attr_icon = "mdi:lightbulb-group-off"

    def __init__(self, wp) -> None:
        super().__init__(wp, "batch_off", "일괄소등 설정", "binary_sensor")

    @property
    def is_on(self):
        return self.wp.state.batch_off
