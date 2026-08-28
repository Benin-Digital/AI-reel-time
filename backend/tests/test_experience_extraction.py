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

from app.services.parser import _extract_years

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
