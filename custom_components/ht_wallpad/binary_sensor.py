"""이진 센서: 엘리베이터 호출 중, 일괄소등 설정."""
from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.const import EntityCategory

from .const import DOMAIN
from .entity import WallpadEntity


async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    wp = hass.data[DOMAIN]
    async_add_entities([ElevatorCalling(wp), BatchOff(wp)] + [Ew11Connected(wp, b) for b in wp.buses])


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


EW11_NAMES = {"elevator": "EW11 1 일괄·엘리베이터", "light": "EW11 2 조명·콘센트", "heat": "EW11 3 난방·환기"}


class Ew11Connected(WallpadEntity, BinarySensorEntity):
    _signal = "conn"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, wp, bus) -> None:
        super().__init__(wp, f"ew11_{bus.name}", f"{EW11_NAMES.get(bus.name, bus.name)} 연결", "binary_sensor")
        self.bus = bus

    @property
    def is_on(self):
        return self.bus.connected

    @property
    def extra_state_attributes(self):
        return {"host": self.bus.host}
