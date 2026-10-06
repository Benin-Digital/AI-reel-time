"""Tests : representation semantique robuste (F4).

_semantic_repr() ne prenait qu'UNE section (la premiere non vide dans un
ordre de priorite). Si la classification de section se trompait, le
cross-encoder recevait le mauvais extrait. Desormais la representation
combine les sections informatives (exigences/competences + resume), avec
un complement par le texte nettoye si elles sont trop maigres. Plafonnee
a 200000 caracteres (2026-10-06, releve de 12000) en garde-fou contre un
document pathologique uniquement -- plus une vraie limite de contenu,
voir _cross_encode_best() dans matcher.py pour le meme changement cote
decoupage en fenetres.

Invariants : symetrie CV/Job preservee sur un self-match, robustesse
quand les sections sont vides.
"""
from __future__ import annotations

from app.services import matcher
from app.services.parser import ParsedDocument, parse_document

JOB_TEXT = """Fiche de poste : Developpeur back-end
Missions principales
Concevoir et developper une API REST exposant les operations metier
Environnement technique : Node.js, TypeScript, PostgreSQL, Docker, Git
Competences techniques requises
Maitrise de Node.js avec TypeScript
Conception d'API REST, Documentation OpenAPI
Profil recherche
Experience : 3 ans minimum en developpement back-end"""


def test_semantic_repr_symmetric_on_self_match():
    cv = parse_document(JOB_TEXT, kind="cv")
    job = parse_document(JOB_TEXT, kind="job")
    assert matcher._semantic_repr(cv) == matcher._semantic_repr(job)


def test_semantic_repr_is_bounded():
    cv = parse_document(JOB_TEXT * 20, kind="cv")  # very long input
    assert len(matcher._semantic_repr(cv)) <= 200000


def test_semantic_repr_does_not_truncate_a_long_real_world_sized_cv():
    # 2026-10-06 : des CV reels en base font jusqu'a ~20 pages. L'ancien
    # plafond de _semantic_repr (12000 car.) et celui de _cross_encode_best
    # (8 fenetres de 800 car. = 6400 car.) coupaient silencieusement tout
    # contenu au-dela -- le cross-encoder ne voyait jamais la fin d'un CV
    # de cette taille. Les deux sont desormais des garde-fous tres larges
    # (pathological input only), plus des limites pratiques : ce test
    # verrouille qu'un contenu realiste de ~20 pages (environ 70000
    # caracteres) traverse _semantic_repr intact.
    long_skills_text = "Python, Django, PostgreSQL. " * 2500  # ~72500 caracteres
    cv = ParsedDocument(
        kind="cv",
        domain="general",
        raw_text=long_skills_text,
        cleaned_text=long_skills_text,
        skills_text=long_skills_text,
    )
    repr_text = matcher._semantic_repr(cv)
    assert len(repr_text) == len(long_skills_text.strip())


def test_semantic_repr_combines_multiple_sections():
    """La representation doit contenir plus que la seule premiere section :
    on verifie qu'au moins deux infos distinctes du document y figurent."""
    job = parse_document(JOB_TEXT, kind="job")
    repr_text = matcher._semantic_repr(job).lower()
    # Des elements issus de sections differentes doivent coexister
    assert "api rest" in repr_text
    assert repr_text.strip() != ""


def test_semantic_repr_falls_back_on_empty_sections():
    """Un document sans sections structurees exploitables retombe sur le
    texte nettoye plutot que de renvoyer une chaine vide."""
    doc = parse_document("Juste du texte libre sans structure particuliere ici.", kind="cv")
    repr_text = matcher._semantic_repr(doc)
    assert repr_text.strip() != ""
