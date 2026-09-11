"""Jeu de validation base sur des cas REELS (audit manuel du 2026-09-11).

Contexte : test_validation_dataset.py ne couvre que des cas synthetiques
inventes. Tout le calibrage fait le 2026-09-11 (poids semantique 0.40->0.10,
poids experience 0.12->0.20, plancher du plafond competences/mots-cles,
credit semantique sur les mots-cles prioritaires, mecanisme mot-cle-coeur
via le titre...) s'est appuye sur une lecture manuelle ponctuelle de vraies
offres/CV, jamais figee en test -- un futur changement de formule pourrait
defaire silencieusement ce calibrage sans qu'aucun test ne le detecte.

Chaque cas ci-dessous reproduit fidelement (competences, annees
d'experience, structure de l'offre) une paire reelle deja auditee
manuellement cette session-la, avec le jugement humain de reference
explicite. Le texte est condense/anonymise (pas de coordonnees
personnelles, pas de citation integrale du CV) mais conserve tous les
faits qui pilotent le score. Bandes larges (pas de valeurs exactes),
memes raisons que test_validation_dataset.py : le cross-encoder tombe sur
un score neutre 0.5 quand le modele n'est pas disponible (CI).
"""
from __future__ import annotations

from app.services.matcher import match_cv_to_job

# ---------------------------------------------------------------------------
# Cas 1 : offre "5 ans minimum" -- un junior avec le bon stack (3 ans reels)
# contre un senior avec le meme stack en mission reelle (8 ans reels). Un
# recruteur classerait le senior nettement devant : l'ecart d'annees par
# rapport a un seuil EXPLICITE prime sur un mot-cle de difference.
# Regression reelle : avant le recalibrage du poids experience (0.12->0.20),
# ces deux candidats etaient scores a moins d'un point d'ecart (67.53 vs
# 66.93), le junior legerement DEVANT le senior.
# ---------------------------------------------------------------------------
PHP_JOB = """
Développeur Full Stack PHP, Laravel, VueJS.
Le prestataire devra proposer un profil senior, autonome et motivé,
justifiant d'au moins 5 ans d'expérience.
Compétences requises : PHP, Laravel, Vue.js, Back-office, SQL Server, SQL,
Jira, Git, Frontend, ORM, API REST, HTML/CSS, Responsive design.
"""
PHP_JUNIOR_CV = """
Consultant développeur fullstack spécialisé en PHP, Laravel et Vue.js.
Compétences : PHP (Laravel, Symfony), HTML, CSS, Bootstrap, Vue.js, MySQL,
SQL Server, Git, GitHub.
Expérience : alternance puis deux missions courtes en développement PHP
Laravel et Vue.js, environ 3 ans d'expérience professionnelle au total.
"""
PHP_SENIOR_CV = """
Développeur Sénior PHP / Symfony / Laravel / Vue.js / Angular, 8 ans
d'expérience.
Expérience : plusieurs missions longues en Laravel/VueJS et Symfony pour
des grands comptes banque/assurance, développement d'API REST, mise en
place de backoffice (Sonata Admin), responsive design, gestion Git en
équipe, revue de code, Jira.
Compétences : PHP, Symfony, Laravel, VueJS, Angular, Git, Jira, API REST,
HTML/CSS, Responsive design, Back-office.
"""


def test_explicit_years_threshold_ranks_the_senior_clearly_above_the_junior():
    junior = match_cv_to_job(PHP_JUNIOR_CV, PHP_JOB)
    senior = match_cv_to_job(PHP_SENIOR_CV, PHP_JOB)
    assert senior.score > junior.score + 5, (
        "un poste avec un seuil d'annees EXPLICITE (5 ans minimum) doit "
        "classer nettement devant un candidat qui le depasse largement (8 "
        f"ans) face a un candidat tres en dessous (3 ans) -- obtenu junior="
        f"{junior.score} senior={senior.score}"
    )
    assert senior.score_experience == 1.0, (
        "8 ans pour 5 requis (ratio 1.6) est un cas 'legerement superieur' "
        "-- credit plein, pas de penalite de sur-qualification"
    )
    assert junior.score_experience < 0.8, (
        "3 ans pour 5 requis doit rester nettement en dessous du plein credit"
    )


# ---------------------------------------------------------------------------
# Cas 2 : offre dont la liste de mots-cles est tres pointue (taches precises
# de controle qualite data, pas des noms d'outils) -- un excellent candidat
# architecte Data/BI (tres forte couverture de competences generales) ne
# doit pas s'effondrer sous un score mediocre juste parce qu'il ne reprend
# jamais mot pour mot ce vocabulaire tres specifique.
# Regression reelle : avant plusieurs corrections (mecanisme mot-cle-coeur
# sur titre compose, credit semantique sur mots-cles prioritaires), ce
# candidat tombait a 24.75-29.25% malgre une couverture de competences
# generale quasi totale.
# ---------------------------------------------------------------------------
BI_JOB = """
Data Analyst / Concepteur Décisionnel Sénior H/F.
Compétences requises : informatique décisionnelle, architectures BI,
outils ETL (Informatica), analyse des besoins métiers, reporting,
coordination, compliance.
"""
BI_JOB_PRIORITY_KEYWORDS = (
    "Data Analyst\n"
    "Concepteur Décisionnel\n"
    "ETL\nInformatica\nSQL\narchitectures BI\ncontrôle de données\n"
    "qualification d'anomalies\nvalidation des résultats\nflux de données\n"
    "Recette\nTests\nAssurance\nbesoins métiers"
)
BI_EXPERT_CV = """
Chef de Projet Technique Data Architect - Expert BI, 25 ans d'expérience.
Pilotage et gestion de projet Data, coordination transverse, analyse des
besoins métiers. Intégration de données : expertise Informatica
(PowerCenter, IDMC), formateur Informatica. Reporting opérationnel et
règlementaire, compliance et assurance qualité. Business Intelligence,
planification, ETL, SQL. Architecture applicative et technique pour de
grands comptes (banque, assurance).
"""


def test_expert_profile_does_not_collapse_under_a_hyper_specific_keyword_list():
    result = match_cv_to_job(
        BI_EXPERT_CV, BI_JOB, priority_keywords=BI_JOB_PRIORITY_KEYWORDS
    )
    assert result.score_skills >= 0.85, (
        "couverture generale des competences quasi totale pour ce profil"
    )
    assert result.score >= 55, (
        "un expert avec une couverture generale quasi totale ne doit pas "
        f"s'effondrer sous 55% juste par manque de formulation exacte des "
        f"mots-cles prioritaires -- obtenu {result.score}"
    )


# ---------------------------------------------------------------------------
# Cas 3 : offre avec mots-cles prioritaires bien alignes avec le profil --
# cas de reference "tout va bien", pour detecter une regression qui
# affaiblirait le signal positif des mots-cles sur un cas simple.
# ---------------------------------------------------------------------------
GOVERNANCE_JOB = """
Consultant Chef de Projet Gouvernance IT.
Compétences requises : gouvernance des risques, conformité, cybersécurité,
gestion de projet, pilotage.
"""
GOVERNANCE_JOB_PRIORITY_KEYWORDS = (
    "gouvernance\nrisques\nconformité\ncybersécurité\ngestion de projet\npilotage"
)
GOVERNANCE_STRONG_CV = """
Consultant en gouvernance, cybersécurité, risque et conformité
réglementaire. Pilotage de projets de mise en conformité, gestion des
risques, cadrage gouvernance IT. Plusieurs missions en cybersécurité et
conformité réglementaire pour des grands comptes.
"""


def test_well_aligned_priority_keywords_still_score_high():
    result = match_cv_to_job(
        GOVERNANCE_STRONG_CV, GOVERNANCE_JOB,
        priority_keywords=GOVERNANCE_JOB_PRIORITY_KEYWORDS,
    )
    assert result.score >= 65, (
        f"couverture quasi totale des mots-cles prioritaires attendue "
        f">= 65%, obtenu {result.score}"
    )
