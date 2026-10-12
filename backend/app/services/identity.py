"""Identité d'un candidat, pour regrouper les candidatures d'une même personne.

Un candidat qui dépose plusieurs CV (versions, intitulés différents) apparaissait
plusieurs fois dans le classement d'une offre. Constaté le 2026-10-12 sur la
plateforme soeur Keoni : une même personne aux rangs 7, 8 et 9
(« OUENJLI ABDELGHAFOUR » / « ABDELGHAFOUR OUENJLI »).
"""
from __future__ import annotations

import re

from .structured import fold_text


def normalize_person_name(name: str | None) -> str | None:
    """Clé de nom indépendante de l'ordre prénom / nom, des accents et de la
    casse : « OUENJLI Abdelghafour » et « Abdelghafour Ouenjli » donnent la même.
    Au moins deux mots d'au moins deux lettres, sinon None (un nom d'un seul mot
    n'identifie personne)."""
    tokens = sorted(re.findall(r"[a-z]{2,}", fold_text(name or "")))
    return " ".join(tokens) if len(tokens) >= 2 else None
