"""Test de non-regression : _convert_with_docling reconstruisait un
DocumentConverter (chargement des modeles de layout/table Docling) a chaque
document, au lieu de le mettre en cache comme les autres modeles ML du
projet (cross-encoder, embeddings). Avec plusieurs threads worker
(AI_REALTIME_WORKER_CONCURRENCY > 1), ca pouvait meme declencher plusieurs
chargements concurrents du meme modele.

docling n'est pas installe dans cet environnement de dev (dependance POC
optionnelle) : ce test injecte un faux module `docling` dans sys.modules
pour verifier uniquement la logique de cache (_get_converter), sans
dependre du package reel ni de vrais modeles.
"""
from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock

import pytest

from app.services import conversion


@pytest.fixture
def fake_docling(monkeypatch):
    constructed = []

    class _FakeDocumentConverter:
        def __init__(self, format_options=None):
            constructed.append(self)
            self.format_options = format_options

        def convert(self, path):
            result = MagicMock()
            result.document = MagicMock(tables=[])
            result.document.export_to_markdown.return_value = "# Doc\n\ntext"
            result.document.export_to_text.return_value = "text"
            return result

    document_converter_mod = types.ModuleType("docling.document_converter")
    document_converter_mod.DocumentConverter = _FakeDocumentConverter
    document_converter_mod.PdfFormatOption = lambda pipeline_options=None: pipeline_options

    base_models_mod = types.ModuleType("docling.datamodel.base_models")
    base_models_mod.InputFormat = types.SimpleNamespace(PDF="pdf")

    pipeline_options_mod = types.ModuleType("docling.datamodel.pipeline_options")
    pipeline_options_mod.PdfPipelineOptions = lambda **kwargs: kwargs

    settings_mod = types.ModuleType("docling.datamodel.settings")
    settings_mod.settings = types.SimpleNamespace(artifacts_path="/some/path")

    docling_mod = types.ModuleType("docling")
    datamodel_mod = types.ModuleType("docling.datamodel")

    modules = {
        "docling": docling_mod,
        "docling.document_converter": document_converter_mod,
        "docling.datamodel": datamodel_mod,
        "docling.datamodel.base_models": base_models_mod,
        "docling.datamodel.pipeline_options": pipeline_options_mod,
        "docling.datamodel.settings": settings_mod,
    }
    for name, mod in modules.items():
        monkeypatch.setitem(sys.modules, name, mod)

    # Reset the module-level singleton so each test starts cold.
    monkeypatch.setattr(conversion, "_converter", None)
    return constructed


def test_converter_is_built_once_and_reused(fake_docling):
    first = conversion._get_converter()
    second = conversion._get_converter()

    assert first is second
    assert len(fake_docling) == 1, "DocumentConverter must be constructed only once, not per call"


def test_convert_with_docling_reuses_cached_converter(fake_docling, tmp_path):
    fake_pdf = tmp_path / "cv.pdf"
    fake_pdf.write_bytes(b"%PDF-1.4 fake")

    conversion._convert_with_docling(fake_pdf)
    conversion._convert_with_docling(fake_pdf)

    assert len(fake_docling) == 1, "a second document must not trigger a second model load"
