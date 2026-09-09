"""Tests de non-regression pour le fallback OCR (extraction.py).

Deux generations de bugs couvertes ici :

1. (deja corrige, PR precedent) L'OCR tournait sans plafond de pages ni
   timeout, dans le thread unique du worker d'ingestion. Un document
   scanne de plusieurs pages pouvait monopoliser le CPU pendant plusieurs
   minutes, provoquant des 502 nginx (repro reelle : un CV de 11 pages).

2. Le seuil de declenchement de l'OCR etait verifie sur le texte COMBINE
   de tout le document, pas page par page. Un CV de plusieurs pages dont
   une seule page est un diplome/certificat scanne (le reste du document
   ayant largement assez de texte reel pour depasser le seuil) ne
   declenchait jamais l'OCR pour cette page precise -> son contenu
   disparaissait silencieusement, sans erreur, sans page manquante visible.

_ocr_pdf_pages() OCRise maintenant des pages precises (une a la fois,
via first_page/last_page) au lieu de convertir tout le document d'un
coup ; extract_text_from_pdf() decide quelles pages sont "faibles"
(sous le seuil) une par une et ne demande l'OCR que pour celles-la.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from app.services import extraction


@pytest.fixture(autouse=True)
def _restore_settings():
    original_max_pages = extraction.settings.ocr_max_pages
    original_timeout = extraction.settings.ocr_page_timeout_seconds
    original_min_len = extraction.settings.ocr_min_text_length
    yield
    extraction.settings.ocr_max_pages = original_max_pages
    extraction.settings.ocr_page_timeout_seconds = original_timeout
    extraction.settings.ocr_min_text_length = original_min_len


class _FakePage:
    """Mimics fitz.Page.get_text('dict') just enough for extract_text_from_pdf's
    per-page threshold logic: one block with one line whose text round-trips
    back to the original string (these tests aren't about column ordering --
    see test_pdf_column_extraction.py for that)."""

    def __init__(self, text: str):
        self._text = text

    def get_text(self, mode):
        blocks = []
        if self._text:
            blocks = [{
                "type": 0,
                "bbox": (0, 0, 100, 20),
                "lines": [{"bbox": (0, 0, 100, 20), "spans": [{"text": self._text}]}],
            }]
        return {"width": 200, "height": 800, "blocks": blocks}


class _FakeDoc:
    def __init__(self, texts: list[str]):
        self._pages = [_FakePage(t) for t in texts]

    def __iter__(self):
        return iter(self._pages)

    def close(self):
        pass


# --- _ocr_pdf_pages: OCR of specific pages -----------------------------------

def test_ocr_pdf_pages_renders_only_requested_pages():
    with patch.object(extraction, "convert_from_path", return_value=["img"]) as mock_convert, \
         patch.object(extraction.pytesseract, "image_to_string", return_value="texte") as mock_ocr:
        result = extraction._ocr_pdf_pages(extraction.Path("/fake/cv.pdf"), [2, 5])

    assert mock_convert.call_count == 2, "un rendu par page demandee, pas un rendu du document entier"
    calls = mock_convert.call_args_list
    assert calls[0].kwargs["first_page"] == 3 and calls[0].kwargs["last_page"] == 3
    assert calls[1].kwargs["first_page"] == 6 and calls[1].kwargs["last_page"] == 6
    assert result == {2: "texte", 5: "texte"}
    assert mock_ocr.call_count == 2


def test_ocr_pdf_pages_skips_page_that_times_out():
    def _convert_side_effect(path, dpi, first_page, last_page):
        return [f"img-page-{first_page}"]

    def _ocr_side_effect(img, **kwargs):
        if img == "img-page-2":
            raise RuntimeError("Tesseract process timeout")
        return f"texte-{img}"

    with patch.object(extraction, "convert_from_path", side_effect=_convert_side_effect), \
         patch.object(extraction.pytesseract, "image_to_string", side_effect=_ocr_side_effect):
        result = extraction._ocr_pdf_pages(extraction.Path("/fake/cv.pdf"), [0, 1, 2])

    assert 1 not in result, "la page en timeout doit etre ignoree, pas planter tout le document"
    assert result[0] == "texte-img-page-1"
    assert result[2] == "texte-img-page-3"


def test_ocr_pdf_pages_passes_configured_timeout():
    extraction.settings.ocr_page_timeout_seconds = 7
    with patch.object(extraction, "convert_from_path", return_value=["img"]), \
         patch.object(extraction.pytesseract, "image_to_string", return_value="ok") as mock_ocr:
        extraction._ocr_pdf_pages(extraction.Path("/fake/cv.pdf"), [0])

    _, kwargs = mock_ocr.call_args
    assert kwargs.get("timeout") == 7


# --- extract_text_from_pdf: per-page threshold + cap orchestration ----------

def test_only_weak_pages_are_sent_to_ocr(monkeypatch):
    extraction.settings.ocr_min_text_length = 20
    # page 0: plenty of real text ; page 1: a scanned page with no text layer
    texts = ["A" * 50, ""]
    monkeypatch.setattr(extraction.fitz, "open", lambda p: _FakeDoc(texts))

    with patch.object(extraction, "_ocr_pdf_pages", return_value={1: "texte OCR de la page scannee"}) as mock_ocr_pages:
        result = extraction.extract_text_from_pdf(extraction.Path("/fake/cv.pdf"))

    mock_ocr_pages.assert_called_once_with(extraction.Path("/fake/cv.pdf"), [1])
    assert "texte OCR de la page scannee" in result
    assert "A" * 50 in result


def test_document_wide_text_does_not_mask_a_scanned_page(monkeypatch):
    """Repro : un CV de 2 pages ou la page 1 a largement assez de texte pour
    depasser le seuil a elle seule ne doit pas empecher l'OCR de la page 2
    (un certificat scanne) simplement parce que le total combine est eleve."""
    extraction.settings.ocr_min_text_length = 20
    texts = ["Jean Dupont - Developpeur Python - 5 ans d'experience", ""]
    monkeypatch.setattr(extraction.fitz, "open", lambda p: _FakeDoc(texts))

    with patch.object(extraction, "_ocr_pdf_pages", return_value={1: "Diplome Master Informatique 2018"}) as mock_ocr_pages:
        result = extraction.extract_text_from_pdf(extraction.Path("/fake/cv.pdf"))

    assert mock_ocr_pages.called, "la page 2, individuellement sous le seuil, doit declencher l'OCR malgre le total du document"
    assert "Diplome Master Informatique 2018" in result


def test_weak_pages_beyond_cap_are_not_ocred(monkeypatch):
    extraction.settings.ocr_min_text_length = 20
    extraction.settings.ocr_max_pages = 3
    texts = [""] * 11  # repro : CV/document de 11 pages, toutes faibles
    monkeypatch.setattr(extraction.fitz, "open", lambda p: _FakeDoc(texts))

    with patch.object(extraction, "_ocr_pdf_pages", return_value={}) as mock_ocr_pages:
        extraction.extract_text_from_pdf(extraction.Path("/fake/cv-11-pages.pdf"))

    called_pages = mock_ocr_pages.call_args[0][1]
    assert len(called_pages) == 3, "seules les 3 premieres pages faibles doivent etre envoyees a l'OCR"


def test_ocr_text_only_replaces_page_text_when_longer(monkeypatch):
    extraction.settings.ocr_min_text_length = 20
    texts = ["short"]  # below threshold, but OCR might return something even shorter/empty
    monkeypatch.setattr(extraction.fitz, "open", lambda p: _FakeDoc(texts))

    with patch.object(extraction, "_ocr_pdf_pages", return_value={0: ""}):
        result = extraction.extract_text_from_pdf(extraction.Path("/fake/cv.pdf"))

    assert "short" in result, "si l'OCR ne produit rien de mieux, le texte original doit etre garde"
