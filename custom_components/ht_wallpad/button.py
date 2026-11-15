"""버튼: 방별 조명 전체 끄기, 집 전체 소등."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity

from . import protocol as p
from .const import DOMAIN
from .entity import WallpadEntity


async def async_setup_entry(hass, entry, async_add_entities):
    wp = hass.data[DOMAIN][entry.entry_id]
    ents = [RoomLightsOff(wp, rid, rname, group) for rid, rname, group, _c, _h in wp.rooms]
    ents.append(AllLightsOff(wp))
    ents.append(ElevatorCall(wp))
    async_add_entities(ents)


async def group_off(wp, group: int) -> bool:
    return await wp.light.send(
        p.light_cmd(group, False),
        sync=lambda f: p.is_reply(f, p.DEV_LIGHT, group),
        verify=lambda f: p.is_reply(f, p.DEV_LIGHT, group)
        and ((f[7] != 0x00 and f[8] == p.OFF) or (f[7] == 0x00 and all(v == p.OFF for v in f[8:-2]))),
    )


class RoomLightsOff(WallpadEntity, ButtonEntity):
    _attr_icon = "mdi:lightbulb-off"

    def __init__(self, wp, rid, rname, group) -> None:
        super().__init__(wp, f"{rid}_lights_off", f"{rname} 조명 전체 끄기", "button", rid)
        self.group = group

    async def async_press(self) -> None:
        await group_off(self.wp, self.group)


class AllLightsOff(WallpadEntity, ButtonEntity):
    _attr_icon = "mdi:home-lightbulb-outline"

    def __init__(self, wp) -> None:
        super().__init__(wp, "all_lights_off", "집 전체 소등", "button")

    async def async_press(self) -> None:
        for _rid, _n, group, _c, _h in self.wp.rooms:
            await group_off(self.wp, group)


class ElevatorCall(WallpadEntity, ButtonEntity):
    """일괄(2A) 응답 직후 약 0.2초 뒤, 월패드가 엘리베이터를 묻기 직전에 '호출' 응답을 미리 보낸다.
    접수되면 월패드의 엘리베이터 상태가 00이 아니게 되거나 스위치가 06(호출 중)을 보낸다."""
    _attr_icon = "mdi:elevator-down"

    def __init__(self, wp) -> None:
        super().__init__(wp, "elevator_call", "엘리베이터 호출", "button")

    async def async_press(self) -> None:
        if self.wp.state.ev_calling:
            return
        delays = [0.20, 0.21, 0.22, 0.19, 0.23, 0.18, 0.24, 0.25, 0.27, 0.30, 0.16, 0.32]

        def accepted(f: bytes) -> bool:
            if f[3] != p.DEV_ELEVATOR:
                return False
            if f[4] == p.CMD_QUERY and len(f) >= 13:
                return f[8] != 0x00
            return f[4] == p.CMD_REPLY and len(f) >= 11 and f[8] == 0x06

        await self.wp.ev.send_before(
            p.elevator_call_reply(),
            after=lambda f: f[3] == p.DEV_BATCH and f[4] == p.CMD_REPLY,
            verify=accepted,
            delays=delays,
        )
