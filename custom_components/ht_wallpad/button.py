"""버튼: 방별 조명 전체 끄기, 집 전체 소등."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity

from . import protocol as p
from .const import DOMAIN
from .entity import WallpadEntity


async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    wp = hass.data[DOMAIN]
    ents = [RoomLightsOff(wp, rid, rname, group) for rid, rname, group, _c, _h in wp.rooms]
    ents.append(AllLightsOff(wp))
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
