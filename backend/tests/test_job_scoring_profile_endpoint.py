"""Tests : PATCH /job-documents/{id}/scoring-profile.

Contexte : demande explicite (2026-09-14) de laisser un recruteur choisir,
par offre, parmi un jeu FERME de profils de ponderation pre-calibres
("equilibre" / "priorite_experience" / "priorite_mots_cles") -- pas des
poids libres, pour eviter de recreer le risque qui a fait retirer l'ancien
endpoint /feedback/apply-weights (poids non valides appliques en prod)."""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base, CvDocument, ExtractedText, JobDocument, MatchResult
from app.schemas import JobScoringProfileUpdate
from app.services.matcher import match_cv_to_job
import app.main as app_main


@pytest.fixture
def session_factory(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[
            CvDocument.__table__,
            JobDocument.__table__,
            MatchResult.__table__,
            ExtractedText.__table__,
        ],
    )
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(app_main, "SessionLocal", factory)
    monkeypatch.setattr(app_main, "_on_watch_event", lambda event: None)
    return factory


def _seed_job(factory, tmp_path) -> int:
    job_path = tmp_path / "offre.docx"
    job_path.write_text("Offre")
    with factory() as session:
        job = JobDocument(path=str(job_path), status="ready", session_id=None)
        session.add(job)
        session.commit()
        return job.id


def test_patch_saves_a_valid_profile(session_factory, tmp_path):
    job_id = _seed_job(session_factory, tmp_path)
    result = app_main.update_job_scoring_profile(
        job_id, JobScoringProfileUpdate(profile="priorite_experience")
    )
    assert result.scoring_profile == "priorite_experience"

    with session_factory() as session:
        refreshed = session.get(JobDocument, job_id)
        assert refreshed.scoring_profile == "priorite_experience"


def test_patch_rejects_an_unknown_profile_name(session_factory, tmp_path):
    from fastapi import HTTPException

    job_id = _seed_job(session_factory, tmp_path)
    with pytest.raises(HTTPException) as exc_info:
        app_main.update_job_scoring_profile(
            job_id, JobScoringProfileUpdate(profile="agressif")
        )
    assert exc_info.value.status_code == 422


def test_patch_none_resets_to_the_platform_default(session_factory, tmp_path):
    job_id = _seed_job(session_factory, tmp_path)
    app_main.update_job_scoring_profile(job_id, JobScoringProfileUpdate(profile="priorite_mots_cles"))
    result = app_main.update_job_scoring_profile(job_id, JobScoringProfileUpdate(profile=None))
    assert result.scoring_profile is None


def test_unknown_job_returns_404(session_factory, tmp_path):
    from fastapi import HTTPException

    _seed_job(session_factory, tmp_path)
    with pytest.raises(HTTPException) as exc_info:
        app_main.update_job_scoring_profile(999, JobScoringProfileUpdate(profile="equilibre"))
    assert exc_info.value.status_code == 404


def test_priorite_experience_profile_shifts_the_php_job_tie_toward_the_senior():
    """Regression reelle (offre PHP/Laravel/VueJS, 5 ans requis, 2026-09-11) :
    sous le profil par defaut, un junior (3 ans, plus de mots-cles) et un
    senior (8 ans, meme stack en mission reelle) finissaient exactement a
    egalite. Le profil priorite_experience doit casser cette egalite en
    faveur du senior."""
    job_text = (
        "Développeur Full Stack PHP, Laravel, VueJS.\n"
        "Le prestataire devra proposer un profil senior justifiant d'au "
        "moins 5 ans d'expérience.\n"
        "Compétences requises : PHP, Laravel, Vue.js, Back-office, SQL "
        "Server, SQL, Jira, Git, Frontend, ORM, API REST, HTML/CSS, "
        "Responsive design."
    )
    junior_cv = (
        "Consultant développeur fullstack PHP, Laravel et Vue.js.\n"
        "PHP (Laravel, Symfony), HTML, CSS, Vue.js, MySQL, SQL Server, Git.\n"
        "Environ 3 ans d'expérience professionnelle."
    )
    senior_cv = (
        "Développeur Sénior PHP / Symfony / Laravel / Vue.js / Angular, "
        "8 ans d'expérience.\n"
        "API REST, backoffice Sonata Admin, responsive design, Git, Jira."
    )

    junior_default = match_cv_to_job(junior_cv, job_text)
    senior_default = match_cv_to_job(senior_cv, job_text)
    junior_boosted = match_cv_to_job(junior_cv, job_text, scoring_profile="priorite_experience")
    senior_boosted = match_cv_to_job(senior_cv, job_text, scoring_profile="priorite_experience")

    gap_default = senior_default.score - junior_default.score
    gap_boosted = senior_boosted.score - junior_boosted.score
    assert gap_boosted > gap_default, (
        "priorite_experience doit creuser l'ecart en faveur du senior par "
        f"rapport au profil par defaut -- ecart defaut={gap_default} "
        f"ecart priorite_experience={gap_boosted}"
    )
