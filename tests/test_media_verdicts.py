"""Media auditor verdicts beyond the happy paths (issue #32).

Header parsers for every supported image format, and the image and audio
verdicts for the less common responses: truncated or empty bodies, an ignored
format, audio that does not scale with its input, a failing second call.
Everything runs against in-process ``httpx.MockTransport`` handlers.
"""

from __future__ import annotations

import base64
import json
import struct

import httpx
import pytest

from ekte.clients import OpenAICompatibleClient
from ekte.media_audit import (
    _format_matches,
    _parse_size,
    audit_audio,
    audit_image,
    detect_audio,
    detect_image,
    wav_duration_seconds,
)
from tests.test_media import (
    SECRET,
    AudioMock,
    ImageMock,
    _aud_target,
    _finding,
    _img_target,
    make_png,
    make_wav,
)


def _jpeg(width: int, height: int) -> bytes:
    app0 = b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00" + b"\x00" * 9
    sof = b"\xff\xc0" + struct.pack(">HBHHB", 17, 8, height, width, 3) + b"\x00" * 9
    return b"\xff\xd8" + app0 + sof + b"\xff\xd9"


def _gif(width: int, height: int) -> bytes:
    return b"GIF89a" + struct.pack("<HH", width, height) + b"\x00" * 8


def _webp(kind: bytes, width: int, height: int) -> bytes:
    riff = b"RIFF" + b"\x00" * 4 + b"WEBP"
    if kind == b"VP8 ":
        # chunk header (8), frame tag (3), start code (3), 14-bit width/height
        return riff + b"VP8 " + b"\x00" * 4 + b"\x00" * 3 + b"\x9d\x01\x2a" + struct.pack("<HH", width, height) + b"\x00" * 4
    if kind == b"VP8L":
        w, h = width - 1, height - 1
        b0 = w & 0xFF
        b1 = ((w >> 8) & 0x3F) | ((h & 0x03) << 6)
        b2 = (h >> 2) & 0xFF
        b3 = (h >> 10) & 0x0F
        return riff + b"VP8L" + b"\x00" * 4 + b"\x2f" + bytes([b0, b1, b2, b3])
    w, h = width - 1, height - 1
    return riff + b"VP8X" + b"\x00" * 8 + w.to_bytes(3, "little") + h.to_bytes(3, "little")


# --------------------------------------------------------------------------- parsers
def test_detect_jpeg_gif_and_webp_dimensions():
    assert detect_image(_jpeg(640, 480)) == ("jpeg", 640, 480)
    assert detect_image(_gif(33, 22)) == ("gif", 33, 22)
    assert detect_image(_webp(b"VP8L", 300, 200)) == ("webp", 300, 200)
    assert detect_image(_webp(b"VP8X", 1280, 720)) == ("webp", 1280, 720)
    assert detect_image(_webp(b"VP8 ", 512, 256)) == ("webp", 512, 256)


def test_detect_image_handles_truncated_and_unknown_headers():
    assert detect_image(b"") == (None, None, None)
    assert detect_image(b"\x89PNG\r\n\x1a\n" + b"\x00" * 6) == ("png", None, None)
    assert detect_image(b"\xff\xd8" + b"\xff\xe0" + b"\x00\x02" + b"\x00" * 10) == ("jpeg", None, None)
    assert detect_image(b"\xff\xd8\xff\xe0\x00\x02\xff\xc0\x00\x11\x08\x00") == ("jpeg", None, None)
    assert detect_image(b"RIFF\x00\x00\x00\x00WEBPVP8Z" + b"\x00" * 20) == ("webp", None, None)
    assert detect_image(b"<html>" + b"x" * 20) == (None, None, None)
    # fill bytes and restart markers before the frame header
    padded = b"\xff\xd8" + b"\x00" + b"\xff\xd0" + _jpeg(8, 4)[2:]
    assert detect_image(padded) == ("jpeg", 8, 4)


def test_detect_audio_containers():
    assert detect_audio(b"OggS" + b"\x00" * 8) == "ogg"
    assert detect_audio(b"fLaC" + b"\x00" * 8) == "flac"
    assert detect_audio(b"ID3\x04" + b"\x00" * 8) == "mp3"
    assert detect_audio(b"\xff\xfb\x90\x00") == "mp3"
    assert detect_audio(make_wav(0.1)) == "wav"
    assert detect_audio(b"abc") is None
    assert detect_audio(b"<html>") is None


def test_wav_duration_rejects_garbage():
    assert wav_duration_seconds(b"not a wav") is None
    assert wav_duration_seconds(make_wav(0.5)) == pytest.approx(0.5, abs=0.01)


def test_parse_size_and_format_matching():
    assert _parse_size("1024x512") == (1024, 512)
    assert _parse_size("1024×512") == (1024, 512)
    assert _parse_size("big") is None
    assert _parse_size("axb") is None
    assert _format_matches("ogg", "opus") and _format_matches("ogg", "OGG")
    assert _format_matches("mp3", "mp3") and not _format_matches("wav", "mp3")
    assert not _format_matches(None, "wav")


# --------------------------------------------------------------------------- helpers
def _install(monkeypatch, handler):
    def _factory(target, *, transport=None):  # noqa: ARG001
        return OpenAICompatibleClient(target, transport=httpx.MockTransport(handler))

    monkeypatch.setattr("ekte.media_audit.make_client", _factory)


def _img_response(images: list[bytes], model: str = "dall-e-3") -> httpx.Response:
    data = [{"b64_json": base64.b64encode(i).decode()} for i in images]
    return httpx.Response(200, json={"model": model, "data": data})


# --------------------------------------------------------------------------- image
async def test_image_without_any_image_bytes_is_an_error(monkeypatch):
    _install(monkeypatch, lambda r: httpx.Response(200, json={"data": []}))
    v = await audit_image(_img_target(), size="1024x1024", claimed_sizes=[])
    assert _finding(v, "image.connectivity")["status"] == "error"


async def test_image_with_truncated_header_fails_format(monkeypatch):
    _install(monkeypatch, lambda r: _img_response([b"\x89PNG\r\n\x1a\n" + b"\x00" * 8]))
    v = await audit_image(_img_target(), size="1024x1024", claimed_sizes=[])
    assert _finding(v, "image.format")["status"] == "fail"


async def test_image_with_unparseable_requested_size_is_informational(monkeypatch):
    _install(monkeypatch, lambda r: _img_response([make_png(8, 8)]))
    v = await audit_image(_img_target(), size="huge", claimed_sizes=[])
    assert _finding(v, "image.size_match")["status"] == "info"


async def test_image_multiple_images_for_n1_warns_on_count(monkeypatch):
    _install(monkeypatch, lambda r: _img_response([make_png(8, 8), make_png(8, 8, (1, 2, 3))]))
    v = await audit_image(_img_target(), size="8x8", claimed_sizes=["8x8"])
    assert _finding(v, "image.count")["status"] == "warn"
    assert _finding(v, "image.size_match")["status"] == "pass"


async def test_image_second_call_failing_leaves_distinctness_inconclusive(monkeypatch):
    calls = []

    def handler(request):
        calls.append(1)
        if len(calls) == 1:
            return _img_response([make_png(8, 8)])
        return httpx.Response(500, json={"error": {"message": "boom"}})

    _install(monkeypatch, handler)
    v = await audit_image(_img_target(), size="8x8", claimed_sizes=[])
    assert _finding(v, "image.distinctness")["status"] == "info"
    assert _finding(v, "image.connectivity")["status"] == "pass"


async def test_image_url_only_response_is_fetched(monkeypatch):
    png = make_png(8, 8)

    def handler(request):
        if request.url.path.endswith("/images/generations"):
            return httpx.Response(200, json={"data": [{"url": "https://img.test/a.png"}]})
        return httpx.Response(200, content=png)

    _install(monkeypatch, handler)
    v = await audit_image(_img_target(), size="8x8", claimed_sizes=[])
    assert _finding(v, "image.format")["status"] == "pass"


# --------------------------------------------------------------------------- audio
def _audio_handler(first: bytes, second: bytes | None = None, *, second_status: int = 200):
    calls = []

    def handler(request):
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(200, content=first)
        if second_status >= 400:
            return httpx.Response(second_status, json={"error": {"message": "boom"}})
        return httpx.Response(200, content=second if second is not None else first)

    return handler


async def test_audio_mp3_length_scaling_pass_and_fail(monkeypatch):
    short, long_ = b"ID3\x04" + b"a" * 100, b"ID3\x04" + b"b" * 500
    _install(monkeypatch, _audio_handler(short, long_))
    v = await audit_audio(_aud_target(), voice="alloy", fmt="mp3")
    assert _finding(v, "audio.nontrivial")["status"] == "pass"
    assert _finding(v, "audio.format_honored")["status"] == "pass"

    _install(monkeypatch, _audio_handler(long_, short))
    v = await audit_audio(_aud_target(), voice="alloy", fmt="mp3")
    assert _finding(v, "audio.nontrivial")["status"] == "warn"


async def test_audio_requested_format_ignored_warns(monkeypatch):
    _install(monkeypatch, _audio_handler(make_wav(0.3), make_wav(0.9)))
    v = await audit_audio(_aud_target(), voice="alloy", fmt="mp3")
    assert _finding(v, "audio.format_honored")["status"] == "warn"


async def test_audio_second_call_failing_is_inconclusive(monkeypatch):
    _install(monkeypatch, _audio_handler(make_wav(0.3), second_status=500))
    v = await audit_audio(_aud_target(), voice="alloy", fmt="wav")
    assert _finding(v, "audio.nontrivial")["status"] == "pass"
    assert _finding(v, "audio.distinctness")["status"] == "info"

    _install(monkeypatch, _audio_handler(b"ID3\x04" + b"a" * 50, second_status=500))
    v = await audit_audio(_aud_target(), voice="alloy", fmt="mp3")
    assert _finding(v, "audio.nontrivial")["status"] == "pass"


async def test_audio_wav_with_no_frames_fails(monkeypatch):
    _install(monkeypatch, _audio_handler(make_wav(0.0)))
    v = await audit_audio(_aud_target(), voice="alloy", fmt="wav")
    assert _finding(v, "audio.nontrivial")["status"] == "fail"


async def test_audio_wav_not_longer_for_longer_input_warns(monkeypatch):
    _install(monkeypatch, _audio_handler(make_wav(0.5), make_wav(0.5, freq=300)))
    v = await audit_audio(_aud_target(), voice="alloy", fmt="wav")
    assert _finding(v, "audio.nontrivial")["status"] == "warn"
    assert _finding(v, "audio.distinctness")["status"] == "pass"


async def test_verdicts_never_contain_the_api_key(monkeypatch):
    mock = ImageMock(status=500)
    monkeypatch.setattr(
        "ekte.media_audit.make_client",
        lambda target, *, transport=None: OpenAICompatibleClient(target, transport=mock.transport),
    )
    v = await audit_image(_img_target(), size="8x8", claimed_sizes=[])
    assert SECRET not in json.dumps(v)
    amock = AudioMock(status=500)
    monkeypatch.setattr(
        "ekte.media_audit.make_client",
        lambda target, *, transport=None: OpenAICompatibleClient(target, transport=amock.transport),
    )
    v = await audit_audio(_aud_target(), voice="alloy", fmt="wav")
    assert SECRET not in json.dumps(v)
