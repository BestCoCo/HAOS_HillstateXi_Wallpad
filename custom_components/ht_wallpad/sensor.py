"""센서: 콘센트별 전력(W), 엘리베이터 층·상태."""
from __future__ import annotations

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.const import UnitOfPower

from .const import DOMAIN, OUTLETS_PER_ROOM
from .entity import WallpadEntity

EV_STATUS = {0x00: "대기", 0xA6: "이동 중", 0xB6: "출발/감속", 0x01: "도착"}


async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    wp = hass.data[DOMAIN]
    ents: list = [ElevatorFloor(wp), ElevatorStatus(wp)]
    for rid, rname, group, _c, _h in wp.rooms:
        for n in range(1, OUTLETS_PER_ROOM + 1):
            ents.append(OutletWatt(wp, rid, rname, group | n, n))
    async_add_entities(ents)


class OutletWatt(WallpadEntity, SensorEntity):
    _signal = "outlet"
    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfPower.WATT

    def __init__(self, wp, rid, rname, oid, n) -> None:
        super().__init__(wp, f"outlet_{rid}_{n}_power", f"{rname} 콘센트 {n} 전력", "sensor")
        self.oid = oid

    @property
    def available(self) -> bool:
        o = self.wp.state.outlets.get(self.oid)
        return o is not None and o.watt is not None

    @property
    def native_value(self):
        o = self.wp.state.outlets.get(self.oid)
        return o.watt if o else None


class ElevatorFloor(WallpadEntity, SensorEntity):
    """월패드 엘리베이터 화면을 볼 때(호출 중)만 값이 들어온다."""
    _signal = "elevator"
    _attr_icon = "mdi:elevator"

    def __init__(self, wp) -> None:
        super().__init__(wp, "elevator_floor", "엘리베이터 층", "sensor")

    @property
    def native_value(self):
        return self.wp.state.ev_floor


class ElevatorStatus(WallpadEntity, SensorEntity):
    _signal = "elevator"
    _attr_icon = "mdi:elevator-passenger"

    def __init__(self, wp) -> None:
        super().__init__(wp, "elevator_status", "엘리베이터 상태", "sensor")

    @property
    def native_value(self):
        s = self.wp.state
        if s.ev_calling:
            return EV_STATUS.get(s.ev_status, "호출 중") if s.ev_status else "호출 중"
        return EV_STATUS.get(s.ev_status, "대기") if s.ev_status is not None else None
