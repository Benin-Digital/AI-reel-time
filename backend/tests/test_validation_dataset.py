"""Jeu de validation independant pour le moteur de matching.

Contexte : la seule mesure de qualite du moteur jusqu'ici etait le retour
RH en circuit ferme (accept/reject sur de vrais matches) — mais ca ne
mesure rien tant que la plateforme n'a pas d'usage reel. Ce fichier fixe
un petit jeu de paires CV/offre avec un jugement de reference explicite
(ce que n'importe quel recruteur humain attendrait), pour detecter
immediatement si un futur changement de poids/formule degrade la
pertinence generale — plutot que de le decouvrir via des retours RH des
mois plus tard.

Chaque cas documente le raisonnement humain derriere le score attendu.
Les seuils sont volontairement larges (bandes, pas valeurs exactes) pour
rester valables que le cross-encoder semantique soit disponible (prod)
ou non (CI, ou il retombe sur un score neutre de 0.5 — voir
matcher._get_cross_encoder).
"""
from __future__ import annotations

from app.services.matcher import match_cv_to_job

# ---------------------------------------------------------------------------
# Cas 1 : match technique fort — competences, experience et domaine alignes.
# Un recruteur validerait ce match sans hesitation.
# ---------------------------------------------------------------------------
TECH_STRONG_CV = """
Competences: Python, Django, PostgreSQL, Docker, API REST.
Experience: 5 ans en developpement backend Python chez plusieurs entreprises tech.
Formation: Master informatique.
"""
TECH_STRONG_JOB = """
Poste: Developpeur Backend Python.
Competences requises: Python, Django, PostgreSQL, Docker, API REST.
Experience requise: Minimum 3 ans en developpement backend.
Formation requise: Bac+5 informatique ou equivalent.
"""

# ---------------------------------------------------------------------------
# Cas 2 : mismatch total — un profil design candidate sur un poste de
# developpeur backend. Aucun recruteur ne verrait ca comme un bon match,
# quel que soit le nombre d'annees d'experience du candidat.
# ---------------------------------------------------------------------------
TECH_MISMATCH_CV = """
Competences: Photoshop, Illustrator, InDesign, identite visuelle, charte graphique.
Experience: 4 ans en tant que graphiste independant pour des agences de communication.
Formation: BTS design graphique.
"""
TECH_MISMATCH_JOB = """
Poste: Developpeur Backend Python.
Competences requises: Python, Django, PostgreSQL, Docker, Kubernetes, AWS.
Experience requise: Minimum 3 ans en developpement backend.
Formation requise: Bac+5 informatique ou equivalent.
"""

# ---------------------------------------------------------------------------
# Cas 3 : match fort dans un autre secteur (sante), pour verifier que la
# pertinence ne se limite pas au domaine tech.
# ---------------------------------------------------------------------------
HEALTH_STRONG_CV = """
Competences: soins infirmiers, urgences, prise en charge patient, pose de perfusion.
Experience: 4 ans en tant qu infirmiere en service d urgences.
Formation: Diplome d Etat Infirmier.
"""
HEALTH_STRONG_JOB = """
Poste: Infirmier(e) service des urgences.
Competences requises: soins infirmiers, urgences, prise en charge patient, gestes techniques.
Experience requise: Minimum 2 ans en service d urgences.
Formation requise: Diplome d Etat Infirmier obligatoire.
"""

# ---------------------------------------------------------------------------
# Cas 4 : match partiel — bon profil general, mais il manque des
# competences cles (Kubernetes, AWS) explicitement demandees. Un recruteur
# verrait ca comme "a examiner", ni excellent ni rejetable d'office.
# ---------------------------------------------------------------------------
PARTIAL_CV = """
Competences: Python, Django, PostgreSQL, API REST.
Experience: 4 ans en developpement backend Python.
Formation: Licence informatique.
"""
PARTIAL_JOB = """
Poste: Developpeur Backend Python Cloud.
Competences requises: Python, Django, PostgreSQL, API REST, Kubernetes, AWS.
Experience requise: Minimum 3 ans en developpement backend.
Formation requise: Bac+3 informatique ou equivalent.
"""

# ---------------------------------------------------------------------------
# Cas 5 : ecart d'experience flagrant — competences parfaitement alignees,
# mais un profil junior (1 an) sur un poste senior/lead (8 ans requis, avec
# encadrement). La composante experience doit refleter cet ecart, meme si
# le score global reste porte par les competences.
# ---------------------------------------------------------------------------
EXPERIENCE_GAP_CV = """
Competences: Python, Django, PostgreSQL, API REST, Docker.
Experience: 1 an en developpement backend Python (premier emploi).
Formation: Master informatique.
"""
EXPERIENCE_GAP_JOB = """
Poste: Lead Developpeur Backend Python Senior.
Competences requises: Python, Django, PostgreSQL, API REST, Docker.
Experience requise: Minimum 8 ans en developpement backend, dont experience d encadrement.
Formation requise: Bac+5 informatique ou equivalent.
"""


def test_tech_strong_match_scores_high():
    result = match_cv_to_job(TECH_STRONG_CV, TECH_STRONG_JOB)
    assert result.score_skills >= 0.9, "competences parfaitement alignees, couverture attendue quasi totale"
    assert result.score >= 65, f"match technique fort attendu >= 65, obtenu {result.score}"


def test_total_mismatch_scores_low():
    result = match_cv_to_job(TECH_MISMATCH_CV, TECH_MISMATCH_JOB)
    assert result.score_skills == 0.0, "aucune competence design ne recoupe les competences dev demandees"
    assert result.score <= 45, f"mismatch total attendu <= 45, obtenu {result.score}"


def test_health_strong_match_scores_high():
    result = match_cv_to_job(HEALTH_STRONG_CV, HEALTH_STRONG_JOB)
    assert result.score_skills >= 0.9
    assert result.score >= 65, f"match sante fort attendu >= 65, obtenu {result.score}"


def test_partial_match_scores_between_mismatch_and_strong():
    partial = match_cv_to_job(PARTIAL_CV, PARTIAL_JOB)
    strong = match_cv_to_job(TECH_STRONG_CV, TECH_STRONG_JOB)
    mismatch = match_cv_to_job(TECH_MISMATCH_CV, TECH_MISMATCH_JOB)

    assert 0.0 < partial.score_skills < 1.0, "il doit manquer au moins une competence requise, mais pas toutes"
    assert mismatch.score < partial.score < strong.score, (
        "un match partiel doit se classer strictement entre un mismatch total et un match fort"
    )


def test_experience_gap_is_reflected_in_experience_component():
    result = match_cv_to_job(EXPERIENCE_GAP_CV, EXPERIENCE_GAP_JOB)
    assert result.score_skills >= 0.9, "les competences techniques restent parfaitement alignees"
    assert result.score_experience <= 0.3, (
        f"un candidat a 1 an d'experience sur un poste senior (8 ans requis) doit avoir "
        f"une composante experience nettement penalisee, obtenu {result.score_experience}"
    )
