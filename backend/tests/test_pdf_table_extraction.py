"""Tests de non-regression pour la detection de tableaux PDF via PyMuPDF
(extraction.py::_find_tables / _render_table_rows).

Contexte reel (production, "Data Analyst Expert SAS") : une section
"Competences Techniques" en tableau a deux colonnes (etiquette de
categorie a gauche, liste d'outils a droite, cellules pouvant s'etaler sur
plusieurs lignes) lue ligne par ligne se retrouvait entrelacee -- une
etiquette de categorie de la ligne N+1 collee en plein milieu de la valeur
(sur plusieurs lignes) de la ligne N. Le candidat le plus fort des deux
lots evalues avait ainsi un score semantique (le composant le plus
pondere) aussi mauvais que des candidats sans aucune des competences
listees, uniquement a cause de ce texte incoherent.

page.find_tables() (integre a PyMuPDF depuis la 1.23, aucune nouvelle
dependance, purement geometrique -- pas de modele ML comme Docling, donc
pas le meme risque de blocage CPU qui a fait retirer Docling du chemin
d'ingestion automatique) detecte les tableaux avec de vraies lignes/
remplissages et les restitue en lignes propres "categorie\tvaleurs",
retirees du flux ligne-par-ligne habituel pour ne pas etre doublees.
"""
from __future__ import annotations

import fitz

from app.services.extraction import extract_text_from_pdf

PAGE_WIDTH = 595
PAGE_HEIGHT = 842


def _draw_bordered_table(page, x0, x_mid, x1, y_bands, rows):
    """Draw a real bordered 2-column table (grid lines, not just floating
    text) -- find_tables()'s default strategy requires ruling lines/fills
    to detect a table at all, so a plain two-column CV template with no
    table framing (the case _order_lines_by_column already handles) stays
    unaffected."""
    for y in y_bands:
        page.draw_line((x0, y), (x1, y))
    page.draw_line((x0, y_bands[0]), (x0, y_bands[-1]))
    page.draw_line((x_mid, y_bands[0]), (x_mid, y_bands[-1]))
    page.draw_line((x1, y_bands[0]), (x1, y_bands[-1]))
    for (label, value), y_top in zip(rows, y_bands[:-1]):
        page.insert_text((x0 + 5, y_top + 20), label)
        page.insert_text((x_mid + 5, y_top + 20), value)


def test_bordered_table_rows_are_read_as_clean_grouped_lines(tmp_path):
    """Simple case: one line per cell, real grid lines. Each row's label
    and value must end up on the same line, in the right pairing --
    exactly what a recruiter scanning the extracted text needs to trust."""
    path = tmp_path / "table_cv.pdf"
    doc = fitz.open()
    page = doc.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
    rows = [
        ("Langages", "Python, Java, SAS, SQL, R et Scala"),
        ("Outils", "Docker, Git, Jenkins, Ansible, Terraform"),
        ("SGBD", "Oracle, PostgreSQL, MySQL, MongoDB"),
    ]
    _draw_bordered_table(page, x0=40, x_mid=180, x1=550, y_bands=[45, 75, 105, 135], rows=rows)
    doc.save(path)
    doc.close()

    result = extract_text_from_pdf(path)

    for label, value in rows:
        assert f"{label} {value}" in result, (
            f"expected '{label}' grouped with its own value on one line, got:\n{result}"
        )


def _insert_wrapped_table_text(page, x0, x_mid):
    """Row A: single-line label, value wraps across two lines. Row B:
    label itself wraps across two lines ('Outils de' / 'developpement').
    This exact shape is what corrupted the real "Compétences Techniques"
    table: row B's first label line lands, by y-position, between row A's
    two wrapped value lines."""
    page.insert_text((x0 + 5, 65), "Langages")
    page.insert_text((x_mid + 5, 65), "SAS Fundation Macro Sql Connect Config Base Stat ODS AF SCL IM OR DDE")
    page.insert_text((x_mid + 5, 80), "SAS to EXCEL SQL PL/SQL VBA R Python Matlab Scilab Pyspark PowerShell")
    page.insert_text((x0 + 5, 80), "Outils de")
    page.insert_text((x0 + 5, 95), "developpement")
    page.insert_text((x_mid + 5, 95), "Toad Siebel SAS6 SAS91 SAS92 SAS94 SASEntrepriseGuide SASVisualStudio")


def test_wrapped_table_cell_no_longer_interleaves_with_the_next_row(tmp_path):
    """Same text and coordinates rendered twice: once with no ruling lines
    at all (find_tables() detects nothing, so this exercises the exact
    pre-existing line-by-line reading order on its own -- confirms the
    interleaving bug is real for this layout) and once with a real grid
    (find_tables() detects the table, this fix's code path kicks in)."""
    x0, x_mid, x1 = 40, 180, 550

    no_table_path = tmp_path / "wrapped_no_table.pdf"
    doc = fitz.open()
    page = doc.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
    _insert_wrapped_table_text(page, x0, x_mid)
    doc.save(no_table_path)
    doc.close()

    without_fix = extract_text_from_pdf(no_table_path)
    assert "Outils de\nSAS to EXCEL" in without_fix, (
        "test setup should reproduce the interleaving bug when no table is "
        f"detected -- got:\n{without_fix}"
    )

    table_path = tmp_path / "wrapped_with_table.pdf"
    doc = fitz.open()
    page = doc.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
    _insert_wrapped_table_text(page, x0, x_mid)
    y_bands = [50, 72.5, 87.5, 105]
    for y in y_bands:
        page.draw_line((x0, y), (x1, y))
    page.draw_line((x0, y_bands[0]), (x0, y_bands[-1]))
    page.draw_line((x_mid, y_bands[0]), (x_mid, y_bands[-1]))
    page.draw_line((x1, y_bands[0]), (x1, y_bands[-1]))
    doc.save(table_path)
    doc.close()

    result = extract_text_from_pdf(table_path)

    assert "Outils de\nSAS to EXCEL" not in result, (
        f"row B's label must no longer be split by row A's wrapped value, got:\n{result}"
    )
    assert "Langages" in result and "SAS Fundation" in result


def test_plain_two_column_cv_without_any_table_is_unaffected(tmp_path):
    """No ruling lines/fills anywhere on the page -- find_tables() must
    find nothing, and the existing column-aware line ordering
    (_order_lines_by_column) must behave exactly as before this change."""
    path = tmp_path / "sidebar_no_table.pdf"
    doc = fitz.open()
    page = doc.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
    page.insert_text((40, 60), "Jean DUPONT")
    page.insert_text((40, 90), "06 12 34 56 78")
    page.insert_text((40, 120), "Python")
    page.insert_text((300, 90), "Developpement de flux ETL chez ACME")
    doc.save(path)
    doc.close()

    result = extract_text_from_pdf(path)
    lines = result.splitlines()

    assert lines.index("Jean DUPONT") < lines.index("Python")
    assert any(l.startswith("Developpement") for l in lines)
