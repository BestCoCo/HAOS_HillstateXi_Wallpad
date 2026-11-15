"""조명 (채널2): 방·회로별 켜기/끄기."""
from __future__ import annotations

from homeassistant.components.light import ColorMode, LightEntity

from . import protocol as p
from .const import DOMAIN
from .entity import WallpadEntity


async def async_setup_entry(hass, entry, async_add_entities):
    wp = hass.data[DOMAIN][entry.entry_id]
    ents = []
    for rid, rname, group, circuits, _heat in wp.rooms:
        for idx, cname in enumerate(circuits, 1):
            ents.append(WallpadLight(wp, rid, rname, group, idx, cname))
    async_add_entities(ents)


def light_verify(group: int, idx: int, want: int):
    sub = group | idx

    def pred(f: bytes) -> bool:
        if f[3] != p.DEV_LIGHT or f[4] != p.CMD_REPLY:
            return False
        if f[6] == sub:
            return f[8] == want
        if f[6] == group and f[7] == 0x00 and len(f) > 8 + idx:
            return f[7 + idx] == want
        return False

    return pred


class WallpadLight(WallpadEntity, LightEntity):
    _signal = "light"
    _attr_color_mode = ColorMode.ONOFF
    _attr_supported_color_modes = {ColorMode.ONOFF}

    def __init__(self, wp, rid, rname, group, idx, cname) -> None:
        label = f"{rname} 조명 {cname}" if cname.isdigit() else f"{rname} {cname}"
        super().__init__(wp, f"{rid}_{idx}", label, "light", rid)
        self.group = group
        self.idx = idx
        self.sub = group | idx

    @property
    def is_on(self):
        return self.wp.state.lights.get(self.sub)

    @property
    def available(self) -> bool:
        return self.sub in self.wp.state.lights

    async def _set(self, on: bool) -> None:
        want = p.ON if on else p.OFF
        await self.wp.light.send(
            p.light_cmd(self.sub, on),
            sync=lambda f: p.is_reply(f, p.DEV_LIGHT, self.group),
            verify=light_verify(self.group, self.idx, want),
        )

    async def async_turn_on(self, **kwargs) -> None:
        await self._set(True)

    async def async_turn_off(self, **kwargs) -> None:
        await self._set(False)
