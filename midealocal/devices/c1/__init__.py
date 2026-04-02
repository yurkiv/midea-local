"""Midea local C1 device."""

import json
import logging
from enum import StrEnum
from typing import Any

from midealocal.const import DeviceType, ProtocolVersion
from midealocal.device import MideaDevice

from .message import (
    C1_HEATING_MODE_NAMES,
    MessageC1Response,
    MessagePower,
    MessageQuery,
    MessageSetHeating,
    MessageSetHotStyle,
)

_LOGGER = logging.getLogger(__name__)


class DeviceAttributes(StrEnum):
    """Midea C1 device attributes."""

    power = "power"
    wait_power = "wait_power"
    heating = "heating"
    warm_power = "warm_power"
    cold_power = "cold_power"
    sleep_power = "sleep_power"
    fault = "fault"
    error_code = "error_code"
    return_temperature = "return_temperature"
    current_temperature = "current_temperature"
    heating_temperature = "heating_temperature"
    heating_target_temperature = "heating_target_temperature"
    heating_gap_temperature = "heating_gap_temperature"
    heating_mode = "heating_mode"
    heating_mode_code = "heating_mode_code"
    user_mode_target_temperature = "user_mode_target_temperature"
    activity_mode_target_temperature = "activity_mode_target_temperature"
    sleep_mode_target_temperature = "sleep_mode_target_temperature"
    rate_lower = "rate_lower"
    rate_high = "rate_high"
    rated_power = "rated_power"
    last_time = "last_time"
    current_power = "current_power"
    flow_volume = "flow_volume"
    hot_style = "hot_style"
    buzzer_on = "buzzer_on"
    pump_on = "pump_on"
    three_way_mode = "three_way_mode"
    heating_unit_type = "heating_unit_type"
    light_gear = "light_gear"
    status = "status"


class MideaC1Device(MideaDevice):
    """Midea C1 device."""

    def __init__(
        self,
        name: str,
        device_id: int,
        ip_address: str,
        port: int,
        token: str,
        key: str,
        device_protocol: ProtocolVersion,
        model: str,
        subtype: int,
        customize: str,
    ) -> None:
        """Initialize Midea C1 device."""
        super().__init__(
            name=name,
            device_id=device_id,
            device_type=DeviceType.C1,
            ip_address=ip_address,
            port=port,
            token=token,
            key=key,
            device_protocol=device_protocol,
            model=model,
            subtype=subtype,
            attributes={
                DeviceAttributes.power: False,
                DeviceAttributes.wait_power: False,
                DeviceAttributes.heating: False,
                DeviceAttributes.warm_power: False,
                DeviceAttributes.cold_power: False,
                DeviceAttributes.sleep_power: False,
                DeviceAttributes.fault: False,
                DeviceAttributes.error_code: "normal",
                DeviceAttributes.return_temperature: None,
                DeviceAttributes.current_temperature: None,
                DeviceAttributes.heating_temperature: None,
                DeviceAttributes.heating_target_temperature: None,
                DeviceAttributes.heating_gap_temperature: None,
                DeviceAttributes.heating_mode: "unknown",
                DeviceAttributes.heating_mode_code: 0,
                DeviceAttributes.user_mode_target_temperature: None,
                DeviceAttributes.activity_mode_target_temperature: None,
                DeviceAttributes.sleep_mode_target_temperature: None,
                DeviceAttributes.rate_lower: 0,
                DeviceAttributes.rate_high: 0,
                DeviceAttributes.rated_power: 0,
                DeviceAttributes.last_time: 0,
                DeviceAttributes.current_power: 0,
                DeviceAttributes.flow_volume: 0,
                DeviceAttributes.hot_style: 0,
                DeviceAttributes.buzzer_on: False,
                DeviceAttributes.pump_on: False,
                DeviceAttributes.three_way_mode: "heating",
                DeviceAttributes.heating_unit_type: "floor_heating",
                DeviceAttributes.light_gear: 0,
                DeviceAttributes.status: "off",
            },
        )
        self._default_temperature_step: float = 1.0
        self._temperature_step: float = self._default_temperature_step
        self.set_customize(customize)

    @property
    def temperature_step(self) -> float | None:
        """Midea C1 device temperature step (for UI / customize)."""
        return self._temperature_step

    @property
    def heating_modes(self) -> list[str]:
        """Midea C1 space-heating mode names (Lua mode codes 1-3)."""
        return list(C1_HEATING_MODE_NAMES.values())

    def build_query(self) -> list[MessageQuery]:
        """Midea C1 device build query."""
        return [MessageQuery(self._message_protocol_version)]

    def _derive_status(self, power: bool, heating: bool, fault: bool) -> str:
        if fault:
            return "fault"
        if not power:
            return "off"
        if heating:
            return "running"
        return "idle"

    def process_message(self, msg: bytes) -> dict[str, Any]:
        """Midea C1 device process message."""
        message = MessageC1Response(msg)
        self._message_protocol_version = message.protocol_version
        _LOGGER.debug("[%s] Received: %s", self.device_id, message)
        new_status: dict[str, Any] = {}
        for status in self._attributes:
            if status == DeviceAttributes.status:
                continue
            if hasattr(message, str(status)):
                self._attributes[status] = getattr(message, str(status))
                new_status[str(status)] = self._attributes[status]

        power = bool(self._attributes[DeviceAttributes.power])
        heating = bool(self._attributes[DeviceAttributes.heating])
        fault = bool(self._attributes[DeviceAttributes.fault])
        self._attributes[DeviceAttributes.status] = self._derive_status(
            power,
            heating,
            fault,
        )
        new_status[str(DeviceAttributes.status)] = self._attributes[
            DeviceAttributes.status
        ]

        return new_status

    @staticmethod
    def _heating_mode_code(mode_name: str) -> int:
        for code, name in C1_HEATING_MODE_NAMES.items():
            if name == mode_name:
                return code
        return 1

    def _supports_segment_set(self) -> bool:
        """Segmented and extended C1 control (Lua); used on V3 local sessions."""
        return self._device_protocol_version == ProtocolVersion.V3

    def set_heating_target_temperature(
        self,
        target_temperature: float,
        heating_mode: int | None = None,
    ) -> None:
        """Set space-heating target; Lua segment 0x14 / 0x04."""
        if not self._supports_segment_set():
            _LOGGER.debug(
                "[%s] Heating target set not supported for protocol %s",
                self.device_id,
                self._device_protocol_version,
            )
            return
        message = MessageSetHeating(self._message_protocol_version)
        mode_code = (
            heating_mode
            if heating_mode is not None
            else self._heating_mode_code(
                str(self._attributes[DeviceAttributes.heating_mode]),
            )
        )
        message.heating_mode = mode_code
        message.target_temperature = target_temperature
        message.last_time = 0
        gap = self._attributes[DeviceAttributes.heating_gap_temperature]
        if isinstance(gap, (int, float)):
            message.gap_temperature = int(gap)
        else:
            message.gap_temperature = 0
        self.build_send(message)

    def set_hot_style(self, hot_style: int) -> None:
        """Set heat-supply style; Lua 0x14 / 0x02 (bit0=style1, bit1=style2)."""
        if not self._supports_segment_set():
            return
        message = MessageSetHotStyle(self._message_protocol_version)
        message.hot_style = hot_style & 0x03
        self.build_send(message)

    def set_attribute(self, attr: str, value: bool | str | float) -> None:
        """Midea C1 device set attribute."""
        if attr == DeviceAttributes.power:
            message = MessagePower(self._message_protocol_version)
            message.power = bool(value)
            self.build_send(message)
        elif attr == DeviceAttributes.heating_target_temperature and isinstance(
            value,
            int | float,
        ):
            self.set_heating_target_temperature(float(value))
        elif attr == DeviceAttributes.heating_mode and isinstance(value, str):
            target = self._attributes.get(DeviceAttributes.heating_target_temperature)
            if isinstance(target, int | float):
                self.set_heating_target_temperature(
                    float(target),
                    heating_mode=self._heating_mode_code(value),
                )
        elif attr == DeviceAttributes.hot_style and isinstance(value, int | float):
            self.set_hot_style(int(value))

    def set_customize(self, customize: str) -> None:
        """Midea C1 device set customize (JSON, same style as other appliances)."""
        self._temperature_step = self._default_temperature_step
        if customize and len(customize) > 0:
            try:
                params = json.loads(customize)
                if params and "temperature_step" in params:
                    step = params.get("temperature_step")
                    if isinstance(step, int | float):
                        self._temperature_step = float(step)
                    else:
                        _LOGGER.error(
                            "[%s] Invalid type for temperature_step: %s",
                            self.device_id,
                            step,
                        )
                if params and "refresh_interval" in params:
                    interval = params.get("refresh_interval")
                    if isinstance(interval, int | float):
                        self.set_refresh_interval(int(interval))
                    else:
                        _LOGGER.error(
                            "[%s] Invalid type for refresh_interval: %s",
                            self.device_id,
                            interval,
                        )
            except Exception:
                _LOGGER.exception("[%s] Set customize error", self.device_id)
            self.update_all(
                {
                    "temperature_step": self._temperature_step,
                    "refresh_interval": self._refresh_interval,
                },
            )


class MideaAppliance(MideaC1Device):
    """Midea C1 appliance."""
