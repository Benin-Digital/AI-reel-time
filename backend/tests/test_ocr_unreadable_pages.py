"""OCR sur les pages dont le texte est illisible ou incomplet.

L'OCR ne se declenchait que sur les pages de moins de `ocr_min_text_length`
caracteres. Deux cas passaient donc sans OCR, constates le 2026-10-12 sur la
plateforme soeur (Keoni), sur des CV qui n'avaient aucune competence detectee et
remontaient en tete de chaque classement :

- texte PRESENT mais illisible : police PDF sans table Unicode, qui sort des
  caracteres decales ("DWDDQDO\\VW", "3\\WKRQ64/" pour "Data Analyst", "Python SQL") ;
- texte INCOMPLET : corps du CV rendu en image, seul l'etat civil en couche texte.

Les chaines ci-dessous ne contiennent aucune donnee personnelle.
"""
from __future__ import annotations

import fitz

from app.services.extraction import _image_coverage, looks_unreadable, page_ocr_reason

GARBLED_FONT_TEXT = (
    r"3\WKRQ64/DLQVLTX HQ JHVWLRQGHEDVHVGHGRQQ«HVJ«RJUDSKLTXHVFRPSOH[HVDYHF3RVW*,6RQH[S«ULHQFHPDSHUPLVG "
    r"RSWLPLVHU O H[SORLWDWLRQGHVGRQQ«HVSRXUGHVSURMHWVDQDO\WLTXHVHQJDUDQWLVVDQWODTXDOLW«HWODILDELOLW«GHVLQIRUPDWLRQV"
)

NORMAL_FRENCH_TEXT = (
    "Ingénieur DevOps avec huit ans d'expérience dans la mise en place de pipelines CI/CD et "
    "l'automatisation des déploiements sur des environnements cloud. Responsable de la sécurité des "
    "applications et de la formation des équipes de développement."
)

SKILLS_LIST_TEXT = (
    "Python, SQL, Docker, Kubernetes, Terraform, Ansible, Jenkins, GitLab CI, Prometheus, Grafana, Linux, "
    "Bash, Java, Spring Boot, PostgreSQL, Oracle, MongoDB, Redis, Kafka, RabbitMQ, OpenShift, Azure, AWS, "
    "GCP, SonarQube, Nexus"
)

CIVIL_STATUS_TEXT = (
    "Prénom Nom Né le 19/08/1994 Marocain, Célibataire 28 Rue Jbel Aouam Casablanca Maroc Permis B "
    "Disponible immédiatement Mobilité nationale et internationale Langues Arabe Français Anglais"
)


def test_garbled_font_text_is_detected_as_unreadable():
    assert looks_unreadable(GARBLED_FONT_TEXT) is True


def test_readable_texts_are_not_flagged_as_unreadable():
    assert looks_unreadable(NORMAL_FRENCH_TEXT) is False
    # A page made of a plain tool list is not noise.
    assert looks_unreadable(SKILLS_LIST_TEXT) is False
    assert looks_unreadable(CIVIL_STATUS_TEXT) is False


def test_short_text_is_never_called_unreadable():
    assert looks_unreadable("Python SQL") is False
    assert looks_unreadable("") is False


def test_page_ocr_reason_covers_the_three_cases():
    assert page_ocr_reason("", 0.0) == "empty"
    assert page_ocr_reason("quelques mots", 0.0) == "empty"
    assert page_ocr_reason(GARBLED_FONT_TEXT, 0.0) == "unreadable"
    # Little text on a page almost entirely covered by an image.
    assert page_ocr_reason(CIVIL_STATUS_TEXT, 0.8) == "sparse"


def test_page_ocr_reason_leaves_a_normal_text_page_alone():
    assert page_ocr_reason(NORMAL_FRENCH_TEXT, 0.0) is None
    # A small ID photo on a well-filled page triggers nothing.
    assert page_ocr_reason(NORMAL_FRENCH_TEXT * 12, 0.1) is None
    # A large image but plenty of text: the text is enough.
    assert page_ocr_reason(NORMAL_FRENCH_TEXT * 12, 0.8) is None


def test_image_coverage_measures_how_much_of_the_page_is_an_image():
    text_only = fitz.open()
    page = text_only.new_page(width=600, height=800)
    page.insert_text((50, 100), "Texte seul")
    assert _image_coverage(page) == 0.0

    with_image = fitz.open()
    page = with_image.new_page(width=600, height=800)
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 100, 100), False)
    pix.set_rect(pix.irect, (200, 200, 200))
    page.insert_image(fitz.Rect(0, 0, 600, 800), pixmap=pix)
    assert _image_coverage(page) >= 0.9
