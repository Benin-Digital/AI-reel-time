"""Tests de non-regression : mots de secteur d'activite vs competences (F3).

Bug trouve sur un CV reel (Rachida Omari) : la ligne
"Experience sectorielle : Banque, Finance, Transport, Telecom, E-commerce,
Luxe, RH" — une liste de SECTEURS, pas de competences — generait une
fausse competence "Transport", parce que le mot generique "transport"
etait un alias de la competence logistique "Transport". Idem "retail"
etait un alias de "Vente B2C".

Ces alias mono-mot ambigus ont ete retires ; les alias specifiques et non
ambigus de ces memes competences (gestion du transport, affretement,
vente b2c...) sont conserves.
"""
from __future__ import annotations

from app.services.taxonomy import find_skills


def test_sector_list_does_not_produce_skills():
    """Une ligne enumerant des secteurs d'activite ne doit generer aucune
    fausse competence."""
    sectors = "Experience sectorielle : Banque, Finance, Transport, Telecom, E-commerce, Luxe, RH"
    result = find_skills(sectors)
    assert "Transport" not in result, f"faux positif secteur->competence : {result}"


def test_retail_sector_word_is_not_a_skill():
    result = find_skills("Secteur : Retail, Grande distribution")
    assert "Vente B2C" not in result, f"faux positif secteur->competence : {result}"


def test_specific_transport_skills_still_match():
    """Les usages non ambigus de la competence Transport doivent rester
    detectes (un logisticien decrivant son metier)."""
    assert "Transport" in find_skills("gestion du transport de marchandises")
    assert "Transport" in find_skills("responsable affretement et expedition")


def test_specific_b2c_skills_still_match():
    """Les usages non ambigus de Vente B2C doivent rester detectes."""
    assert "Vente B2C" in find_skills("experience en vente b2c")
    assert "Vente B2C" in find_skills("business to consumer")
