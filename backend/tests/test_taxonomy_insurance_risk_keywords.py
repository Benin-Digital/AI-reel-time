"""Tests : enrichissement de la taxonomie avec les mots-cles observes en
production (F10).

Chaque offre reelle echantillonnee etait accompagnee d'un "Mots Cles.docx"
(voir la fonctionnalite mots-cles prioritaires) -- plusieurs de ces termes
n'avaient aucune presence dans le dictionnaire de competences, ce qui les
rendait invisibles a find_skills() meme quand un CV les mentionnait
explicitement. Ce fichier verifie que les termes ajoutes resolvent bien,
et que les exclusions deliberees (mots trop ambigus pour le dictionnaire
global) restent exclues.
"""
from __future__ import annotations

from app.services.taxonomy import normalize_skill, find_skills


def test_previously_missing_terms_now_resolve():
    checks = {
        "iard": "IARD",
        "secteur de l assurance": "Assurance",
        "gestion des sinistres": "Gestion des sinistres",
        "sinistres": "Gestion des sinistres",
        "gestion des risques": "Gestion des risques",
        "cartographie des risques": "Gestion des risques",
        "lod1": "Lignes de défense (LOD)",
        "lod2": "Lignes de défense (LOD)",
        "nist": "NIST",
        "grc": "GRC (gouvernance, risques, conformité)",
        "analyse des besoins": "Analyse des besoins",
        "besoins metiers": "Analyse des besoins",
        "outils bureautiques": "Outils bureautiques",
        "data analyst": "Data Analyst",
        "orm": "ORM",
        "full stack": "Développeur Full Stack",
        "fullstack": "Développeur Full Stack",
        "frontend": "Frontend",
        "backoffice": "Back-office",
        "tableaux de bord": "Reporting",
        "bases de donnees": "SGBD",
        "webservices": "API REST",
        "vulnerabilites": "Cybersécurité",
        "data management": "Data Engineering",
        "parties prenantes": "Parties prenantes",
        "cycle en v": "Cycle en V",
        "projet reglementaire": "Compliance",
    }
    for alias, expected_canonical in checks.items():
        assert normalize_skill(alias) == expected_canonical, (
            f"{alias!r} devrait resoudre a {expected_canonical!r}"
        )


def test_deliberately_excluded_terms_stay_unresolved():
    """Ces termes restent hors taxonomie globale : trop ambigus (sens
    courant different en francais) ou deja converts par le principe
    "un secteur n'est pas une competence" (voir
    test_generic_sector_words_are_not_skills). Toujours utilisables au cas
    par cas via les mots-cles prioritaires d'une offre."""
    for word in ("assurance", "sinistre", "recette", "run", "trm", "banque", "finance"):
        assert normalize_skill(word) is None, f"{word!r} doit rester hors taxonomie globale"


def test_back_office_plural_hyphenated_form_resolves():
    """Regression reelle (CV Abas Konate, offre "Developpeur Full Stack
    PHP/Laravel/VueJS", 2026-09-11) : le profil ecrit "des outils metiers
    et des back-offices" (pluriel, trait d'union) -- ce candidat construit
    reellement des back-offices, mais le mot-cle restait invisible car seul
    le singulier etait enregistre (find_skills ne fait pas de stemming,
    voir le precedent "declaration de sinistre")."""
    assert normalize_skill("back-offices") == "Back-office"
    assert normalize_skill("backoffices") == "Back-office"
    assert "Back-office" in find_skills("des outils metiers et des back-offices")


def test_sector_word_invariant_still_holds():
    """Non-regression explicite sur le principe touche par cet ajout : un
    secteur d'activite ne doit toujours jamais devenir une 'competence',
    meme apres l'ajout de la section assurance/risque/conformite."""
    result = find_skills("Expérience sectorielle : Banque, Finance, Assurance, Transport")
    assert "Secteur bancaire" not in result
    assert "Secteur finance" not in result


def test_real_job_offer_text_detects_expected_skills():
    """Reproduit le vrai texte de l'offre "Chef de Projet MOA - Indemnisation
    IARD" observee en production : avant cet ajout, aucun des termes
    metier (assurance, sinistres) n'etait detecte."""
    text = (
        "Bonne compréhension des enjeux métiers de l'indemnisation IARD et des "
        "processus de gestion des sinistres. Expérience avérée dans le secteur "
        "de l'assurance, idéalement sur le périmètre indemnisation IARD."
    )
    result = find_skills(text)
    assert "IARD" in result
    assert "Gestion des sinistres" in result
    assert "Assurance" in result


def test_singular_declaration_de_sinistre_is_detected_without_the_ambiguous_bare_word():
    """Regression reelle (Christophe Jalier, meme offre "Chef de Projet MOA -
    Indemnisation IARD", 2026-09-11) : son CV decrit une vraie experience
    de systeme de gestion de sinistres avec la formulation singuliere
    "declaration de sinistre" (verbe "declarer", pas "gerer") -- absente
    tant que seul le pluriel "sinistres" etait enregistre. La phrase
    complete (3 mots) n'a pas la meme ambiguite que le mot seul "sinistre"
    (qui reste exclu, voir test_deliberately_excluded_terms_stay_unresolved)
    puisque find_skills() compare la phrase exacte, pas un mot isole."""
    assert normalize_skill("sinistre") is None
    assert "Gestion des sinistres" in find_skills("systemes de declaration de sinistre")
    assert "Gestion des sinistres" in find_skills("indemnisation")
