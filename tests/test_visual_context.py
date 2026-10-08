#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Тесты визуального контекста ответа и выдачи изображений (ТЗ §14, §16.2)."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from core.kb_catalog import KnowledgeCatalog
from core.visual_assets import VisualAssetStore
from core.visual_context import VisualContextResolver, resolve_visual_evidence
from core.visual_serving import KnowledgeImageService


def _png_bytes(width: int = 64, height: int = 64) -> bytes:
    pytest.importorskip("PIL")
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (width, height), "white").save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture
def store(tmp_path: Path) -> VisualAssetStore:
    catalog = KnowledgeCatalog(tmp_path / "catalog.sqlite")
    return VisualAssetStore(tmp_path / "assets", catalog=catalog)


def _chunk_with_occurrence(occ_id: str, title: str = "Процесс") -> dict:
    return {
        "chunk_id": "vc1",
        "score": 0.9,
        "metadata": {
            "chunk_kind": "visual",
            "title": title,
            "path": "manuals/process.docx",
            "source_revision": "rev1",
            "occurrence_ids_json": json.dumps([occ_id]),
        },
    }


def test_resolve_visual_evidence_builds_data_url(store: VisualAssetStore) -> None:
    aid = store.store_original(_png_bytes(), mime_type="image/png")
    store.catalog.upsert_source(source_id="src:doc", title="Процесс", source_type="docx",
                                source_path="manuals/process.docx", revision="rev1")
    store.catalog.upsert_occurrence(
        occurrence_id="occ:1", source_id="src:doc", asset_id=aid,
        locator={"page": 3}, caption="Схема", visual_type="flowchart",
        section_path="Процесс → Приёмка",
    )
    bundle = VisualContextResolver(assets=store).resolve([_chunk_with_occurrence("occ:1")])
    assert len(bundle.evidence) == 1
    assert len(bundle.image_data_urls) == 1
    assert bundle.image_data_urls[0].startswith("data:image/png;base64,")
    ev = bundle.evidence[0]
    assert ev.evidence_label == "Визуальный источник V1"
    assert ev.page == 3
    assert ev.used_for_answer is True
    assert "V1" in bundle.labels_text()


def test_resolve_respects_max_parts(store: VisualAssetStore) -> None:
    for i in range(5):
        aid = store.store_original(_png_bytes(32 + i, 32), mime_type="image/png")
        store.catalog.upsert_source(source_id=f"src:{i}", title=f"S{i}", source_type="docx",
                                    source_path=f"f{i}.docx", revision="r")
        store.catalog.upsert_occurrence(occurrence_id=f"occ:{i}", source_id=f"src:{i}",
                                        asset_id=aid, locator={}, section_path="s")
    docs = [_chunk_with_occurrence(f"occ:{i}") for i in range(5)]
    bundle = VisualContextResolver(assets=store).resolve(docs, max_parts=2, max_groups=10)
    assert len(bundle.evidence) == 2
    assert bundle.diagnostics["skipped_budget"] >= 0


def test_resolve_skips_non_visual_chunks(store: VisualAssetStore) -> None:
    text_chunk = {"chunk_id": "t1", "metadata": {"chunk_kind": "text"}}
    bundle = VisualContextResolver(assets=store).resolve([text_chunk])
    assert bundle.evidence == []
    assert bundle.diagnostics["visual_context"] == "none"


def test_visual_evidence_dict_shape(store: VisualAssetStore) -> None:
    aid = store.store_original(_png_bytes(), mime_type="image/png")
    store.catalog.upsert_source(source_id="src:doc", title="Процесс", source_type="docx",
                                source_path="p.docx", revision="rev1")
    store.catalog.upsert_occurrence(occurrence_id="occ:9", source_id="src:doc", asset_id=aid,
                                    locator={}, caption="cap", section_path="sec")
    ev = VisualContextResolver(assets=store).resolve(
        [_chunk_with_occurrence("occ:9")]
    ).evidence[0].to_dict()
    for key in ("asset_id", "occurrence_id", "url", "thumbnail_url", "visual_type",
                "used_for_answer", "evidence_label", "extraction_status"):
        assert key in ev
    assert ev["page"] is None  # не выдумываем номер


# --- Выдача изображений -------------------------------------------------------

def test_image_service_not_found(store: VisualAssetStore) -> None:
    service = KnowledgeImageService(assets=store)
    resp = service.resolve("occ:missing")
    assert resp.error_code == "not_found"


def test_image_service_serves_png(store: VisualAssetStore) -> None:
    aid = store.store_original(_png_bytes(), mime_type="image/png")
    store.catalog.upsert_source(source_id="src:doc", title="t", source_type="docx",
                                source_path="p.docx", revision="r")
    store.catalog.upsert_occurrence(occurrence_id="occ:1", source_id="src:doc", asset_id=aid,
                                    locator={}, section_path="s")
    service = KnowledgeImageService(assets=store)
    resp = service.resolve("occ:1")
    assert resp.error_code is None
    assert resp.mime_type == "image/png"
    assert resp.data


def test_image_service_thumbnail_variant(store: VisualAssetStore) -> None:
    aid = store.store_original(_png_bytes(1000, 800), mime_type="image/png")
    store.catalog.upsert_source(source_id="src:doc", title="t", source_type="docx",
                                source_path="p.docx", revision="r")
    store.catalog.upsert_occurrence(occurrence_id="occ:1", source_id="src:doc", asset_id=aid,
                                    locator={}, section_path="s")
    service = KnowledgeImageService(assets=store)
    resp = service.resolve("occ:1", variant="thumbnail")
    assert resp.error_code is None
    assert len(resp.data) < 1000 * 800  # уменьшено


def test_image_service_svg_download_only(store: VisualAssetStore) -> None:
    svg = b'<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"><rect/></svg>'
    aid = store.store_original(svg, mime_type="image/svg+xml")
    store.catalog.upsert_source(source_id="src:doc", title="t", source_type="html",
                                source_path="p.html", revision="r")
    store.catalog.upsert_occurrence(occurrence_id="occ:svg", source_id="src:doc", asset_id=aid,
                                    locator={}, section_path="s")
    service = KnowledgeImageService(assets=store)
    resp = service.resolve("occ:svg", variant="original")
    # Без растеризатора SVG отдаётся только на скачивание, не inline.
    assert resp.error_code is None
    assert resp.download_only is True or resp.mime_type == "image/png"


def test_rag_result_includes_images_field() -> None:
    from core.rag import RAGResult

    result = RAGResult(answer="a", citations=[], sources=[])
    assert result.to_dict()["images"] == []
    result.images = [{"occurrence_id": "occ:1"}]
    assert result.to_dict()["images"][0]["occurrence_id"] == "occ:1"


# --- Мягкий откат, когда модель не принимает изображения (ТЗ §15.1) -----------

def test_generate_answer_falls_back_when_vision_unsupported(monkeypatch) -> None:
    import core.rag as rag
    from core.rag import RAGSystem
    from utils.embeddings import ChatCompletionError

    monkeypatch.setattr(rag.settings, "CHAT_API_MODE", "openai", raising=False)
    calls = {"multimodal": 0, "text": 0}

    def fake_multimodal(messages, timeout=120):
        calls["multimodal"] += 1
        raise ChatCompletionError("no vision", code="vision_unsupported")

    def fake_text(prompt, timeout=120):
        calls["text"] += 1
        return "текстовый ответ"

    monkeypatch.setattr(rag, "chat_completion_messages", fake_multimodal)
    monkeypatch.setattr(rag, "chat_completion", fake_text)

    system = RAGSystem.__new__(RAGSystem)
    system._vision_fallback_reason = None
    answer = RAGSystem._generate_answer(
        system, "промпт", attachments=None,
        visual_image_urls=["data:image/png;base64,AAAA"], visual_labels="V1",
    )
    assert answer == "текстовый ответ"
    assert system._vision_fallback_reason == "vision_unsupported"
    assert calls == {"multimodal": 1, "text": 1}


def test_generate_answer_does_not_swallow_other_errors(monkeypatch) -> None:
    import core.rag as rag
    from core.rag import RAGSystem
    from utils.embeddings import ChatCompletionError

    monkeypatch.setattr(rag.settings, "CHAT_API_MODE", "openai", raising=False)

    def fake_multimodal(messages, timeout=120):
        raise ChatCompletionError("boom", code="generation_error")

    def fake_text(prompt, timeout=120):
        raise AssertionError("не должно дойти до текстового пути")

    monkeypatch.setattr(rag, "chat_completion_messages", fake_multimodal)
    monkeypatch.setattr(rag, "chat_completion", fake_text)

    system = RAGSystem.__new__(RAGSystem)
    system._vision_fallback_reason = None
    with pytest.raises(ChatCompletionError):
        RAGSystem._generate_answer(
            system, "промпт", attachments=None,
            visual_image_urls=["data:image/png;base64,AAAA"],
        )
