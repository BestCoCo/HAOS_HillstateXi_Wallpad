"""난방 (채널3, Honeywell 밸브제어기 경유): 켜기/끄기, 설정 온도."""
from __future__ import annotations

from homeassistant.components.climate import ClimateEntity, ClimateEntityFeature, HVACMode
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature

from . import protocol as p
from .const import DOMAIN
from .entity import WallpadEntity


async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    wp = hass.data[DOMAIN]
    async_add_entities(
        WallpadHeat(wp, rid, rname, heat) for rid, rname, _g, _c, heat in wp.rooms if heat is not None
    )


class WallpadHeat(WallpadEntity, ClimateEntity):
    _signal = "heat"
    _attr_hvac_modes = [HVACMode.HEAT, HVACMode.OFF]
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.TURN_ON | ClimateEntityFeature.TURN_OFF
    )
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_target_temperature_step = 1
    _attr_min_temp = 5
    _attr_max_temp = 40

    def __init__(self, wp, rid, rname, room) -> None:
        super().__init__(wp, f"heat_{rid}", f"{rname} 난방", "climate")
        self.room = room

    @property
    def _h(self):
        return self.wp.state.heats.get(self.room)

    @property
    def available(self) -> bool:
        return self._h is not None and self._h.mode is not None

    @property
    def hvac_mode(self):
        return HVACMode.HEAT if self._h and self._h.mode == p.HEAT_ON else HVACMode.OFF

    @property
    def current_temperature(self):
        return self._h.current if self._h else None

    @property
    def target_temperature(self):
        return self._h.target if self._h else None

    @property
    def extra_state_attributes(self):
        mode = self._h.mode if self._h else None
        return {"월패드_모드": {p.HEAT_ON: "난방", p.HEAT_OFF: "꺼짐", p.HEAT_AWAY: "외출"}.get(mode, mode)}

    def _sync(self, f: bytes) -> bool:
        return p.is_reply(f, p.DEV_HEAT, self.room)

    async def async_set_hvac_mode(self, hvac_mode) -> None:
        on = hvac_mode == HVACMode.HEAT
        want = p.HEAT_ON if on else p.HEAT_OFF
        await self.wp.heat.send(
            p.heat_power_cmd(self.room, on),
            sync=self._sync,
            verify=lambda f: p.is_reply(f, p.DEV_HEAT, self.room) and len(f) >= 13 and f[8] == want,
        )

    async def async_turn_on(self) -> None:
        await self.async_set_hvac_mode(HVACMode.HEAT)

    async def async_turn_off(self) -> None:
        await self.async_set_hvac_mode(HVACMode.OFF)

    async def async_set_temperature(self, **kwargs) -> None:
        temp = kwargs.get(ATTR_TEMPERATURE)
        if temp is None:
            return
        t = int(round(temp))
        await self.wp.heat.send(
            p.heat_target_cmd(self.room, t),
            sync=self._sync,
            verify=lambda f: p.is_reply(f, p.DEV_HEAT, self.room) and len(f) >= 13 and f[10] == t,
        )
