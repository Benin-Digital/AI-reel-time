"""Tests de non-regression : dissociation des competences fusionnees (F2).

Plusieurs entrees de la taxonomie ecrasaient des produits/technologies
DISTINCTS sous un meme nom canonique via des alias trop larges. Exemple
prouve sur un CV reel (ingenieur BI) : SSIS, SSAS et SSRS — trois outils
Microsoft BI distincts (ETL / cube OLAP / reporting) — etaient tous des
alias de "SQL Server", donc fondus en une seule ligne generique, faisant
disparaitre les competences les plus caracteristiques du profil.

Ces entrees ont ete separees en competences distinctes. Ce test verifie
que chaque outil dissocie est desormais detecte pour lui-meme, et que
l'entree generique d'origine ne les capture plus.
"""
from __future__ import annotations

from app.services.taxonomy import find_skills


def test_ssis_ssas_ssrs_are_distinct_from_sql_server():
    """Les 3 outils BI doivent etre detectes separement, pas fondus dans
    'SQL Server'."""
    result = find_skills("Microsoft BI : SSIS, SSAS, SSRS")
    assert "SSIS" in result
    assert "SSAS" in result
    assert "SSRS" in result


def test_sql_server_alone_does_not_yield_bi_tools():
    """'SQL Server' seul ne doit plus faussement produire SSIS/SSAS/SSRS."""
    result = find_skills("Administration MS SQL Server")
    assert "SSIS" not in result
    assert "SSAS" not in result
    assert "SSRS" not in result
    assert "SQL Server" in result


def test_microservices_distinct_from_api_rest():
    assert "Microservices" in find_skills("architecture microservices")
    # "API REST" seule ne doit plus produire "Microservices"
    assert "Microservices" not in find_skills("conception d'API REST")


def test_svn_is_not_git():
    """SVN et Git sont deux systemes de versioning differents."""
    assert find_skills("SVN Subversion") == ["SVN"]
    assert "SVN" not in find_skills("Git et GitHub")


def test_dotnet_distinct_from_csharp():
    assert ".NET" in find_skills("developpement asp.net")
    assert ".NET" not in find_skills("langage C# uniquement")


def test_symfony_distinct_from_php():
    assert "Symfony" in find_skills("framework Symfony")
    assert "Symfony" not in find_skills("developpeur PHP")


def test_qlikview_distinct_from_qliksense():
    assert "QlikView" in find_skills("dashboards QlikView")
    assert "QlikView" not in find_skills("rapports Qlik Sense")


def test_monitoring_tools_are_distinct():
    """Les outils precis sortent de l'ombrelle 'Monitoring'."""
    result = find_skills("stack observabilite : Prometheus, Grafana, Datadog")
    assert "Prometheus" in result
    assert "Grafana" in result
    assert "Datadog" in result


def test_confluence_distinct_from_jira():
    assert "Confluence" in find_skills("documentation sur Confluence")
    assert "Confluence" not in find_skills("gestion de tickets Jira")


def test_vba_distinct_from_excel():
    assert "VBA" in find_skills("macros VBA")
    assert "VBA" not in find_skills("maitrise d'Excel")


def test_morchid_bi_profile_regression():
    """Cas reel complet : la section competences d'un ingenieur BI doit
    faire ressortir ses outils BI specifiques (SSIS/SSAS/SSRS) en plus des
    bases de donnees."""
    cv = ("Microsoft BI : SSIS - SSAS - SSRS, Power BI, QlikSense, "
          "MS SQL Server, MySQL, PostgreSQL, Oracle PL/SQL, Snowflake")
    result = find_skills(cv)
    for skill in ("SSIS", "SSAS", "SSRS", "Power BI", "QlikSense", "SQL Server"):
        assert skill in result, f"{skill} manquant dans {result}"
