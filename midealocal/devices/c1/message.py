"""Midea local C1 message.

Protocol layout follows Meiju Lua T_0000_C1_2760001Z (electric wall-hung boiler):
- Query: type 0x03, body 0x01 0x01 (status)
- Power set: type 0x02, body 0x01/0x02 + 0x01
- Segmented control: body 0x14; sub 0x04 heat (hot_style segment not used for this model)
"""

from midealocal.const import DeviceType
from midealocal.message import (
    ListTypes,
    MessageBody,
    MessageRequest,
    MessageResponse,
    MessageType,
)

C1_HEATING_MODE_NAMES: dict[int, str] = {
    1: "user",
    2: "activity",
    3: "sleep",
}

# Minimum body length for long status (profile temps at body[23:26]).
C1_LONG_STATUS_MIN_LEN = 26


def c1_error_code(body: bytearray) -> str:  # noqa: PLR0911
    """Return Lua-style error_code from body[3] and body[4] (priority order)."""
    b14 = body[3] if len(body) > 3 else 0
    b15 = body[4] if len(body) > 4 else 0
    if b14 & 0x01:
        return "F0"
    if b15 & 0x01:
        return "F2"
    if b14 & 0x80:
        return "E8"
    if b14 & 0x40:
        return "E7"
    if b14 & 0x10:
        return "E3"
    if b14 & 0x04:
        return "E1"
    return "normal"


def c1_long_status_applies(message_type: MessageType, body_type: int) -> bool:
    """Return whether the Lua long-status parse branch applies."""
    bt = int(body_type)
    return (
        (message_type == MessageType.set and bt in (0x01, 0x02, 0x04, 0x14))
        or (message_type == MessageType.query and bt == ListTypes.X01)
        or (message_type == MessageType.notify1 and bt in (0x00, ListTypes.X01))
    )


class MessageC1Base(MessageRequest):
    """C1 message base."""

    def __init__(
        self,
        protocol_version: int,
        message_type: MessageType,
        body_type: ListTypes,
    ) -> None:
        """Initialize C1 message base."""
        super().__init__(
            device_type=DeviceType.C1,
            protocol_version=protocol_version,
            message_type=message_type,
            body_type=body_type,
        )

    @property
    def _body(self) -> bytearray:
        raise NotImplementedError


class MessageQuery(MessageC1Base):
    """C1 message query (full status)."""

    def __init__(self, protocol_version: int) -> None:
        """Initialize C1 message query."""
        super().__init__(
            protocol_version=protocol_version,
            message_type=MessageType.query,
            body_type=ListTypes.X01,
        )

    @property
    def _body(self) -> bytearray:
        return bytearray([0x01])


class MessagePower(MessageC1Base):
    """C1 message power."""

    def __init__(self, protocol_version: int) -> None:
        """Initialize C1 message power."""
        super().__init__(
            protocol_version=protocol_version,
            message_type=MessageType.set,
            body_type=ListTypes.X02,
        )
        self.power = False

    @property
    def _body(self) -> bytearray:
        if self.power:
            self.body_type = ListTypes.X01
        else:
            self.body_type = ListTypes.X02
        return bytearray([0x01])


class MessageSetHeating(MessageC1Base):
    """C1 segmented set: space heating (Lua 0x14, heating_target_temperature)."""

    def __init__(self, protocol_version: int) -> None:
        """Initialize C1 heating segment set."""
        super().__init__(
            protocol_version=protocol_version,
            message_type=MessageType.set,
            body_type=ListTypes.X14,
        )
        self.heating_mode: int = 1
        self.target_temperature: float = 40.0
        self.last_time: int = 0
        self.gap_temperature: int = 0

    @property
    def _body(self) -> bytearray:
        temp = round(self.target_temperature) & 0xFF
        return bytearray(
            [
                0x04,
                self.heating_mode & 0xFF,
                temp,
                self.last_time & 0xFF,
                self.gap_temperature & 0xFF,
            ],
        )


class C1GeneralMessageBody(MessageBody):
    """C1 long status body (Lua parseByteToJson main branch).

    Lua bodyBytes index n maps to Python body[n - 11] when aligned to frame.
    """

    def __init__(self, body: bytearray) -> None:
        """Initialize C1 message general body."""
        super().__init__(body)
        flags = body[2] if len(body) > 2 else 0
        self.power = (flags & 0x01) > 0
        # Lua 待机 / Meiju key wait_power: appliance in standby (bit 0x02).
        self.standby = (flags & 0x02) > 0
        # Lua 加热中 / Meiju key hot_power: actively heating (bit 0x04).
        self.heating = (flags & 0x04) > 0
        self.warm_power = (flags & 0x08) > 0
        self.cold_power = (flags & 0x10) > 0
        self.sleep_power = (flags & 0x20) > 0

        self.error_code = c1_error_code(body)
        self.fault = self.error_code != "normal"

        self.return_temperature = float(body[7] if len(body) > 7 else 0)
        self.current_temperature = float(body[8] if len(body) > 8 else 0)

        self.heating_temperature = float(body[12] if len(body) > 12 else 0)
        self.heating_target_temperature = float(body[13] if len(body) > 13 else 0)
        raw_mode = body[14] if len(body) > 14 else 0
        self.heating_mode = C1_HEATING_MODE_NAMES.get(raw_mode, "unknown")
        self.heating_gap_temperature = float(body[15] if len(body) > 15 else 0)

        self.last_time = int(body[16] if len(body) > 16 else 0)
        cur_rate_lower = int(body[17] if len(body) > 17 else 0)
        cur_rate_high = int(body[18] if len(body) > 18 else 0)
        # Lua calculate: [current_power] = [cur_rate_high] * 256 + [cur_rate_lower]
        self.current_power = cur_rate_high * 256 + cur_rate_lower
        self.flow_volume = int(body[19] if len(body) > 19 else 0)

        packed = body[22] if len(body) > 22 else 0
        self.pump_on = (packed & 0x02) > 0
        self.three_way_mode = "alternate" if (packed & 0x04) else "heating"
        self.heating_unit_type = "radiator" if (packed & 0x08) else "floor_heating"

        self.user_mode_target_temperature: float | None = None
        self.activity_mode_target_temperature: float | None = None
        self.sleep_mode_target_temperature: float | None = None
        if len(body) > 25:
            self.user_mode_target_temperature = float(body[23])
            self.activity_mode_target_temperature = float(body[24])
            self.sleep_mode_target_temperature = float(body[25])


class MessageC1Response(MessageResponse):
    """C1 message response."""

    def __init__(self, message: bytes) -> None:
        """Initialize C1 message response."""
        super().__init__(bytearray(message))
        raw = super().body
        bt = int(self.body_type)
        long_ok = (
            c1_long_status_applies(self.message_type, bt)
            and len(raw) >= C1_LONG_STATUS_MIN_LEN
        )
        if long_ok:
            self.set_body(C1GeneralMessageBody(raw))
        self.set_attr()
