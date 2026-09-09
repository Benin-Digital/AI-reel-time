"""Tests de non-regression pour l'ordonnancement des blocs PDF a colonnes
asymetriques (extraction.py::_order_blocks_by_column).

Contexte : PyMuPDF's get_text(sort=True) ordonne les spans par (y, x), ce
qui reconstruit correctement un texte mono-colonne ou des colonnes de
hauteur egale, mais casse le gabarit de CV tres courant "sidebar courte
(nom/contact/competences) + corps principal beaucoup plus long" — une
ligne de la sidebar et une ligne du corps principal au meme y se
retrouvent emises l'une apres l'autre, entrelacant deux sections sans
rapport en plein milieu d'une phrase. Un cas reel de ce bug est deja
documente dans test_name_section_title.py : un verbe d'action du corps
principal, entrelace avec la sidebar, etait pris pour le nom du candidat.

_order_blocks_by_column() detecte une vraie mise en page a deux colonnes
via la part de caracteres de chaque cote de la ligne mediane de page (pas
un simple comptage de blocs : une colonne principale peut n'etre qu'un
seul gros bloc de texte) et ne reordonne QUE dans ce cas — sinon elle
retombe sur l'ordre (y, x) d'origine, pour ne jamais degrader un CV
mono-colonne (ex: une date alignee a droite sur la meme ligne qu'un
intitule de poste ne doit pas etre prise pour une deuxieme colonne).
"""
from __future__ import annotations

import fitz

from app.services.extraction import extract_text_from_pdf

PAGE_WIDTH = 595
PAGE_HEIGHT = 842


def _make_pdf(path, inserts: list[tuple[tuple[float, float], str]]) -> None:
    doc = fitz.open()
    page = doc.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
    for point, text in inserts:
        page.insert_text(point, text)
    doc.save(path)
    doc.close()


def test_sidebar_lines_stay_grouped_instead_of_interleaved(tmp_path):
    """Sidebar courte (nom, telephone, competences) a gauche, corps
    principal long a droite qui commence a peu pres au meme y que la
    2e ligne de la sidebar -- le cas exact qui cassait avant ce fix."""
    path = tmp_path / "sidebar_cv.pdf"
    _make_pdf(path, [
        ((40, 60), "Jean DUPONT"),
        ((40, 90), "06 12 34 56 78"),
        ((40, 120), "Python"),
        ((40, 150), "Docker"),
        ((300, 90), "Developpement Deploiement des flux ETL chez ACME"),
    ])

    result = extract_text_from_pdf(path)
    lines = result.splitlines()

    sidebar = ["Jean DUPONT", "06 12 34 56 78", "Python", "Docker"]
    sidebar_positions = [lines.index(l) for l in sidebar]
    body_position = next(i for i, l in enumerate(lines) if l.startswith("Developpement"))

    assert sidebar_positions == sorted(sidebar_positions), "la sidebar doit rester dans son ordre de haut en bas"
    assert max(sidebar_positions) < body_position, (
        f"le corps principal ne doit apparaitre qu'apres toute la sidebar, "
        f"obtenu sidebar={sidebar_positions} body={body_position} dans {lines!r}"
    )


def test_single_column_with_right_aligned_date_is_not_split_into_columns(tmp_path):
    """Une date alignee a droite sur un CV mono-colonne (tres courant :
    intitule de poste a gauche, dates a droite sur la meme ligne) ne doit
    jamais etre prise pour une deuxieme colonne -- ca ne represente qu'une
    infime part du texte de la page."""
    path = tmp_path / "single_column_cv.pdf"
    _make_pdf(path, [
        ((72, 60), "Jean Dupont"),
        ((72, 90), "Experience professionnelle chez ACME de 2019 a 2023, poste de "
                   "developpeur backend Python avec de nombreuses responsabilites"),
        ((500, 90), "2019-2023"),
        ((72, 130), "Formation Master informatique 2018"),
    ])

    result = extract_text_from_pdf(path)
    lines = result.splitlines()

    assert lines.index("Jean Dupont") < next(i for i, l in enumerate(lines) if l.startswith("Experience"))
    assert next(i for i, l in enumerate(lines) if l.startswith("Experience")) < lines.index("2019-2023")
    assert lines.index("2019-2023") < lines.index("Formation Master informatique 2018")


def test_empty_page_returns_empty_string(tmp_path):
    path = tmp_path / "empty.pdf"
    doc = fitz.open()
    doc.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
    doc.save(path)
    doc.close()

    assert extract_text_from_pdf(path) == ""
