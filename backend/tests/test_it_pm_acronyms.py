"""Tests pour les termes IT/gestion de projet ajoutes a la taxonomie apres
une analyse de couverture a grande echelle sur ~13700 vrais CV.

Contexte : un controle systematique (comptage de frequence des acronymes
majuscules 2-8 lettres non reconnus par normalize_skill(), sur l'ensemble
du corpus) a fait ressortir des dizaines de vrais termes techniques/metier
manquants (BI, ERP, UML, UX/UI, TMA, protocoles reseau, etc.), noyes parmi
beaucoup de bruit qui a ete explicitement ecarte :
- noms d'entreprises clientes/employeurs (SNCF, AXA, BNP, EDF...) -- pas
  des competences ;
- mots de secteur trop generiques (IT, SI, DATA) -- meme categorie que
  "Finance"/"Assurances" deja exclus lors de l'import ROME ;
- artefacts de mise en forme (titres de section en majuscules : LANGUES,
  PROJET, MANAGER, CONTACT...) ;
- acronymes a 2-3 lettres trop ambigus sans desambiguisation claire (DB,
  CA, PC, XP...).

Seuls les termes retenus sont testes ici. Verifie aussi explicitement
l'absence de faux positifs sur du texte francais ordinaire, le meme type
de risque deja rencontre avec "c"/"son" (voir test_rome_skills_import.py)
et "dora" (voir test_grc_cybersecurity_skills.py) : les termes courts
retenus ici ne sont pas des mots du francais courant.
"""
from __future__ import annotations

from app.services.taxonomy import find_skills, normalize_skill

_NEW_TERMS = {
    "BI": "Business Intelligence",
    "ERP": "ERP",
    "MOE": "Maîtrise d'œuvre",
    "UML": "UML",
    "UX": "UX/UI Design",
    "UI": "UX/UI Design",
    "IHM": "UX/UI Design",
    "TMA": "TMA",
    "SGBD": "SGBD",
    "JEE": "J2EE",
    "J2EE": "J2EE",
    "JPA": "JPA",
    "JSF": "JSF",
    "MVC": "MVC",
    "SSO": "SSO",
    "ALM": "ALM",
    "HP ALM": "ALM",
    "GLPI": "GLPI",
    "SCCM": "SCCM",
    "TFS": "TFS",
    "CISCO": "Cisco",
    "VMWARE": "VMware",
    "MDM": "MDM",
    "RSSI": "RSSI",
    "SEPA": "SEPA",
    "SOA": "SOA",
    "KYC": "KYC",
    "PCA": "Continuité d'activité",
    "PRA": "Continuité d'activité",
    "CLOUD": "Cloud Computing",
    "DEVOPS": "DevOps",
    "RPA": "RPA",
    "GPO": "GPO",
    "BPM": "BPM",
    "WAF": "WAF",
    "VPN": "Réseaux informatiques",
    "DNS": "Réseaux informatiques",
    "DHCP": "Réseaux informatiques",
    "LDAP": "Réseaux informatiques",
    "JSON": "API REST",
    "SOAP": "SOAP/XML Web Services",
    "QA": "Tests automatisés",
    "ISTQB": "Tests automatisés",
    "UAT": "Tests automatisés",
    "PO": "Product Owner",
}


def test_new_it_pm_terms_resolve():
    for term, expected in _NEW_TERMS.items():
        assert normalize_skill(term) == expected, f"{term!r} devrait resoudre a {expected!r}"


def test_moe_is_distinct_from_moa():
    """MOE (maitrise d'oeuvre) et MOA (maitrise d'ouvrage) sont deux roles
    projet opposes -- ne doivent jamais se confondre."""
    assert normalize_skill("moe") == "Maîtrise d'œuvre"
    assert normalize_skill("moa") == "Maîtrise d'ouvrage"


def test_no_false_positive_on_ordinary_french_sentences():
    """Aucun des termes courts retenus (bi, po, cloud, erp...) n'est un mot
    du francais courant -- contrairement a "c"/"son", deja exclus."""
    assert find_skills("Le poste est situe a Paris, il faut etre disponible et motive.") == []
    assert find_skills("Nous avons prepare une bonne recette de cuisine ce week-end en famille.") == []
    assert find_skills("Le nuage etait present toute la journee au dessus de la ville.") == []


def test_real_cv_excerpt_detects_expected_terms():
    """Reproduit le type d'extrait qui a motive cet ajout : une liste de
    competences IT en acronymes, comme trouve dans les vrais CV analyses."""
    excerpt = (
        "Environnement technique : ERP SAP, BI, UML, UX/UI, TMA applicative, "
        "SGBD Oracle, VPN, DNS, JSON/SOAP, tests QA ISTQB, methodologie DevOps."
    )
    result = find_skills(excerpt)
    for expected in ("ERP", "Business Intelligence", "UML", "UX/UI Design", "TMA",
                      "SGBD", "Réseaux informatiques", "API REST",
                      "SOAP/XML Web Services", "Tests automatisés", "DevOps"):
        assert expected in result, f"{expected!r} absent de {result!r}"
