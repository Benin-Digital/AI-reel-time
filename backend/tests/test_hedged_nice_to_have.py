"""Tests : phrases "bonus" noyees dans le paragraphe requis (job_required).

Regression reelle (offre "Developpeur full stack PHP, Laravel, VueJS -ER",
production, 2026-09-11) : la phrase "Si le candidat possede des competences
ou un interet pour la comptabilite publique, cela constituerait un reel
atout pour notre module d'interfacage comptable." vit au milieu du
paragraphe job_required (aucune sous-rubrique "Atouts"/"Nice to have"
dediee), donc _match_section ne pouvait pas la voir -- "Comptabilite
generale" atterrissait dans required_skill_terms au lieu de
nice_skill_terms, plafonnant injustement le score de tout candidat
developpeur qui ne mentionne pas la comptabilite.
"""
from __future__ import annotations

from app.services.parser import _split_hedged_sentences, parse_document

_JOB_TEXT = (
    "Développeur Full Stack PHP, Laravel, VueJS -ER\n\n"
    "Compétences requises :\n"
    "Vous maitrisez PHP, Laravel, Vue.js, SQL Server et Git. "
    "Vous avez une bonne connaissance des API REST et du responsive design. "
    "Si le candidat possède des compétences ou un intérêt pour la "
    "comptabilité publique, cela constituerait un réel atout pour notre "
    "module d'interfaçage comptable.\n"
)


def test_split_hedged_sentences_moves_only_the_hedged_sentence():
    required = (
        "Vous maitrisez PHP et Laravel. Cela constituerait un réel atout "
        "de connaitre la comptabilité publique. Vous avez une bonne "
        "maitrise de Git."
    )
    kept, hedged = _split_hedged_sentences(required)
    assert "PHP" in kept and "Laravel" in kept and "Git" in kept
    assert "comptabilité" not in kept
    assert "comptabilité" in hedged


def test_split_hedged_sentences_handles_empty_and_no_match():
    assert _split_hedged_sentences("") == ("", "")
    kept, hedged = _split_hedged_sentences("Vous maitrisez PHP et Laravel.")
    assert kept == "Vous maitrisez PHP et Laravel."
    assert hedged == ""


def test_split_hedged_sentences_recognizes_common_hedge_phrasings():
    for sentence in (
        "La connaissance de Java serait un plus.",
        "La connaissance de Java serait un réel atout.",
        "La maitrise de Java représenterait un atout supplémentaire.",
        "Une expérience en Java sera appréciée.",
        "La connaissance de Java est un plus, de préférence récente.",
    ):
        _, hedged = _split_hedged_sentences(sentence)
        assert hedged, f"devrait etre detecte comme optionnel: {sentence!r}"


def test_real_job_offer_hedged_accounting_mention_lands_in_nice_not_required():
    job = parse_document(_JOB_TEXT, kind="job")
    assert "Comptabilité générale" not in job.required_skill_terms
    assert "Comptabilité générale" in job.nice_skill_terms
    # Les vraies exigences ne doivent pas etre affectees par l'extraction.
    for expected in ("PHP", "Laravel"):
        assert expected in job.required_skill_terms


_JOB_TEXT_NO_RECOGNIZED_REQUIRED_HEADING = (
    "Développeur full stack PHP Laravel VueJS -ER\n\n"
    "Le candidat devra montrer un réel intérêt pour la gestion du "
    "programme afin d'appréhender, voire d'anticiper les besoins des "
    "utilisateurs et de les traduire en solutions informatiques.\n"
    "Si le candidat possède des compétences ou un intérêt pour la "
    "comptabilité publique, cela constituerait un réel atout pour notre "
    "module d'interfaçage comptable.\n"
    "Profil requis et compétences attendues\n"
    "La personne apportera une assistance technique en soutien de "
    "l'équipe informatique, avec une solide maitrise de PHP, Laravel et "
    "Vue.js ainsi que de Git.\n"
)


def test_hedged_mention_is_filtered_even_without_a_recognized_required_heading():
    """Regression reelle (offre "Developpeur full stack PHP Laravel VueJS
    -ER", production, 2026-09-11) : aucune ligne de ce document ne
    correspond a un alias job_required connu ("Profil requis et
    competences attendues" ne matche aucun alias enregistre), donc
    job_required_text reste vide et le code retombait sur la liste brute
    de TOUTES les competences detectees -- en contournant completement le
    filtrage des phrases "atout" qui ne s'appliquait qu'a job_required_text."""
    job = parse_document(_JOB_TEXT_NO_RECOGNIZED_REQUIRED_HEADING, kind="job")
    assert "Comptabilité générale" not in job.required_skill_terms
    assert "Comptabilité générale" in job.nice_skill_terms
    for expected in ("PHP", "Laravel", "Git"):
        assert expected in job.required_skill_terms
