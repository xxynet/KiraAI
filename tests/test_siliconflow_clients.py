"""Regression tests for Siliconflow response parsing and audio uploads."""

import base64

import httpx
import pytest

from core.chat.message_elements import Record
from core.provider import ModelInfo, ModelType
from core.provider.src.siliconflow_cn import model_clients as siliconflow_clients
from core.provider.src.siliconflow_cn.model_clients import (
    SiliconflowImageClient,
    SiliconflowRerankClient,
    resolve_audio_filename,
)


def build_model_info(model_type: ModelType, model_id: str) -> ModelInfo:
    return ModelInfo(
        model_type=model_type,
        model_id=model_id,
        provider_id="siliconflow-test",
        provider_name="Siliconflow Test",
        provider_config={"api_key": "test-key"},
        model_config={},
    )


def patch_transport(monkeypatch, handler):
    real_async_client = httpx.AsyncClient
    monkeypatch.setattr(
        siliconflow_clients.httpx,
        "AsyncClient",
        lambda *args, **kwargs: real_async_client(
            transport=httpx.MockTransport(handler)
        ),
    )


@pytest.mark.anyio
async def test_image_generation_surfaces_missing_image_field(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"message": "model is overloaded"})

    patch_transport(monkeypatch, handler)
    client = SiliconflowImageClient(build_model_info(ModelType.IMAGE, "kolors"))

    with pytest.raises(ValueError, match="model is overloaded"):
        await client.text_to_image("a cat")


@pytest.mark.anyio
async def test_rerank_skips_out_of_range_indexes(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "results": [
                    {"index": 1, "relevance_score": 0.9},
                    {"index": 7, "relevance_score": 0.8},
                    {"relevance_score": 0.7},
                    "not-a-dict",
                ]
            },
        )

    patch_transport(monkeypatch, handler)
    client = SiliconflowRerankClient(build_model_info(ModelType.RERANK, "bge-reranker"))

    results = await client.rerank("query", ["first", "second"])

    assert [(item.index, item.text) for item in results] == [(1, "second")]


@pytest.mark.parametrize(
    "payload,expected",
    [
        (b"#!AMR\n" + b"\x00" * 16, "audio.amr"),
        (b"\x02#!SILK_V3" + b"\x00" * 16, "audio.silk"),
        (b"OggS" + b"\x00" * 16, "audio.ogg"),
        (b"ID3\x03\x00\x00\x00\x00\x00\x00", "audio.mp3"),
        (b"RIFF\x00\x00\x00\x00WAVE", "audio.wav"),
    ],
)
def test_audio_filename_is_derived_from_the_payload(payload, expected):
    record = Record(record=base64.b64encode(payload).decode())

    assert resolve_audio_filename(record, payload) == expected


def test_audio_filename_falls_back_to_mime_then_wav():
    unknown = b"\x00" * 32

    assert resolve_audio_filename(Record(record="aGVsbG8=", mime="audio/amr"), unknown) == (
        "audio.amr"
    )
    assert resolve_audio_filename(Record(record="aGVsbG8="), unknown) == "audio.wav"
