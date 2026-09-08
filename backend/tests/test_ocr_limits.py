"""Test de non-regression : l'OCR (fallback Tesseract pour les PDF scannes)
tournait sans plafond de pages ni timeout, dans le thread unique du worker
d'ingestion. Un document scanne de plusieurs pages pouvait ainsi monopoliser
le CPU pendant plusieurs minutes, provoquant des 502 nginx sur le reste de
la plateforme (repro reelle : un CV de 11 pages).

Ces tests verifient que _ocr_pdf :
- ne traite jamais plus de `ocr_max_pages` pages ;
- ignore une page dont l'OCR depasse `ocr_page_timeout_seconds` (RuntimeError
  levee par pytesseract) au lieu d'abandonner tout le document.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from app.services import extraction


@pytest.fixture(autouse=True)
def _restore_settings():
    original_max_pages = extraction.settings.ocr_max_pages
    original_timeout = extraction.settings.ocr_page_timeout_seconds
    yield
    extraction.settings.ocr_max_pages = original_max_pages
    extraction.settings.ocr_page_timeout_seconds = original_timeout


def test_ocr_caps_number_of_pages():
    extraction.settings.ocr_max_pages = 3
    fake_images = ["page"] * 11  # repro : CV de 11 pages

    with patch.object(extraction, "convert_from_path", return_value=fake_images) as mock_convert, \
         patch.object(extraction.pytesseract, "image_to_string", return_value="texte") as mock_ocr:
        result = extraction._ocr_pdf(extraction.Path("/fake/cv-11-pages.pdf"))

    assert mock_convert.called
    assert mock_ocr.call_count == 3, "seules les 3 premieres pages doivent etre passees a Tesseract"
    assert result.count("texte") == 3


def test_ocr_skips_page_that_times_out():
    extraction.settings.ocr_max_pages = 20
    fake_images = ["page1", "page2", "page3"]

    def _side_effect(img, **kwargs):
        if img == "page2":
            raise RuntimeError("Tesseract process timeout")
        return f"texte-{img}"

    with patch.object(extraction, "convert_from_path", return_value=fake_images), \
         patch.object(extraction.pytesseract, "image_to_string", side_effect=_side_effect) as mock_ocr:
        result = extraction._ocr_pdf(extraction.Path("/fake/cv.pdf"))

    assert mock_ocr.call_count == 3, "les 3 pages doivent etre tentees"
    assert "texte-page1" in result
    assert "texte-page3" in result
    assert "page2" not in result, "la page en timeout doit etre ignoree, pas planter tout le document"


def test_ocr_page_timeout_is_passed_to_tesseract():
    extraction.settings.ocr_page_timeout_seconds = 7
    fake_images = ["page1"]

    with patch.object(extraction, "convert_from_path", return_value=fake_images), \
         patch.object(extraction.pytesseract, "image_to_string", return_value="ok") as mock_ocr:
        extraction._ocr_pdf(extraction.Path("/fake/cv.pdf"))

    _, kwargs = mock_ocr.call_args
    assert kwargs.get("timeout") == 7
