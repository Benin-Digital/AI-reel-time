"""Tests de non-regression : detection de domaine (F9).

detect_domain() comptait 1 point par mot-cle present et prenait le max,
les egalites etant tranchees par l'ordre d'insertion du dict. Sur des
profils transverses (ex: un chef de projet IT en banque), plusieurs
domaines arrivaient a egalite a 1 point et le gagnant etait arbitraire —
souvent "tech" a cause d'un simple "sql" venant du mot "MySql".

Ameliorations :
- signaux metier manquants ajoutes (chef de projet / MOA / MOE / PMO /
  AMOA -> management ; ingenieur BI / ETL -> tech ; etc.)
- signaux "forts" (titres de poste) comptes double vs mots-cles isoles
- egalites tranchees de facon deterministe par _TIE_PRIORITY (domaines
  au metier le plus specifique d'abord) plutot que par ordre du dict
- retrait des mots de secteur ambigus (finance/rh/transport... isoles)
"""
from __future__ import annotations

from app.services.parser import (
    _DOMAIN_SIGNALS,
    _STRONG_SIGNALS,
    _TIE_PRIORITY,
    detect_domain,
)

# ── Profils transverses : le metier reel doit gagner ─────────────────────────

def test_project_manager_is_management_not_tech():
    """Un chef de projet qui mentionne quelques outils ne doit pas basculer
    en 'tech' juste a cause d'un 'sql'."""
    cv = (
        "Chef de projets MOE/MOA, 9 ans. Gestion de projet, cadrage, AMOA, "
        "Agile Scrum. Outils : Java, MySql, Angular, Power BI, VBA."
    )
    assert detect_domain(cv) == "management"


def test_direction_projet_is_management():
    cv = (
        "Direction de projets, PMO, transformation. Consulting AMOA et MOE, "
        "maitrise d'ouvrage, pilotage, comites de direction."
    )
    assert detect_domain(cv) == "management"


def test_bi_engineer_stays_tech():
    cv = (
        "Ingenieur en Business Intelligence. Ingenieur BI, developpeur. "
        "SSIS SSAS SSRS Power BI SQL Server Python ETL."
    )
    assert detect_domain(cv) == "tech"


# ── Profils mono-domaine : ne doivent PAS changer ────────────────────────────

def test_nurse_is_health():
    cv = "Infirmiere DE en service d'urgences. Soins aux patients, hopital, reanimation."
    assert detect_domain(cv) == "health"


def test_salesperson_is_commercial():
    cv = "Commercial B2B. Prospection, CRM, portefeuille client, account manager."
    assert detect_domain(cv) == "commercial"


def test_accountant_is_finance():
    cv = "Comptable, expert comptable. Comptabilite, consolidation, IFRS, Sage, Cegid."
    assert detect_domain(cv) == "finance"


# ── Cas limites ──────────────────────────────────────────────────────────────

def test_short_signal_glued_inside_unrelated_word_does_not_win():
    """Regression reelle (production, offre "Data Analyst Expert SAS",
    2026-09-11) : les signaux courts "ide" (fort, sante) et "soins" (sante)
    matchaient en simple sous-chaine dans "SAS Enterprise Guide" et
    "besoins", suffisant a lui seul (ide compte double) pour classer une
    offre Data Analyst / SQL / SAS en domaine "health"."""
    job = (
        "Data Analyst Expert SAS. Developper et maintenir des traitements "
        "sous SAS Enterprise Guide, SAS Grid et SAS Base. Concevoir, "
        "optimiser et executer des requetes SQL. Analyser les besoins des "
        "utilisateurs internes. Connaissance du secteur de l'assurance "
        "appreciee."
    )
    assert detect_domain(job) == "tech"


def test_no_signal_is_general():
    assert detect_domain("Texte sans aucun signal metier particulier.") == "general"
    assert detect_domain("") == "general"


def test_strong_signal_outweighs_lone_keyword():
    """Un titre de poste (fort, x2) doit l'emporter sur un mot-cle isole."""
    # "recruteur" (fort, hr) vs "sql" (faible, tech)
    assert detect_domain("Recruteur. Utilise parfois un export sql.") == "hr"


# ── Coherence interne des structures ─────────────────────────────────────────

def test_strong_signals_are_subset_of_domain_signals():
    for domain, strong in _STRONG_SIGNALS.items():
        assert domain in _DOMAIN_SIGNALS, f"domaine fort orphelin: {domain}"
        missing = strong - set(_DOMAIN_SIGNALS[domain])
        assert not missing, f"{domain}: signaux forts hors liste: {missing}"


def test_tie_priority_covers_all_domains():
    assert set(_TIE_PRIORITY) == set(_DOMAIN_SIGNALS)
