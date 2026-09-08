"""Tests de non-regression : _build_lookup() construit alias -> canonical via
un simple dict, donc un alias partage par deux competences canoniques
differentes etait silencieusement attribue a la DERNIERE declaree dans
_SKILLS, en ecrasant la premiere sans aucun avertissement.

5 collisions trouvees en auditant toute la taxonomie (voir corrections dans
taxonomy.py) :
- "service client" -> toujours "Sens du service" (soft skill) au lieu de
  "Service client" (hard skill), un terme tres frequent.
- "controle de gestion" / "controlling" -> toujours "Contrôle de gestion",
  jamais "Comptabilité analytique" (qui perdait ces deux alias).
- "analyse financiere" -> toujours "Analyse financière", jamais
  "Contrôle de gestion".
- "ingenierie pedagogique" -> toujours "Pédagogie", jamais "Formation".

Le premier test scanne TOUTE la taxonomie pour interdire qu'une future
modification de _SKILLS reintroduise ce genre de collision silencieuse.
"""
from __future__ import annotations

import unicodedata

from app.services.taxonomy import _SKILLS, normalize_skill


def _fold(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", text)
    return nfkd.encode("ascii", "ignore").decode("ascii").lower()


def test_no_alias_is_shared_by_two_different_canonical_skills():
    owner_by_alias: dict[str, str] = {}
    collisions: list[str] = []

    for canonical, aliases in _SKILLS.items():
        for alias in aliases:
            key = _fold(alias)
            if not key:
                continue
            existing = owner_by_alias.get(key)
            if existing is not None and existing != canonical:
                collisions.append(f"{key!r}: {existing!r} vs {canonical!r}")
            else:
                owner_by_alias[key] = canonical

    assert not collisions, (
        "Alias partages par plusieurs competences canoniques (le dernier "
        "declare dans _SKILLS ecrase silencieusement le precedent) :\n"
        + "\n".join(collisions)
    )


def test_service_client_resolves_to_the_hard_skill_not_the_soft_skill():
    assert normalize_skill("service client") == "Service client"


def test_controle_de_gestion_resolves_correctly():
    assert normalize_skill("controle de gestion") == "Contrôle de gestion"
    assert normalize_skill("controlling") == "Contrôle de gestion"


def test_analyse_financiere_resolves_to_its_own_canonical():
    assert normalize_skill("analyse financiere") == "Analyse financière"


def test_ingenierie_pedagogique_resolves_to_pedagogie():
    assert normalize_skill("ingenierie pedagogique") == "Pédagogie"
