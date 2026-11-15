"""화면 설정 (config flow / options flow) + 기존 YAML 가져오기."""
from __future__ import annotations

import asyncio
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_ELEVATOR_HOST, CONF_HEAT_HOST, CONF_LIGHT_HOST, CONF_PORT, CONF_PROTECTED_OUTLETS, DEFAULT_PORT,
    DOMAIN,
)
from .rooms import default_rooms_text, parse_hex_list, parse_rooms, rooms_to_text

CONF_ROOMS_TEXT = "rooms_text"
CONF_FAN_AREA = "fan_area"
CONF_MAIN_AREA = "main_area"

TEXT = selector.TextSelector()
MULTI = selector.TextSelector(selector.TextSelectorConfig(multiline=True))


async def _reachable(host: str, port: int) -> bool:
    try:
        _r, w = await asyncio.wait_for(asyncio.open_connection(host, port), 5)
        w.close()
        return True
    except Exception:  # noqa: BLE001
        return False


def _host_schema(d: dict) -> vol.Schema:
    return vol.Schema({
        vol.Required(CONF_ELEVATOR_HOST, default=d.get(CONF_ELEVATOR_HOST, "")): TEXT,
        vol.Required(CONF_LIGHT_HOST, default=d.get(CONF_LIGHT_HOST, "")): TEXT,
        vol.Required(CONF_HEAT_HOST, default=d.get(CONF_HEAT_HOST, "")): TEXT,
        vol.Required(CONF_PORT, default=d.get(CONF_PORT, DEFAULT_PORT)): vol.Coerce(int),
    })


def _options_schema(o: dict) -> vol.Schema:
    return vol.Schema({
        vol.Optional(CONF_ROOMS_TEXT, default=o.get(CONF_ROOMS_TEXT) or default_rooms_text()): MULTI,
        vol.Optional(CONF_PROTECTED_OUTLETS, default=o.get(CONF_PROTECTED_OUTLETS, "")): TEXT,
        vol.Optional(CONF_FAN_AREA, default=o.get(CONF_FAN_AREA, "거실")): TEXT,
        vol.Optional(CONF_MAIN_AREA, default=o.get(CONF_MAIN_AREA, "현관")): TEXT,
    })


def _validate_options(user_input: dict) -> dict[str, str]:
    errors: dict[str, str] = {}
    try:
        parse_rooms(user_input.get(CONF_ROOMS_TEXT, ""))
    except ValueError:
        errors[CONF_ROOMS_TEXT] = "invalid_rooms"
    try:
        parse_hex_list(user_input.get(CONF_PROTECTED_OUTLETS, ""))
    except ValueError:
        errors[CONF_PROTECTED_OUTLETS] = "invalid_hex"
    return errors


class WallpadConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        errors: dict[str, str] = {}
        if user_input is not None:
            for key in (CONF_ELEVATOR_HOST, CONF_LIGHT_HOST, CONF_HEAT_HOST):
                if not await _reachable(user_input[key], user_input[CONF_PORT]):
                    errors[key] = "cannot_connect"
            if not errors:
                return self.async_create_entry(
                    title="현대HT 월패드", data=user_input,
                    options={CONF_ROOMS_TEXT: default_rooms_text(), CONF_PROTECTED_OUTLETS: "",
                             CONF_FAN_AREA: "거실", CONF_MAIN_AREA: "현관"},
                )
        return self.async_show_form(step_id="user", data_schema=_host_schema(user_input or {}), errors=errors)

    async def async_step_import(self, conf: dict[str, Any]) -> ConfigFlowResult:
        """configuration.yaml 의 ht_wallpad: 를 화면 설정으로 옮긴다 (처음 한 번)."""
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        rooms = conf.get("rooms")
        if rooms:
            text = rooms_to_text(
                [(r["id"], r["name"], r["light_group"], r.get("lights", []), r.get("heat")) for r in rooms],
                {r["id"]: r.get("area", r["name"]) for r in rooms},
            )
        else:
            text = default_rooms_text()
        return self.async_create_entry(
            title="현대HT 월패드",
            data={k: conf[k] for k in (CONF_ELEVATOR_HOST, CONF_LIGHT_HOST, CONF_HEAT_HOST)}
            | {CONF_PORT: conf.get(CONF_PORT, DEFAULT_PORT)},
            options={
                CONF_ROOMS_TEXT: text,
                CONF_PROTECTED_OUTLETS: ",".join(str(x) for x in conf.get(CONF_PROTECTED_OUTLETS, [])),
                CONF_FAN_AREA: conf.get(CONF_FAN_AREA, "거실"),
                CONF_MAIN_AREA: conf.get(CONF_MAIN_AREA, "현관"),
            },
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return WallpadOptionsFlow()


class WallpadOptionsFlow(OptionsFlow):
    """구성: 방 배치·보호 콘센트·영역, 그리고 EW11 주소."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return self.async_show_menu(step_id="init", menu_options=["rooms", "hosts"])

    async def async_step_rooms(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = _validate_options(user_input)
            if not errors:
                return self.async_create_entry(data=user_input)
        return self.async_show_form(
            step_id="rooms", data_schema=_options_schema(user_input or dict(self.config_entry.options)),
            errors=errors,
        )

    async def async_step_hosts(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            for key in (CONF_ELEVATOR_HOST, CONF_LIGHT_HOST, CONF_HEAT_HOST):
                if not await _reachable(user_input[key], user_input[CONF_PORT]):
                    errors[key] = "cannot_connect"
            if not errors:
                self.hass.config_entries.async_update_entry(self.config_entry, data=user_input)
                return self.async_create_entry(data=dict(self.config_entry.options))
        return self.async_show_form(
            step_id="hosts", data_schema=_host_schema(user_input or dict(self.config_entry.data)), errors=errors,
        )
