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

from app.services.extraction import _detect_column_gutter, extract_text_from_pdf

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


def test_name_in_right_sidebar_is_not_buried_behind_a_long_left_body(tmp_path):
    """Regression reelle (production, 2026-09-09) : sidebar courte (nom,
    contact, competences) a DROITE, corps principal long a GAUCHE.

    PyMuPDF fusionne souvent tout le corps principal en un seul bloc dont la
    bbox est l'union de toutes ses lignes -- si une seule ligne de ce corps
    depasse le milieu de page, la bbox du bloc entier chevauche le milieu,
    le classant "pleine largeur" au lieu de "colonne gauche". La detection
    de mise en page a 2 colonnes se desactive alors, et l'ancienne version
    (qui triait des BLOCS entiers, pas des lignes) faisait sortir tout le
    bloc du corps principal (potentiellement des dizaines de lignes) avant
    le bloc du nom des qu'ils demarraient a un y proche (egalite tranchee
    par x, et le corps commence plus a gauche) -- repoussant le nom bien
    au-dela de la fenetre de lignes que le heuristique de nom scanne."""
    path = tmp_path / "right_sidebar_cv.pdf"
    inserts = [((72, 60 + i * 14), f"Ligne d'experience professionnelle {i} chez ACME") for i in range(50)]
    inserts += [
        ((420, 60), "Jean DUPONT"),
        ((420, 90), "06 12 34 56 78"),
        ((420, 120), "Python"),
        ((420, 150), "Docker"),
    ]
    _make_pdf(path, inserts)

    result = extract_text_from_pdf(path)
    lines = result.splitlines()

    name_position = lines.index("Jean DUPONT")
    assert name_position < 40, (
        f"le nom doit rester dans la fenetre scannee par le heuristique de "
        f"nom (build_document_profile), obtenu position={name_position}"
    )


def test_narrow_sidebar_does_not_swallow_short_main_body_lines(tmp_path):
    """Regression reelle (production) : sidebar ETROITE (~25% de la page,
    pas ~50%) a gauche, corps principal qui demarre bien avant le milieu
    exact de page.

    Contre un split fixe a page_width/2, une ligne courte du corps
    principal (un intitule de poste, une etiquette d'une ou deux lignes)
    qui se termine avant ce milieu se retrouve classee "colonne gauche" et
    entrelacee par y avec la vraie sidebar -- entrelacant deux sections
    sans rapport en plein milieu du corps, alors meme que la ligne
    appartient au corps principal, pas a la sidebar. Vu sur un CV a
    template riche (sidebar certifications/outils + corps experience) :
    le texte extrait melangeait des fragments d'outils avec des bouts de
    phrases de descriptions de poste.

    _detect_column_gutter() doit placer la coupure au vrai gouffre entre
    les deux colonnes (~175, entre la fin de la sidebar a ~150 et le debut
    du corps a 200) plutot qu'au milieu fixe de la page (297.5), pour que
    cette ligne courte du corps principal reste classee a droite."""
    path = tmp_path / "narrow_sidebar_cv.pdf"
    inserts = [
        ((40, 60), "Jean DUPONT"),
        ((40, 90), "Certifications"),
        ((40, 120), "SAFe PO"),
        ((40, 150), "Scrum PSPO"),
        ((200, 60), "Chef de Projet MOA"),
        (
            (200, 90),
            "Pilotage de projets SI en environnement multi-pays avec coordination "
            "des equipes metiers et IT sur les evolutions applicatives",
        ),
        ((200, 120), "APIs - recette"),
        ((200, 150), "Animation des ceremonies Agile Sprint Planning Reviews Retrospectives"),
    ]
    _make_pdf(path, inserts)

    result = extract_text_from_pdf(path)
    lines = result.splitlines()

    sidebar = ["Jean DUPONT", "Certifications", "SAFe PO", "Scrum PSPO"]
    sidebar_positions = [lines.index(l) for l in sidebar]
    body_first = lines.index("Chef de Projet MOA")
    body_tag = lines.index("APIs - recette")

    assert max(sidebar_positions) < body_first, (
        f"'APIs - recette' et le reste du corps principal ne doivent jamais "
        f"s'intercaler dans la sidebar, obtenu sidebar={sidebar_positions} "
        f"corps={lines[body_first:]!r}"
    )
    assert body_first < body_tag, (
        "les lignes du corps principal, y compris les courtes comme "
        "'APIs - recette', doivent rester groupees ensemble dans leur "
        f"ordre naturel, obtenu {lines!r}"
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


def test_narrow_real_gutter_is_not_rejected_as_pixel_noise():
    """Regression reelle (validation du corpus de 13 715 CV, 2026-09-14,
    CV Aurelien Torres) : le vrai gouffre entre les deux colonnes de ce CV
    ne mesurait que ~20.5pt sur une page de 595pt de large (3.4% de la
    largeur) -- juste sous l'ancien seuil de 4% (23.8pt), qui traitait ce
    gouffre bien REEL comme du bruit et retombait sur le milieu exact de
    page (297.75). Ce point de coupure tombait en plein milieu de la
    colonne de droite (large, plusieurs lignes courtes), donnant une part
    de caracteres a droite de seulement ~3% -- le garde-fou en aval
    (_order_lines_by_column) rejetait alors ce point a raison, mais
    n'avait aucun autre candidat a essayer et abandonnait toute detection
    de colonnes, retombant sur un tri (y, x) qui entrelacait le paragraphe
    "Profil Personnel" de la sidebar avec les titres et le corps principal
    en plein milieu de phrase."""
    left = [
        {"bbox": (40.0, 60.0, 113.3, 63.0), "text": "Jean DUPONT"},
        {"bbox": (40.0, 90.0, 103.6, 93.0), "text": "Certifications"},
        {"bbox": (40.0, 120.0, 95.6, 123.0), "text": "Profil perso"},
        {"bbox": (40.0, 150.0, 108.5, 153.0), "text": "Curiosite forte"},
    ]
    right = [
        {"bbox": (134.0, 60.0, 232.4, 63.0), "text": "Chef de Projet MOA"},
        {"bbox": (134.0, 90.0, 472.1, 93.0), "text": "Pilotage de projets SI en environnement multi-pays"},
        {"bbox": (134.0, 120.0, 183.5, 123.0), "text": "Formation"},
        {"bbox": (134.0, 150.0, 258.7, 153.0), "text": "Master informatique 2018"},
    ]
    mid = _detect_column_gutter(left + right, page_width=595.0)
    assert 113.3 < mid < 134.0, (
        f"le vrai gouffre (113.3-134.0) ne doit pas etre rejete au profit "
        f"du milieu de page fixe (297.5), obtenu mid={mid}"
    )


def test_narrow_real_gutter_end_to_end_keeps_sections_grouped(tmp_path):
    """Bout-en-bout : la regression Torres ci-dessus, via un vrai PDF rendu
    avec exactement ce gouffre de ~20.7pt entre les deux colonnes."""
    path = tmp_path / "narrow_real_gutter_cv.pdf"
    _make_pdf(path, [
        ((40, 60), "Jean DUPONT"),
        ((40, 90), "Certifications"),
        ((40, 120), "Profil perso"),
        ((40, 150), "Curiosite forte"),
        ((134, 60), "Chef de Projet MOA"),
        ((134, 90), "Pilotage de projets SI en environnement multi-pays avec coordination"),
        ((134, 120), "Formation"),
        ((134, 150), "Master informatique 2018"),
    ])

    result = extract_text_from_pdf(path)
    lines = result.splitlines()

    sidebar = ["Jean DUPONT", "Certifications", "Profil perso", "Curiosite forte"]
    sidebar_positions = [lines.index(l) for l in sidebar]
    body_first = lines.index("Chef de Projet MOA")
    body_last = lines.index("Master informatique 2018")

    assert max(sidebar_positions) < body_first, (
        f"le corps principal ne doit jamais s'intercaler dans la sidebar "
        f"a cause d'un gouffre etroit mais reel, obtenu sidebar={sidebar_positions} "
        f"body_first={body_first} dans {lines!r}"
    )
    assert body_first < body_last, "le corps principal doit rester groupe dans son ordre naturel"


def test_empty_page_returns_empty_string(tmp_path):
    path = tmp_path / "empty.pdf"
    doc = fitz.open()
    doc.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
    doc.save(path)
    doc.close()

    assert extract_text_from_pdf(path) == ""
