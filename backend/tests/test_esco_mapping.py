"""Tests unitaires pour esco_taxonomy.py / structured._esco_enrich, isoles
des dependances ML reelles (sentence-transformers, faiss).

Contexte : avant ce fichier, le mapping ESCO n'avait aucune couverture de
test directe -- seul le score de matching final CV<->offre etait teste,
jamais la separation "a-t-on bien detecte la competence dans le texte"
(taxonomy.py::find_skills, deja teste ailleurs) vs "l'a-t-on bien reliee au
bon concept ESCO" (esco_taxonomy.py). Methodologie inspiree de Nesta
ojd_daps_skills, qui evalue separement son etape d'extraction et son etape
de mapping taxonomique plutot que seulement le resultat de bout en bout.

Comme l'index FAISS reel et le modele d'embeddings ne sont pas disponibles
en environnement de test, ce fichier teste isolement :
  1. Le chargement/parsing des CSV ESCO (_load_csv).
  2. Le raccourci de match exact (ne touche jamais faiss/model).
  3. Le degrade gracieux quand l'index n'est pas construit.
  4. Le seuil/tri de l'algorithme de mapping semantique, via un faux index
     FAISS + faux modele deterministes (pas de reseau, pas de vrai modele).
  5. get_esco_index() : absence/invalidite de AI_REALTIME_ESCO_DIR.
  6. structured._esco_enrich() : dedup, plafond, degrade gracieux.
"""
from __future__ import annotations

import csv
from pathlib import Path

import pytest

from app.services import esco_taxonomy, structured
from app.services.esco_taxonomy import EscoIndex, EscoSkill, get_esco_index


@pytest.fixture(autouse=True)
def _reset_esco_singleton(monkeypatch):
    """get_esco_index() cache son resultat dans un global de module, non
    reinitialise par le fixture settings de conftest -- sans ca, le premier
    test qui construit un index le laisserait fuiter vers les suivants."""
    monkeypatch.setattr(esco_taxonomy, "_index_singleton", None)


def _write_skills_csv(path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["conceptUri", "preferredLabel", "altLabels", "description"])
        writer.writeheader()
        writer.writerow({
            "conceptUri": "http://data.europa.eu/esco/skill/python",
            "preferredLabel": "Python",
            "altLabels": "python\npython3",
            "description": "un langage de programmation",
        })
        writer.writerow({
            "conceptUri": "http://data.europa.eu/esco/skill/gestion-projet",
            "preferredLabel": "gestion de projet",
            "altLabels": "",
            "description": "",
        })


def test_load_csv_parses_labels_and_alt_labels(tmp_path):
    _write_skills_csv(tmp_path / "skills_fr.csv")
    idx = EscoIndex(tmp_path, "unused-model-name")
    idx._load_csv()

    assert len(idx.skills) == 2
    assert idx.label_to_skill["python"].preferred_label == "Python"
    assert idx.label_to_skill["python3"].preferred_label == "Python"
    assert idx.label_to_skill["gestion de projet"].preferred_label == "gestion de projet"


def test_find_skills_exact_alias_match_short_circuits(tmp_path):
    """Un alias exact doit renvoyer un score de 1.0 sans jamais toucher a
    faiss/model (qui restent None ici -- _build_index() n'a pas ete appele)."""
    _write_skills_csv(tmp_path / "skills_fr.csv")
    idx = EscoIndex(tmp_path, "unused-model-name")
    idx._load_csv()

    result = idx.find_skills("Python")
    assert len(result) == 1
    skill, score = result[0]
    assert skill.preferred_label == "Python"
    assert score == 1.0


def test_find_skills_returns_empty_when_index_not_built(tmp_path):
    """Pas de match exact, et faiss/model absents -> degrade gracieusement
    (liste vide), jamais d'exception."""
    _write_skills_csv(tmp_path / "skills_fr.csv")
    idx = EscoIndex(tmp_path, "unused-model-name")
    idx._load_csv()

    assert idx.find_skills("une phrase totalement inconnue") == []


class _FakeModel:
    def encode(self, texts, normalize_embeddings=True):
        return [[0.0]]  # contenu sans importance, le faux faiss l'ignore


class _FakeFaiss:
    """Renvoie 3 candidats a scores fixes, quel que soit le vecteur d'entree."""

    def search(self, vec, top_k):
        return ([[0.9, 0.6, 0.3]], [[0, 1, 2]])


def _build_fake_semantic_index() -> EscoIndex:
    idx = EscoIndex(Path("/unused"), "unused-model-name")
    idx.skills = [
        EscoSkill(uri="uri-0", preferred_label="Skill zero", alt_labels=[], description=""),
        EscoSkill(uri="uri-1", preferred_label="Skill one", alt_labels=[], description=""),
        EscoSkill(uri="uri-2", preferred_label="Skill two", alt_labels=[], description=""),
    ]
    idx.label_to_skill = {}  # aucun alias exact -> force le chemin semantique
    idx._model = _FakeModel()
    idx._faiss = _FakeFaiss()
    return idx


def test_find_skills_applies_explicit_min_score_threshold():
    idx = _build_fake_semantic_index()
    result = idx.find_skills("une requete", min_score=0.5)
    assert [s.uri for s, _ in result] == ["uri-0", "uri-1"]
    assert [round(score, 2) for _, score in result] == [0.9, 0.6]


def test_find_skills_falls_back_to_settings_esco_min_score(settings, monkeypatch):
    """Sans min_score explicite, doit lire settings.esco_min_score (le seuil
    externalise dans le chantier precedent) plutot qu'une constante figee."""
    idx = _build_fake_semantic_index()

    monkeypatch.setattr(settings, "esco_min_score", 0.95)
    assert idx.find_skills("une requete") == []

    monkeypatch.setattr(settings, "esco_min_score", 0.7)
    result = idx.find_skills("une requete")
    assert [s.uri for s, _ in result] == ["uri-0"]


def test_get_esco_index_returns_none_without_esco_dir(settings, monkeypatch):
    monkeypatch.setattr(settings, "esco_dir", "")
    assert get_esco_index() is None


def test_get_esco_index_returns_none_for_missing_dir(settings, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "esco_dir", str(tmp_path / "does-not-exist"))
    assert get_esco_index() is None


# ── structured._esco_enrich ──────────────────────────────────────────────

def test_esco_enrich_dedupes_and_caps_at_max_uris(monkeypatch):
    monkeypatch.setattr(structured.settings, "esco_enrich_max_uris", 2)

    def fake_find_skills_esco(term, top_k=1):
        # "python" et "py" pointent vers la meme URI -> doit deduper.
        mapping = {
            "python": [(EscoSkill("uri-python", "Python", [], ""), 0.9)],
            "py": [(EscoSkill("uri-python", "Python", [], ""), 0.85)],
            "docker": [(EscoSkill("uri-docker", "Docker", [], ""), 0.8)],
            "kubernetes": [(EscoSkill("uri-k8s", "Kubernetes", [], ""), 0.75)],
        }
        return mapping.get(term, [])

    monkeypatch.setattr(esco_taxonomy, "find_skills_esco", fake_find_skills_esco)

    uris = structured._esco_enrich(["python", "py", "docker", "kubernetes"])
    assert uris == ["uri-python", "uri-docker"], (
        "doit deduper 'python'/'py' vers la meme URI et s'arreter au plafond "
        "esco_enrich_max_uris=2 avant 'kubernetes'"
    )


def test_esco_enrich_returns_empty_on_lookup_failure(monkeypatch):
    def raising_find_skills_esco(term, top_k=1):
        raise RuntimeError("modele indisponible")

    monkeypatch.setattr(esco_taxonomy, "find_skills_esco", raising_find_skills_esco)

    assert structured._esco_enrich(["python", "docker"]) == []


def test_esco_enrich_returns_empty_for_no_skill_terms():
    assert structured._esco_enrich([]) == []


def _counter_value(outcome: str) -> float:
    from app.observability import ESCO_ENRICH_TERMS_TOTAL

    return ESCO_ENRICH_TERMS_TOTAL.labels(outcome=outcome)._value.get()


def test_esco_enrich_records_mapped_and_unmapped_metrics(monkeypatch):
    """Chaque terme doit incrementer exactement un des compteurs
    mapped/unmapped -- c'est ce qui permet de detecter une derive de
    couverture ESCO au lieu d'un echec silencieux (voir _esco_enrich)."""
    def fake_find_skills_esco(term, top_k=1):
        if term == "python":
            return [(EscoSkill("uri-python", "Python", [], ""), 0.9)]
        return []  # rien au-dessus du seuil

    monkeypatch.setattr(esco_taxonomy, "find_skills_esco", fake_find_skills_esco)

    before_mapped = _counter_value("mapped")
    before_unmapped = _counter_value("unmapped")

    structured._esco_enrich(["python", "un-terme-jamais-mappe"])

    assert _counter_value("mapped") == before_mapped + 1
    assert _counter_value("unmapped") == before_unmapped + 1


def test_esco_enrich_records_error_metric_on_lookup_failure(monkeypatch):
    def raising_find_skills_esco(term, top_k=1):
        raise RuntimeError("modele indisponible")

    monkeypatch.setattr(esco_taxonomy, "find_skills_esco", raising_find_skills_esco)

    before_error = _counter_value("error")
    structured._esco_enrich(["python", "docker"])
    assert _counter_value("error") == before_error + 2
