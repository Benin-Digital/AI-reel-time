"""Tests : alias ambigus retires de la taxonomie (nettoyage faux positifs).

Trois entrees avaient des alias trop larges qui matchaient hors de leur
domaine, observes sur des CV reels de gestion de projet :

- "Conduite de travaux" (BTP) avait l'alias "moe" / "maitrise d oeuvre" —
  or MOE = maitrise d'oeuvre en gestion de projet, sans rapport avec le
  BTP. Un profil "AMOA et MOE" matchait a tort un metier de chantier.
- "Mathematiques" avait "algebre" (algebre de Boole = logique de prog) et
  "analyse" (trop generique : "analyse des besoins"...).
- "Cloture comptable" avait "cloture" seul, qui matche "cloture de projet".

Les alias specifiques et non ambigus sont conserves.
"""
from __future__ import annotations

from app.services.taxonomy import find_skills


def test_moe_is_not_construction():
    """MOE (maitrise d'oeuvre projet) ne doit plus matcher le BTP."""
    result = find_skills("Consulting AMOA et MOE, maitrise d'ouvrage")
    assert "Conduite de travaux" not in result


def test_real_construction_still_matches():
    assert "Conduite de travaux" in find_skills("conducteur de travaux sur chantier")
    assert "Conduite de travaux" in find_skills("chef de chantier")


def test_algebra_is_not_mathematics_skill():
    assert "Mathématiques" not in find_skills("algorithmique et algebre de boole")


def test_real_mathematics_still_matches():
    assert "Mathématiques" in find_skills("mathematiques appliquees")


def test_project_closure_is_not_accounting_closure():
    assert "Clôture comptable" not in find_skills("cloture et bilan de projets")


def test_real_accounting_closure_still_matches():
    assert "Clôture comptable" in find_skills("cloture comptable annuelle")
    assert "Clôture comptable" in find_skills("cloture mensuelle des comptes")
