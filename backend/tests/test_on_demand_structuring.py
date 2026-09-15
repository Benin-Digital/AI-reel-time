"""Tests de non-regression pour la structuration Docling a la demande.

Contexte : Docling (analyse de mise en page + tableaux, modeles de vision
tournant sur CPU) rendait le traitement de documents un peu longs (ex: un
CV de 11 pages) trop lent pour de l'ingestion automatique, causant des 502
nginx. L'extraction automatique est desormais TOUJOURS rapide (PyMuPDF +
OCR plafonne) ; Docling ne tourne plus que sur demande explicite via
POST /{cv,job}-documents/{id}/structure.

Ces tests verifient :
- l'extraction automatique (force_docling=False, valeur par defaut) n'appelle
  jamais Docling, meme si un cache Docling existe deja pour ce fichier ;
- force_docling=True declenche bien Docling, sauf si le cache est deja une
  extraction Docling du meme contenu (pas de re-travail inutile) ;
- le changement de methode d'extraction invalide le profil structure mis en
  cache, meme si le hash de contenu (le fichier) n'a pas change ;
- _structure_document met a jour structuring_status et relance le scoring
  seulement en cas de succes.
"""
from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base, CvDocument, ExtractedText, JobDocument, MatchResult
import app.main as app_main
import app.services.conversion as conversion


@pytest.fixture
def session_factory(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[
            CvDocument.__table__,
            JobDocument.__table__,
            ExtractedText.__table__,
            MatchResult.__table__,
        ],
    )
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(app_main, "SessionLocal", factory)
    return factory


@pytest.fixture
def cv_file(tmp_path):
    path = tmp_path / "cv.txt"
    path.write_text("Développeur Python, 5 ans d'expérience. Compétences : Python, Django.")
    return path


def test_default_extraction_never_calls_docling(cv_file, monkeypatch, session_factory):
    def _boom(path):
        raise AssertionError("Docling must not run for the default (auto-ingest) extraction path")

    monkeypatch.setattr(conversion, "convert_document", _boom)

    result = app_main._extract_and_persist(cv_file)

    assert result.extraction_success
    assert result.extraction_method != "docling"


def test_cached_docling_result_is_reused_without_setting(cv_file, monkeypatch, session_factory):
    calls = {"n": 0}

    def _fake_convert(path):
        calls["n"] += 1
        from app.services.conversion import ConvertedDocument
        return ConvertedDocument(full_text="structured text", sections={"skills": "Python"})

    monkeypatch.setattr(conversion, "convert_document", _fake_convert)

    first = app_main._extract_and_persist(cv_file, force_docling=True)
    assert first.extraction_method == "docling"
    assert calls["n"] == 1

    # Auto-ingest call (force_docling=False) on the same unchanged file must
    # reuse the cached Docling extraction, not silently downgrade it.
    second = app_main._extract_and_persist(cv_file)
    assert second.extraction_method == "docling"
    assert second.extracted_text == "structured text"
    assert calls["n"] == 1, "no re-extraction should happen on an unchanged, already-cached file"

    # A second forced structuring request on unchanged content must not
    # re-run Docling either.
    third = app_main._extract_and_persist(cv_file, force_docling=True)
    assert calls["n"] == 1


def test_force_recompute_never_downgrades_an_already_docling_extraction(cv_file, monkeypatch, session_factory):
    """POST /matches/recompute calls _extract_and_persist(path, force=True) on
    every active document to refresh scoring against whatever extraction
    code is deployed -- content-hash cache bypassed on purpose. Reproduces a
    real production bug: a recruiter ran "Structurer (approfondi)" (Docling)
    on several CVs, then a later recompute silently re-ran the fast
    plain-text path over the SAME unchanged files and clobbered the Docling
    text back to the lower-fidelity version, discarding the recruiter's
    explicit request with no error or warning."""
    calls = {"n": 0}

    def _fake_convert(path):
        calls["n"] += 1
        from app.services.conversion import ConvertedDocument
        return ConvertedDocument(full_text="richer structured text", sections={"skills": "Python"})

    monkeypatch.setattr(conversion, "convert_document", _fake_convert)

    structured = app_main._extract_and_persist(cv_file, force_docling=True)
    assert structured.extraction_method == "docling"
    assert calls["n"] == 1

    # force=True, force_docling=False (exactly what /matches/recompute does)
    # on the same unchanged file must NOT revert to the fast plain-text path.
    recomputed = app_main._extract_and_persist(cv_file, force=True)
    assert recomputed.extraction_method == "docling", (
        "force=True must re-run Docling (not the fast path) when the cached "
        "extraction for this unchanged content was already a Docling one"
    )
    assert recomputed.extracted_text == "richer structured text"
    assert calls["n"] == 2, "force=True should still re-run extraction (fresh code), just via Docling"


def test_forcing_docling_over_a_plain_text_cache_invalidates_parsed_profile(cv_file, monkeypatch, session_factory):
    # First, a normal fast extraction (simulates automatic ingestion).
    plain = app_main._extract_and_persist(cv_file)
    assert plain.extraction_method != "docling"

    with session_factory() as session:
        row = session.query(ExtractedText).filter_by(file_path=str(cv_file)).one()
        row.parsed_profile = {"full_name": "stale"}
        row.parsed_profile_hash = row.content_hash
        session.commit()

    def _fake_convert(path):
        from app.services.conversion import ConvertedDocument
        return ConvertedDocument(full_text="richer structured text", sections={})

    monkeypatch.setattr(conversion, "convert_document", _fake_convert)

    app_main._extract_and_persist(cv_file, force_docling=True)

    with session_factory() as session:
        row = session.query(ExtractedText).filter_by(file_path=str(cv_file)).one()
        assert row.extraction_method == "docling"
        assert row.extracted_text == "richer structured text"
        # Regression reelle (2026-09-15) : invalider le profil perime ne
        # suffit pas -- s'il n'est jamais RECONSTRUIT dans la foulee, il
        # reste a None indefiniment (rien d'autre ne le regenere pour un
        # document deja connu), et le nom du candidat/titre de poste
        # disparait de partout ou le cache est lu (voir cv_label/job_label,
        # routers/matches.py) jusqu'a une action manuelle non garantie.
        assert row.parsed_profile is not None, (
            "le profil perime doit etre RECONSTRUIT avec le nouveau texte "
            "extrait, pas seulement invalide puis laisse a None"
        )
        assert row.parsed_profile != {"full_name": "stale"}
        assert row.parsed_profile_hash == row.content_hash


def test_force_true_invalidates_parsed_profile_even_when_content_and_method_are_unchanged(
    cv_file, monkeypatch, session_factory
):
    """Regression reelle (2026-09-11) : POST /matches/recompute et le
    "rescore" par document existent specifiquement pour qu'un fix de
    parser.py/taxonomy.py prenne effet sur des documents deja ingeres,
    sans re-upload. Mais _upsert_extraction_result n'invalidait
    parsed_profile que si content_hash OU extraction_method changeait --
    ce qui n'est JAMAIS le cas pour un simple deploi de code sur un
    fichier deja present. Un vrai fix (filtrage des mentions "atout" dans
    parser.py) restait donc sans aucun effet sur une offre deja ingeree
    meme apres un rescore force, tant que le contenu du fichier lui-meme
    n'avait pas change."""
    app_main._extract_and_persist(cv_file)

    with session_factory() as session:
        row = session.query(ExtractedText).filter_by(file_path=str(cv_file)).one()
        row.parsed_profile = {"full_name": "stale"}
        row.parsed_profile_hash = row.content_hash
        session.commit()

    app_main._extract_and_persist(cv_file, force=True)

    with session_factory() as session:
        row = session.query(ExtractedText).filter_by(file_path=str(cv_file)).one()
        # Une simple inegalite a l'ancienne valeur perimee ne suffit pas a
        # prouver une reconstruction : None satisfait aussi "!= stale" (voir
        # la regression reelle du 2026-09-15 -- ce test passait deja avec le
        # bug present, puisque le profil restait bloque a None au lieu
        # d'etre reconstruit).
        assert row.parsed_profile is not None, (
            "force=True doit RECONSTRUIRE le profil structure, pas "
            "seulement l'invalider et le laisser a None"
        )
        assert row.parsed_profile != {"full_name": "stale"}, (
            "force=True doit reconstruire le profil structure avec le code "
            "actuel meme quand le contenu et la methode d'extraction "
            "n'ont pas change"
        )


def test_candidate_name_survives_a_forced_rescore(tmp_path, monkeypatch, session_factory):
    """Bout-en-bout, avec le vrai symptome signale en direct par
    l'utilisateur (2026-09-15) : "avant je voyais le nom des candidats,
    maintenant je vois le nom du fichier". Chaque recalcul force (un
    changement de profil de ponderation ou de mots-cles prioritaires,
    POST /matches/recompute, "Relancer l'IA") invalide parsed_profile pour
    CHAQUE CV actif matche contre l'offre concernee -- sans reconstruction
    automatique, person_name (et donc cv_label dans la liste des
    correspondances) disparaissait purement et simplement pour tous les
    CV touches par un recalcul force, jusqu'a une action manuelle."""
    cv_path = tmp_path / "cv.txt"
    cv_path.write_text("Jean DUPONT\nDéveloppeur Python, 5 ans d'expérience. Compétences : Python, Django.")

    app_main._extract_and_persist(cv_path)

    with session_factory() as session:
        row = session.query(ExtractedText).filter_by(file_path=str(cv_path)).one()
        assert row.parsed_profile is not None
        name_before = row.parsed_profile.get("person_name")
    assert name_before, "le nom doit etre detecte des la premiere extraction"

    # Same forced rescore every job-side save (scoring profile, priority
    # keywords) or /matches/recompute triggers for every active CV matched
    # against that job.
    app_main._extract_and_persist(cv_path, force=True)

    with session_factory() as session:
        row = session.query(ExtractedText).filter_by(file_path=str(cv_path)).one()
        assert row.parsed_profile is not None
        assert row.parsed_profile.get("person_name") == name_before, (
            "le nom du candidat doit survivre a un recalcul force, pas "
            "disparaitre (repli sur le nom de fichier cote frontend)"
        )


def test_structure_document_marks_ready_and_rescopes_on_success(cv_file, monkeypatch, session_factory):
    with session_factory() as session:
        doc = CvDocument(path=str(cv_file), status="ready")
        session.add(doc)
        session.commit()

    def _fake_convert(path):
        from app.services.conversion import ConvertedDocument
        return ConvertedDocument(full_text="structured text", sections={})

    monkeypatch.setattr(conversion, "convert_document", _fake_convert)

    rescored = {"called": False}
    monkeypatch.setattr(app_main, "_score_against_counterparts", lambda path, role: rescored.__setitem__("called", True))

    app_main._structure_document(cv_file, "cv")

    with session_factory() as session:
        doc = session.query(CvDocument).filter_by(path=str(cv_file)).one()
        assert doc.structuring_status == "ready"
        assert doc.structuring_error is None
    assert rescored["called"] is True


def test_structure_document_marks_failed_without_rescoring(tmp_path, monkeypatch, session_factory):
    missing_path = tmp_path / "missing.txt"  # file does not exist -> extraction fails

    with session_factory() as session:
        doc = CvDocument(path=str(missing_path), status="ready")
        session.add(doc)
        session.commit()

    rescored = {"called": False}
    monkeypatch.setattr(app_main, "_score_against_counterparts", lambda path, role: rescored.__setitem__("called", True))

    app_main._structure_document(missing_path, "cv")

    with session_factory() as session:
        doc = session.query(CvDocument).filter_by(path=str(missing_path)).one()
        assert doc.structuring_status == "failed"
        assert doc.structuring_error
    assert rescored["called"] is False
