"""Tests de non-regression pour la tokenisation de taxonomy.find_skills().

Bug F1 (trouve en analysant des CV reels) : la regex de tokenisation
[a-z0-9#+.]+ incluait le point, donc un mot en fin de phrase ou d'item de
liste ("Qliksense.", "Python.") devenait un token avec point colle
("qliksense.") absent du lookup — la competence etait silencieusement
manquee. Le point doit rester A L'INTERIEUR des tokens (node.js, vue.js)
mais etre retire en bordure.
"""
from __future__ import annotations

from app.services.taxonomy import find_skills


def test_skill_at_end_of_sentence_is_detected():
    """Une competence suivie d'un point final doit etre detectee."""
    assert "QlikSense" in find_skills("Maitrise de Qliksense.")
    assert "Python" in find_skills("Experience Python.")
    assert "React" in find_skills("Competences React.")


def test_skill_at_end_of_list_item_is_detected():
    """Cas reel (CV Morchid) : 'Power BI, Qliksense.' en fin d'enumeration."""
    result = find_skills("Business Intelligence : Power BI, Qliksense.")
    assert "Power BI" in result
    assert "QlikSense" in result


def test_internal_dot_is_preserved():
    """Le point interne de node.js / vue.js reste significatif : ces
    competences ne doivent pas etre cassees par le strip de bordure."""
    result = find_skills("Stack : Node.js et Vue.js")
    assert "Node.js" in result
    assert "Vue.js" in result


def test_special_char_skills_still_match():
    """C# et C++ (# et +) ne doivent pas etre affectes par le fix."""
    result = find_skills("Developpeur C# et C++")
    assert "C#" in result
    assert "C++" in result


def test_bare_punctuation_and_numbers_do_not_crash_or_false_match():
    """Ponctuation isolee et nombres a decimale ne doivent produire
    aucun faux positif ni erreur."""
    assert find_skills("version 5.") == []
    assert find_skills("3.14 ans") == []
    # Un point isole entre deux competences n'empeche pas leur detection
    assert "Node.js" in find_skills(". Node.js .")
