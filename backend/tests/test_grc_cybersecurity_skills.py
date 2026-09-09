"""Tests pour les termes de gouvernance/risque/conformite (GRC) et
cybersecurite ajoutes a la taxonomie hand-curated (taxonomy.py).

Contexte : un controle manuel sur un vrai CV de consultant senior
cybersecurite/GRC a montre que 11 des 18 termes de son profil n'etaient
pas reconnus par find_skills() : ISO 27001, ISO 27005, ISO 42001, EBIOS,
DORA, NIS2, CISA, PCI-DSS, SMSI, IAM, PKI, COBIT, ISAE 3402, SOX. Seuls
ITIL et GDPR/RGPD (deja mappe sur "Compliance") passaient. Ce n'etait pas
un probleme de detection de section (skills_text) mais un vrai trou de
vocabulaire : find_skills() tourne sur le texte complet, independamment
des sections, et ne trouvait simplement pas ces termes dans la taxonomie.
"""
from __future__ import annotations

from app.services.taxonomy import find_skills, normalize_skill

_NEW_TERMS = {
    "ISO 27001": "ISO 27001",
    "ISO 27005": "ISO 27005",
    "ISO 42001": "ISO 42001",
    "EBIOS": "EBIOS",
    "DORA": "DORA",
    "NIS2": "NIS2",
    "CISA": "CISA",
    "PCI-DSS": "PCI-DSS",
    "SMSI": "SMSI",
    "IAM": "IAM",
    "PKI": "PKI",
    "COBIT": "COBIT",
    "COBIT 5.0": "COBIT",
    "ISAE 3402": "ISAE 3402",
    "SOX": "SOX",
}


def test_grc_and_cybersecurity_terms_resolve():
    for term, expected in _NEW_TERMS.items():
        assert normalize_skill(term) == expected, f"{term!r} devrait resoudre a {expected!r}"


def test_real_grc_cv_excerpt_detects_all_new_terms():
    """Reproduit l'extrait reel (liste de normes/reglementations) qui a
    revele le trou de vocabulaire."""
    excerpt = (
        "Normes et referentiels ISO 27001, ISO 42001, NIST, PCI-DSS, RGS, ITIL, COBIT 5.0 "
        "Reglementations IA Act, DORA, NIS2, ISAE 3402, GDPR, SOX, HDS, Bale 2"
    )
    result = find_skills(excerpt)
    for expected in ("ISO 27001", "ISO 42001", "PCI-DSS", "ITIL", "COBIT",
                      "DORA", "NIS2", "ISAE 3402", "SOX"):
        assert expected in result, f"{expected!r} absent de {result!r}"


def test_dora_bare_alias_is_a_known_accepted_false_positive_risk():
    """Compromis documente, pas un oubli : "dora" collisionne avec le
    prenom (find_skills replie la casse), contrairement a "c"/"son" (des
    mots grammaticaux francais quasi omnipresents, ceux-la ont ete exclus)
    -- une mention isolee du prenom est rare dans un CV/une offre, et
    l'acronyme brut est la forme reelle utilisee dans les CV GRC/finance.
    Si ce test casse un jour, c'est que le compromis a ete revisite
    consciemment, pas une regression silencieuse."""
    assert find_skills("Dora est partie en vacances avec son chien.") == ["DORA"]
