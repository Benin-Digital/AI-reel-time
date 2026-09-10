"""Tests de non-regression pour le moteur de matching v2 (matcher.py).

Contexte : un test manuel en production a revele qu'un meme document,
depose une fois comme CV et une fois comme Offre, ne se matche qu'a 15%
avec lui-meme au lieu d'un score quasi parfait.

Root cause (voir parser.py::parse_document) : l'extraction des competences
depend du kind ('cv' vs 'job') de maniere asymetrique. Pour un document dont
le contenu utile est classe dans la section 'job_required' (ex: un document
structure comme une offre d'emploi, avec des rubriques "Competences requises",
"Missions principales"), ce contenu est inclus dans skill_src cote 'job' mais
explicitement exclu cote 'cv'. Resultat : la couverture de competences (et,
en cascade, la representation semantique) peut s'effondrer a 0% meme quand
les deux textes compares sont strictement identiques.

Ces tests documentent le comportement attendu (score eleve sur un self-match)
et echouent tant que ce bug n'est pas corrige.
"""
from __future__ import annotations

from app.services import matcher, parser
from app.services.matcher import match_cv_to_job

# Texte reproduisant fidelement la structure d'un vrai document ayant declenche
# le bug en production : rubriques "Missions principales", "Competences
# requises", "Qualites requises" typiques d'une offre d'emploi.
JOB_SHAPED_TEXT = """
Avis de recrutement N : 010/2026/ACME
Titre du Poste : Responsable Technique et Maintenance
Employeur : ACME Infrastructures SA
Superieur hierarchique : Directeur du Pole Exploitation et Maintenance
Relation fonctionnelle : Collegues de la direction, Collaborateurs de la societe.
Lieu d affectation : Cotonou - BENIN

Mission du Poste
Sous l autorite du Directeur, le/la Responsable Technique et Maintenance est
charge(e) d assurer la disponibilite, la fiabilite et le bon fonctionnement
des equipements et installations techniques.
Ses missions principales sont :
- Organiser, coordonner et superviser les activites de maintenance preventive
  et corrective des equipements et installations ;
- Veiller a la disponibilite et au bon fonctionnement des equipements
  techniques et le suivi des incidents et pannes ;
- Elaborer et mettre en oeuvre les programmes de maintenance ;
- Superviser les interventions des prestataires et controler la qualite des
  prestations realisees ;
- Assurer le suivi des stocks de pieces de rechange et anticiper les besoins
  d approvisionnement ;
- Encadrer et coordonner les techniciens de maintenance et veiller a une
  bonne repartition des activites ;
- Analyser les dysfonctionnements recurrents et proposer des actions
  d amelioration perennes ;
- Participer aux projets de modernisation et d evolution des systemes et
  des equipements ;
- Produire les rapports periodiques sur l etat des equipements, les
  interventions realisees et les indicateurs de performance ;
- Accomplir toute autre tache confiee par la hierarchie.

Profil du poste
Formation requise
- Etre titulaire d un Diplome Bac +4 minimum ou d ingenieur en genie
  electrique, electrotechnique, automatisme, maintenance industrielle,
  informatique industrielle ou domaine equivalent.
- Formation complementaire en maintenance industrielle ou en gestion de la
  maintenance constituerait un atout important.
Experiences professionnelles
- Minimum cinq (05) ans d experience dans la maintenance technique,
  industrielle ou dans l exploitation d infrastructures techniques ;
- Une experience dans les infrastructures routieres, systemes automatises
  ou postes techniques constitue un atout ;
- Une experience en gestion d equipe technique serait appreciee.
Competences requises
- Bonne connaissance des equipements techniques et des systemes associes ;
- Maitrise des domaines techniques lies a l automatisme, l electronique,
  l electrotechnique ou l informatique industrielle ;
- Capacite a organiser et coordonner les activites de maintenance ;
- Maitrise des outils de suivi et de gestion de maintenance (GMAO) ;
- Capacite a diagnostiquer les dysfonctionnements et proposer des solutions
  adaptees ;
- Capacite a gerer les prestataires et coordonner les interventions
  techniques.
Qualites requises
- Rigueur et sens de l organisation ;
- Esprit d analyse et de resolution des problemes ;
- Reactivite et sens des priorites ;
- Sens des responsabilites et prise d initiative ;
- Aisance relationnelle et aptitude a travailler en equipe ;
- Capacite a travailler sous pression et a gerer les situations d urgence.
""".strip()


def test_self_match_skill_coverage_is_full(monkeypatch):
    """Un document compare a lui-meme doit avoir une couverture de
    competences quasi totale (~1.0), quel que soit l'endroit ou son contenu
    a ete classe (job_required, skills, experience...).

    Echoue aujourd'hui : score_skills tombe a 0.0 des que le contenu
    pertinent est classe en 'job_required', car parse_document() exclut ce
    champ du skill_src quand kind='cv'.
    """
    result = match_cv_to_job(JOB_SHAPED_TEXT, JOB_SHAPED_TEXT)
    assert result.score_skills >= 0.9, (
        f"couverture de competences attendue ~1.0 sur un self-match, "
        f"obtenu {result.score_skills} — cv/job divergent sur un texte identique"
    )


def test_weights_are_domain_independent():
    """Le score ne doit plus etre pondere differemment selon le domaine
    detecte (retire en production : detect_domain() est une heuristique par
    mots-cles sur les 3000 premiers caracteres, et un mot isole hors
    contexte — ex. "patient" dans un CV tech e-sante — pouvait faire basculer
    tout le profil de poids sans aucun signal visible pour le recruteur,
    faussant silencieusement le classement).

    _weights() ne doit plus varier avec le domaine : c'est toujours
    _DEFAULT_W (sauf poids appris explicitement actives, hors du perimetre
    ici). _DOMAIN_W reste dans le code comme reference historique mais n'est
    plus consulte par _weights().
    """
    assert matcher._weights() == matcher._DEFAULT_W
    assert matcher.get_active_weights() is None, (
        "aucun poids appris ne doit etre actif par defaut dans les tests"
    )


def test_self_match_weights_do_not_depend_on_detected_domain(monkeypatch):
    """Bout en bout : deux documents identiques donnent le meme profil de
    poids quel que soit le domaine qui leur est assigne artificiellement."""
    monkeypatch.setattr(matcher, "_cross_encode", lambda query, document: 1.0)
    cv = parser.parse_document(JOB_SHAPED_TEXT, kind="cv")
    job = parser.parse_document(JOB_SHAPED_TEXT, kind="job")

    cv.domain = "health"
    job.domain = "tech"
    result_a = matcher.match_parsed_documents(cv, job)

    cv.domain = "tech"
    job.domain = "tech"
    result_b = matcher.match_parsed_documents(cv, job)

    assert result_a.weights == result_b.weights == matcher._DEFAULT_W


def test_self_match_overall_score_is_high(monkeypatch):
    """Score composite de bout en bout sur un self-match.

    Le score semantique (cross-encoder) est neutralise a 1.0 ici : il depend
    d'un modele ML non disponible en environnement de test, et n'est pas
    l'objet de cette regression. Cette assertion isole donc les bugs
    structurels (couverture de competences + poids de domaine).

    Echoue aujourd'hui (~55% avec le mock) tant que le bug de couverture de
    competences n'est pas corrige.
    """
    monkeypatch.setattr(matcher, "_cross_encode", lambda query, document: 1.0)
    result = match_cv_to_job(JOB_SHAPED_TEXT, JOB_SHAPED_TEXT)
    assert result.score >= 80, (
        f"score self-match attendu >= 80 (semantique neutralisee a 100%), "
        f"obtenu {result.score}"
    )


def test_semantic_representation_is_symmetric_on_self_match():
    """cv_repr et job_repr doivent etre identiques sur un self-match.

    Trouve en production : meme apres correction de skill_src (parser.py),
    match_cv_to_job() choisissait encore un champ different par cote pour
    la comparaison semantique (cv_repr priorisait skills_text, job_repr
    priorisait job_required_text). Sur un document dont le contenu utile
    est classe en job_required (voir JOB_SHAPED_TEXT), ca revenait a
    comparer deux extraits differents du meme document au cross-encoder,
    qui les jugeait peu similaires — un score self-match de 15% (bug
    original) devenu 61% (apres le fix skill_src, avant celui-ci) au lieu
    d'un score proche de 100%.
    """
    cv = parser.parse_document(JOB_SHAPED_TEXT, kind="cv")
    job = parser.parse_document(JOB_SHAPED_TEXT, kind="job")
    assert matcher._semantic_repr(cv) == matcher._semantic_repr(job), (
        "la representation semantique doit etre identique des deux cotes "
        "quand cv_text et job_text sont un texte identique"
    )


def test_self_match_scores_near_perfect_with_realistic_semantic(monkeypatch):
    """Simule un cross-encoder realiste (texte identique = similarite
    parfaite, texte different = similarite nulle) plutot que de neutraliser
    betement le score semantique a 1.0 — pour verifier que le fix de
    symetrie ci-dessus se traduit bien par un score final quasi parfait,
    pas seulement par une egalite de representations en interne."""
    monkeypatch.setattr(
        matcher, "_cross_encode",
        lambda query, document: 1.0 if query == document else 0.0,
    )
    result = match_cv_to_job(JOB_SHAPED_TEXT, JOB_SHAPED_TEXT)
    assert result.score >= 80, (
        f"self-match avec cross-encoder realiste attendu >= 80, obtenu {result.score}"
    )


def test_low_skill_coverage_caps_score_even_with_perfect_semantic(monkeypatch):
    """Trouve en production sur une offre "Data Analyst Expert SAS" : trois
    CV ne recoupant qu'une minorite des competences requises (l'outil nomme
    par l'offre, SAS, absent des trois -- SQL absent de deux d'entre eux)
    ont quand meme obtenu un score de 93%+ ("Fort"), l'explication du match
    admettant elle-meme ces competences comme manquantes. Cause : semantic
    (poids 0.40) et les autres composantes (experience/education/langues/
    contrat, ici toutes favorables) compensaient une couverture de
    competences a ~57%.

    Isole le cas au maximum : semantique forcee a 1.0 (similarite parfaite)
    et toutes les autres composantes forcees a leur valeur la plus
    favorable, pour verifier qu'une couverture de competences a 4/7 ne peut
    plus a elle seule produire un score "Fort".
    """
    monkeypatch.setattr(matcher, "_cross_encode", lambda query, document: 1.0)
    cv = parser.ParsedDocument(
        kind="cv",
        domain="general",
        raw_text="",
        cleaned_text="",
        skill_terms=["Reporting", "Documentation technique", "Service client", "Communication"],
        experience_years=3,
        education_text="Bac+5",
        language_terms=["francais"],
        contract_type="CDI",
    )
    job = parser.ParsedDocument(
        kind="job",
        domain="general",
        raw_text="",
        cleaned_text="",
        required_skill_terms=[
            "SAS (logiciel)", "SQL", "Controle qualite", "Reporting",
            "Documentation technique", "Service client", "Communication",
        ],
        experience_years=3,
        education_text="Bac+5",
        language_terms=["francais"],
        contract_type="CDI",
    )
    result = matcher.match_parsed_documents(cv, job)
    assert result.score_skills < 0.6, "4 competences requises sur 7 recoupees seulement"
    assert result.score < 80, (
        f"couverture de competences a 4/7 meme avec semantique et tout le "
        f"reste parfaits doit rester sous le seuil 'Fort', obtenu {result.score}"
    )
