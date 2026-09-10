"""Test de non-regression : mots courts et matching approximatif (F9).

Trouve en production sur une offre "Chef de Projet MOA - Indemnisation
IARD" (aucun contenu technique) : "Git" apparaissait comme competence
requise. AI_REALTIME_SCORING_SKILL_KEYWORDS liste "git" par defaut (liste
generique orientee stack technique) ; dans find_skills(), la passe de
matching approximatif (difflib, seuil 0.8) compare CE mot-cle a tous les
mots du texte -- et "it" (l'acronyme "IT" comme dans "strategie IT du
groupe", tres courant en texte business) obtient un ratio de similarite
de 0.8 avec "git" (SequenceMatcher("git", "it").ratio() == 0.8), pile au
seuil.

Meme categorie de bug que _ROME_ALIAS_STOPWORDS (voir plus haut dans
taxonomy.py) : un mot-cle trop court rend le matching approximatif peu
fiable. Applique ici a la passe floue plutot qu'a la passe exacte du
vocabulaire ROME.
"""
from __future__ import annotations

from app.services.taxonomy import find_skills


def test_it_acronym_does_not_fuzzy_match_git():
    result = find_skills(
        "Conseiller les metiers, securiser les orientations prises en "
        "coherence avec la strategie IT du groupe."
    )
    assert "Git" not in result


def test_real_git_mention_still_matches():
    assert "Git" in find_skills("Maitrise de Git et Github pour le versioning")
    assert "Git" in find_skills("Gestion des branches avec git")


def test_other_short_whitelist_entries_still_match_exactly():
    """sql/aws restent detectes par alias exact (taxonomie ou whitelist
    exacte) meme si le matching approximatif ne les couvre plus."""
    assert "SQL" in find_skills("Requetes SQL avancees")
