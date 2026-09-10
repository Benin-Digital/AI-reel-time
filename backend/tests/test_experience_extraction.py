"""Tests de non-regression : extraction des annees d'experience (F8).

_extract_years() ne reconnaissait que la formulation explicite "N ans
d'experience". Beaucoup de CV n'ecrivent jamais ca et listent seulement
des postes dates ("2018 - 2023", "2020 – a ce jour") — qui renvoyaient 0,
faussant la composante experience du score.

Un calcul par plages de dates a ete ajoute EN COMPLEMENT (priorite au "N
ans" explicite quand il existe), avec fusion des periodes qui se
chevauchent pour ne pas gonfler le total avec des postes en parallele.
"""
from __future__ import annotations

from datetime import datetime

from app.services.parser import _extract_years, parse_document

CURRENT_YEAR = datetime.now().year


# ── Formulation explicite : ne doit PAS regresser ────────────────────────────

def test_explicit_years_phrasing_still_wins():
    assert _extract_years("9 années d'expérience") == 9
    assert _extract_years("5 ans d'expériences") == 5
    assert _extract_years("Expérience: 3 ans") == 3
    assert _extract_years("Minimum 8 ans en développement") == 8


# ── Nouveaux cas : periodes datees ───────────────────────────────────────────

def test_simple_date_range():
    assert _extract_years("Développeur 2018 - 2023") == 5


def test_ongoing_period_counts_to_current_year():
    assert _extract_years("Chef de projet 2024 – à ce jour") == CURRENT_YEAR - 2024
    assert _extract_years("Data Analyst 2021 – Aujourd'hui") == CURRENT_YEAR - 2021


def test_depuis_year():
    assert _extract_years("Depuis 2018 chez Acme") == CURRENT_YEAR - 2018


def test_multiple_periods_are_summed():
    # 2017-2020 (3) + 2020-2024 (4) contigus = 7
    assert _extract_years("Ingénieur BI 2020 – 2024\nConsultant 2017 – 2020") == 7


def test_overlapping_periods_are_merged_not_double_counted():
    # 2018-2023 et 2020-2024 se chevauchent -> couverture reelle 2018-2024 = 6
    assert _extract_years("Poste A: 2018-2023\nPoste B: 2020-2024") == 6


def test_range_with_prepositions():
    assert _extract_years("Expérience 2015 au 2020") == 5
    assert _extract_years("De 2019 à 2023") == 4


# ── Faux positifs a eviter : annees isolees non liees a une duree ────────────

def test_isolated_years_do_not_count():
    assert _extract_years("Diplômé en 2015") == 0
    assert _extract_years("Né en 1990") == 0
    assert _extract_years("Certification obtenue 2020") == 0


# ── Bornes ───────────────────────────────────────────────────────────────────

def test_result_stays_within_bounds():
    # Une plage absurde (avant 1970 non capturee) ne doit pas exploser
    assert _extract_years("1960 - 2024") == 0  # 1960 hors plage capturee
    assert 0 <= _extract_years("2000 - 2024") <= 40


# ── Nom de mois / mois numerique colle a l'annee (bug trouve en audit) ───────
# La regex exigeait une annee immediatement adjacente au separateur ; un nom
# de mois ou un "MM/" entre les deux faisait echouer toute la plage a 0,
# alors que c'est un format tres courant en CV francais.

def test_month_name_before_year_is_handled():
    assert _extract_years("janvier 2019 - décembre 2023") == 4
    assert _extract_years("jan 2019 - dec 2023") == 4


def test_numeric_month_before_year_is_handled():
    assert _extract_years("01/2019 - 12/2023") == 4


def test_since_with_month_name_is_handled():
    assert _extract_years("depuis janvier 2020") == CURRENT_YEAR - 2020


# ── Portee : ne pas compter les dates de la section Formation (bug d'audit) ──
# _extract_years() tournait sur experience_text + tout le document nettoye,
# donc des plages de dates de formation (ex: "Master 2015-2017") s'ajoutaient
# a la vraie experience professionnelle des qu'une section Experience existait.

# ── De nombreuses missions courtes consecutives ne doivent pas s'annuler ────
# Trouve en production : un CV de consultant IT/finance batie sur ~15
# missions courtes (quelques mois chacune), toutes datees en "MM/YYYY -
# MM/YYYY", donnait "Experience: 1 ans" pour une carriere reelle d'environ
# 20 ans. Cause : la regex de plage ne capture que l'annee, donc une
# mission entierement dans une seule annee civile (ex: "01/2018 - 07/2018")
# devient l'intervalle de duree nulle (2018, 2018) ; des missions
# consecutives sur des annees civiles differentes (2017, puis 2018) ne se
# fusionnaient pas non plus (2018 <= 2017 est faux), donc chacune
# contribuait 0 au total au lieu de s'enchainer.

def test_many_short_consecutive_missions_are_not_undercounted():
    cv_text = (
        "Experience\n"
        "11/2022 – 08/2023\nMission A\n"
        "10/2021 – 06/2022\nMission B\n"
        "10/2020 – 07/2021\nMission C\n"
        "08/2019 – 07/2020\nMission D\n"
        "01/2019 – 06/2019\nMission E\n"
        "08/2018 – 11/2018\nMission F\n"
        "01/2018 – 07/2018\nMission G\n"
        "08/2017 – 11/2017\nMission H\n"
        "01/2017 – 04/2017\nMission I\n"
    )
    years = _extract_years(cv_text)
    assert years >= 6, (
        f"9 missions courtes s'enchainant sans interruption de 2017 a 2023 "
        f"(couverture reelle ~6-7 ans) ne doivent pas s'annuler a ~0, obtenu {years}"
    )


def test_education_date_ranges_are_not_counted_as_experience():
    cv_text = (
        "Formation\n"
        "Master Informatique - 2015 - 2017\n"
        "Licence Informatique - 2012 - 2015\n"
        "\n"
        "Experience\n"
        "Ingenieur logiciel chez ACME - 2020 - 2023\n"
    )
    doc = parse_document(cv_text, kind="cv")
    assert doc.experience_years == 3, "seule la periode 2020-2023 est une vraie experience professionnelle"
