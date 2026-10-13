"""
telephony/protocol.py
======================
Binary (de)serialization for the Asterisk AudioSocket protocol.

Wire format (all integers big-endian):
    +--------+------------------+------------------------+
    |  Type  |   Payload Len    |         Payload         |
    | 1 byte |     2 bytes      |     <Payload Len> bytes |
    +--------+------------------+------------------------+

Message types (per Asterisk `res_audiosocket.h` / official protocol spec at
docs.asterisk.org/Configuration/Channel-Drivers/AudioSocket):
    0x00  KIND_HANGUP    - server should terminate the call (no payload)
    0x01  KIND_UUID      - 16-byte call UUID, sent once as the first message
    0x03  KIND_DTMF      - 1-byte ASCII DTMF digit
    0x10  KIND_AUDIO     - raw 16-bit signed LE PCM, 8kHz mono (20ms = 320 bytes)
    0xFF  KIND_ERROR     - error indication (no payload, or 1-byte code)

Architectural decision:
    Protocol (de)serialization is isolated from I/O and business logic.
    `server.py` never touches raw bytes directly; it only exchanges
    `AudioSocketMessage` objects with this module. This keeps the wire
    format swappable/testable in complete isolation (Single Responsibility
    + Interface Segregation).
"""

from __future__ import annotations

import struct
import uuid
from dataclasses import dataclass
from enum import IntEnum


class MessageKind(IntEnum):
    """AudioSocket message type identifiers (per Asterisk's res_audiosocket.h)."""

    HANGUP = 0x00
    UUID = 0x01
    DTMF = 0x03
    AUDIO = 0x10
    ERROR = 0xFF


class AudioSocketProtocolError(Exception):
    """Raised on malformed AudioSocket frames (bad header, truncated payload, etc.)."""


_HEADER_STRUCT = struct.Struct(">BH")  # 1-byte type, 2-byte big-endian unsigned length
HEADER_SIZE = _HEADER_STRUCT.size
UUID_PAYLOAD_SIZE = 16


@dataclass(frozen=True, slots=True)
class AudioSocketMessage:
    """A single decoded AudioSocket protocol message."""

    kind: MessageKind
    payload: bytes

    @property
    def call_uuid(self) -> uuid.UUID:
        """Interpret payload as the 16-byte call UUID (only valid for KIND_UUID)."""
        if self.kind is not MessageKind.UUID:
            raise AudioSocketProtocolError(f"Cannot read UUID from message kind {self.kind!r}")
        if len(self.payload) != UUID_PAYLOAD_SIZE:
            raise AudioSocketProtocolError(f"UUID payload must be {UUID_PAYLOAD_SIZE} bytes, got {len(self.payload)}")
        return uuid.UUID(bytes=self.payload)


def encode_header(kind: MessageKind, payload_length: int) -> bytes:
    """Pack a 3-byte AudioSocket header."""
    if not (0 <= payload_length <= 0xFFFF):
        raise AudioSocketProtocolError(f"Payload length {payload_length} exceeds 16-bit range")
    return _HEADER_STRUCT.pack(int(kind), payload_length)


def encode_audio_frame(pcm_bytes: bytes) -> bytes:
    """Encode a raw PCM chunk as a complete KIND_AUDIO AudioSocket message."""
    return encode_header(MessageKind.AUDIO, len(pcm_bytes)) + pcm_bytes


def encode_hangup() -> bytes:
    """Encode a KIND_HANGUP message (empty payload)."""
    return encode_header(MessageKind.HANGUP, 0)


# SIP request methods start with these ASCII letters. Softphones often get
# pointed at AudioSocket ports (9092+) by mistake; surface a clear hint.
_SIP_FIRST_BYTE_HINT = {
    0x41: "ACK",
    0x42: "BYE",
    0x43: "CANCEL",
    0x49: "INVITE",
    0x4F: "OPTIONS",
    0x52: "REGISTER",
}


def decode_header(header_bytes: bytes) -> tuple[MessageKind, int]:
    """Unpack a 3-byte header into (kind, payload_length)."""
    if len(header_bytes) != HEADER_SIZE:
        raise AudioSocketProtocolError(f"Header must be exactly {HEADER_SIZE} bytes, got {len(header_bytes)}")
    raw_kind, length = _HEADER_STRUCT.unpack(header_bytes)
    try:
        kind = MessageKind(raw_kind)
    except ValueError as exc:
        sip = _SIP_FIRST_BYTE_HINT.get(raw_kind)
        if sip is not None:
            raise AudioSocketProtocolError(
                f"Unknown AudioSocket message kind: 0x{raw_kind:02X} "
                f"(looks like SIP {sip} — configure softphones for Asterisk SIP "
                f"UDP :5060, not this AudioSocket TCP port)"
            ) from exc
        raise AudioSocketProtocolError(f"Unknown AudioSocket message kind: 0x{raw_kind:02X}") from exc
    return kind, length


async def read_message(reader) -> AudioSocketMessage:
    """
    Read and decode exactly one AudioSocket message from an asyncio StreamReader.

    Raises:
        AudioSocketProtocolError: on malformed header/payload.
        asyncio.IncompleteReadError: propagated when the peer closes mid-frame;
            callers should treat this as a normal hangup signal.
    """
    header_bytes = await reader.readexactly(HEADER_SIZE)
    kind, length = decode_header(header_bytes)
    payload = await reader.readexactly(length) if length > 0 else b""
    return AudioSocketMessage(kind=kind, payload=payload)