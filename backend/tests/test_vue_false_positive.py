"""Test : le mot francais "vue" ne doit pas matcher "Vue.js" (F11).

L'alias "vue" (mot francais tres courant : "point de vue", "en vue de",
"revue") declenchait un faux positif "Vue.js". Retire ; les formes
specifiques (vue.js, vuejs, vue js, vuex, pinia) restent detectees.
"""
from __future__ import annotations

from app.services.taxonomy import find_skills


def test_french_word_vue_is_not_vuejs():
    assert find_skills("point de vue") == []
    assert find_skills("en vue des sprints") == []
    assert find_skills("revue de code") == []


def test_real_vuejs_still_detected():
    assert "Vue.js" in find_skills("developpeur vue.js")
    assert "Vue.js" in find_skills("vuejs et react")
    assert "Vue.js" in find_skills("stack : vue js, pinia")
