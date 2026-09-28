"""Strict JSON, framing and envelopes (the same rules as the C# package)."""

from __future__ import annotations

import asyncio
import struct

import pytest

from unity_ludometry_mcp.protocol import envelope, json_codec
from unity_ludometry_mcp.protocol.errors import FRAME_TOO_LARGE, INVALID_FRAME, ProtocolException
from unity_ludometry_mcp.protocol.framing import encode_frame, read_frame
from unity_ludometry_mcp.protocol.version import PROTOCOL_MAJOR, is_compatible


@pytest.mark.parametrize("text", ['{"a":1,"a":2}', "NaN", "[1,]", "{", "01", "[Infinity]", "1 2", '"\\x"'])
def test_invalid_json_is_rejected(text: str) -> None:
    with pytest.raises(ProtocolException) as e:
        json_codec.loads(text)
    assert e.value.code == INVALID_FRAME


def test_json_limits_and_utf8() -> None:
    with pytest.raises(ProtocolException):
        json_codec.loads(b'"\xc3\x28"')
    with pytest.raises(ProtocolException):
        json_codec.loads("[" * 200 + "]" * 200)
    with pytest.raises(ProtocolException):
        json_codec.loads("[" * 100_000 + "]" * 100_000)
    with pytest.raises(ProtocolException):
        json_codec.loads(b'"123456789"', max_bytes=8)
    assert json_codec.loads(b'\xef\xbb\xbf{"a":"\\ud800"}') == {"a": "\ud800"}


def test_json_writer_round_trips_unpaired_surrogates_and_refuses_nan() -> None:
    value = {"s": "a\ud800b é 😀", "n": [1, 0.5, -0.0]}
    assert json_codec.loads(json_codec.dumps(value)) == value
    with pytest.raises(ValueError):
        json_codec.dumps({"x": float("nan")})


async def feed(data: bytes, chunk: int = 1) -> asyncio.StreamReader:
    reader = asyncio.StreamReader()
    for i in range(0, len(data), chunk):
        reader.feed_data(data[i : i + chunk])
    reader.feed_eof()
    return reader


async def test_frames_round_trip_with_partial_reads() -> None:
    reader = await feed(encode_frame(b"abc") + encode_frame(b"d"), chunk=1)
    assert await read_frame(reader) == b"abc"
    assert await read_frame(reader) == b"d"
    assert await read_frame(reader) is None


async def test_frame_limits() -> None:
    assert struct.unpack("<I", encode_frame(b"x" * 0x0102)[:4])[0] == 0x0102
    with pytest.raises(ProtocolException) as e:
        encode_frame(b"12345", max_frame_bytes=4)
    assert e.value.code == FRAME_TOO_LARGE
    with pytest.raises(ProtocolException) as e:
        await read_frame(await feed(encode_frame(b"12345")), max_frame_bytes=4)
    assert e.value.code == FRAME_TOO_LARGE
    with pytest.raises(ProtocolException):
        await read_frame(await feed(b"\x00\x00\x00\x00"))
    with pytest.raises(ProtocolException):
        await read_frame(await feed(b"\x03\x00\x00\x00a"))
    with pytest.raises(ProtocolException):
        encode_frame(b"")
    payload = bytes(range(256)) * (16 * 1024 * 1024 // 256)
    assert await read_frame(await feed(encode_frame(payload), chunk=1 << 20)) == payload


@pytest.mark.parametrize(
    "value",
    [
        [],
        {"id": "a", "kind": "request", "method": "ping"},
        {"v": "0", "id": "a", "kind": "request", "method": "ping"},
        {"v": 0, "id": "a", "kind": "notify", "method": "ping"},
        {"v": 0, "id": "", "kind": "request", "method": "ping"},
        {"v": 0, "id": "a", "kind": "request", "method": "ping", "params": []},
        {"v": 0, "id": "a", "kind": "response"},
        {"v": 0, "id": "a", "kind": "response", "result": 1, "error": {"code": "X", "message": "m"}},
        {"v": 0, "kind": "event", "method": "log", "params": {}},
    ],
)
def test_malformed_envelopes_are_invalid_frames(value: object) -> None:
    with pytest.raises(ProtocolException) as e:
        envelope.parse(value if isinstance(value, dict) else json_codec.dumps(value))
    assert e.value.code == INVALID_FRAME


def test_envelopes_round_trip_and_keep_unknown_fields() -> None:
    raw = {"v": 0, "id": "r-1", "kind": "request", "method": "ping", "params": {"echo": "x"}, "timeoutMs": 500, "context": {"task": "t"}, "later": True}
    parsed = envelope.parse(json_codec.dumps(raw))
    assert isinstance(parsed, envelope.Request)
    assert parsed.to_json() == raw
    null_result = envelope.parse({"v": 0, "id": "a", "kind": "response", "result": None})
    assert isinstance(null_result, envelope.Response) and not null_result.is_error and null_result.result is None
    assert envelope.parse({"v": 7, "id": "a", "kind": "request", "method": "hello"}).v == 7


@pytest.mark.parametrize(("major", "minor", "compatible"), [(0, 1, True), (0, 0, False), (0, 2, False), (1, 1, False)])
def test_pre_release_versions_must_match_exactly(major: int, minor: int, compatible: bool) -> None:
    assert PROTOCOL_MAJOR == 0
    assert is_compatible(major, minor) is compatible
