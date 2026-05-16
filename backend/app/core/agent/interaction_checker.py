"""
interaction_checker.py : Vérification des interactions médicamenteuses.

Base de données des interactions connues codée en "dur" cas de test (pour le TFE).
(sur base de renseignements en production, cette base serait remplacée par une API médicale (RxNorm, Vidal...)).

Algorithme : O(n²) compare chaque paire de médicaments.
Pour 10 médicaments : 45 paires à vérifier (10×9/2).
"""
import logging
from typing import Dict, List, Tuple

from app.core.agent.models import InteractionResult, PatientInfo, Prescription
from app.core.agent.types import InteractionSeverity, Status

logger = logging.getLogger(__name__)

class InteractionChecker:
    """
    Vérifie les interactions médicamenteuses et les allergies patient.
    
    Base de données : dict avec paires triées de médicaments comme clé.
    Tri alphabétique = l'ordre d'écriture n'importe pas.
    ("aspirine","warfarine") == ("warfarine","aspirine")
    """

    # Base de données des interactions connues
    # Format : {("méd1", "méd2"): (sévérité, description, recommandations)}
    _INTERACTIONS_DB: Dict[Tuple, Tuple] = {
        ("aspirine", "warfarine"): (
            InteractionSeverity.HIGH,
            "Risque hémorragique majeur : aspirine potentialise l'effet anticoagulant de la warfarine.",
            ["Éviter l'association", "Surveiller l'INR étroitement", "Envisager un IPP si association nécessaire"],
        ),
        ("ibuprofene", "warfarine"): (
            InteractionSeverity.HIGH,
            "AINS + anticoagulant oral : risque de saignement gastro-intestinal élevé.",
            ["Préférer le paracétamol comme antalgique", "Surveillance INR si maintien"],
        ),
        ("metformine", "alcool"): (
            InteractionSeverity.HIGH,
            "Risque d'acidose lactique avec consommation d'alcool sous metformine.",
            ["Éviter la consommation d'alcool", "Surveiller la créatinine"],
        ),
        ("atenolol", "verapamil"): (
            InteractionSeverity.CRITICAL,
            "Bradycardie sévère et bloc auriculo-ventriculaire possible.",
            ["Association contre-indiquée", "Consulter un cardiologue"],
        ),
        ("simvastatine", "clarithromycine"): (
            InteractionSeverity.HIGH,
            "Risque de myopathie et rhabdomyolyse : clarithromycine inhibe le métabolisme de la simvastatine.",
            ["Arrêter temporairement la simvastatine", "Utiliser azithromycine à la place"],
        ),
        ("clopidogrel", "omeprazole"): (
            InteractionSeverity.MEDIUM,
            "Oméprazole réduit l'efficacité du clopidogrel (inhibition CYP2C19).",
            ["Préférer pantoprazole ou ésoméprazole", "Surveillance clinique"],
        ),
        ("lithium", "ibuprofene"): (
            InteractionSeverity.HIGH,
            "Les AINS augmentent la lithiémie et le risque de toxicité au lithium.",
            ["Éviter les AINS", "Si nécessaire : surveiller lithiémie tous les 5 jours"],
        ),
        ("sertraline", "tramadol"): (
            InteractionSeverity.HIGH,
            "Risque de syndrome sérotoninergique (hyperthermie, agitation, tremblements).",
            ["Association déconseillée", "Si nécessaire : démarrer à faibles doses"],
        ),
        ("digoxine", "amiodarone"): (
            InteractionSeverity.HIGH,
            "Amiodarone augmente la digoxinémie jusqu'à 100%, risque de toxicité cardiaque.",
            ["Réduire la dose de digoxine de 50%", "Surveiller la digoxinémie"],
        ),
        ("methotrexate", "aspirine"): (
            InteractionSeverity.CRITICAL,
            "L'aspirine réduit l'élimination rénale du méthotrexate : toxicité majeure.",
            ["Contre-indiqué", "Informer immédiatement le rhumatologue"],
        ),
    }

    # Allergies croisées (si allergie à A → attention à B)
    _CROSS_ALLERGIES: Dict[str, List[str]] = {
        "penicilline":    ["amoxicilline", "ampicilline", "piperacilline"],
        "sulfamides":     ["furosemide", "thiazides", "celecoxib"],
        "aspirine":       ["autres ains", "ibuprofene", "diclofenac"],
    }

    def checkDrugInteractions(self, medications: List[str]) -> InteractionResult:
        """
        Vérifie toutes les paires de médicaments.
        Retourne l'interaction la plus grave trouvée.
        
        Algorithme O(n²) :
        Pour [A, B, C] → vérifie (A,B), (A,C), (B,C)
        """
        normalized = [m.lower().strip() for m in medications if m.strip()]
        worst: Tuple = None  # (sévérité, description, recommandations, pair)

        for i in range(len(normalized)):
            for j in range(i + 1, len(normalized)):
                pair = tuple(sorted([normalized[i], normalized[j]]))
                if pair in self._INTERACTIONS_DB:
                    sev, desc, reco = self._INTERACTIONS_DB[pair]
                    if worst is None or self._severity_rank(sev) > self._severity_rank(worst[0]):
                        worst = (sev, desc, reco, list(pair))

        if worst is None:
            return InteractionResult(
                has_interaction=False,
                medications=normalized,
                description="Aucune interaction connue détectée.",
                status=Status.COMPLETED,
            )

        return InteractionResult(
            has_interaction=True,
            severity=worst[0],
            medications=worst[3],
            description=worst[1],
            recommendations=worst[2],
            status=Status.COMPLETED,
        )

    def checkAllergies(self, patient_info: PatientInfo, medications: List[str]) -> InteractionResult:
        """Vérifie si un médicament correspond à une allergie du patient."""
        meds_lower = [m.lower() for m in medications]
        conflicts = []

        for allergen in patient_info.allergies:
            allergen_low = allergen.lower()
            # Allergie directe
            for med in meds_lower:
                if allergen_low in med or med in allergen_low:
                    conflicts.append(f"Allergie à {allergen} — {med} contre-indiqué")
            # Allergie croisée
            for base, crosses in self._CROSS_ALLERGIES.items():
                if base in allergen_low:
                    for cross in crosses:
                        if cross in meds_lower:
                            conflicts.append(f"Allergie croisée : {allergen} → {cross} déconseillé")

        if not conflicts:
            return InteractionResult(has_interaction=False)

        return InteractionResult(
            has_interaction=True,
            severity=InteractionSeverity.HIGH,
            description=" | ".join(conflicts),
            recommendations=["Vérifier le dossier allergie avec le patient"],
            allergies=patient_info.allergies,
        )

    def validatePrescription(self, patient_info: PatientInfo, prescription: Prescription) -> InteractionResult:
        """
        Inclut : vérification interactions + vérification allergies.
        Retourne le résultat le plus grave.
        """
        candidates = [
            r for r in [
                self.checkDrugInteractions(prescription.medications),
                self.checkAllergies(patient_info, prescription.medications),
            ]
            if r.has_interaction
        ]
        if not candidates:
            return InteractionResult(has_interaction=False, status=Status.COMPLETED)
        return max(candidates, key=lambda r: self._SEVERITY_RANK.get(r.severity, 0))

    # Dictionnaire de rang — attribut de classe (reconstruit une seule fois)
    _SEVERITY_RANK: Dict = {
        InteractionSeverity.LOW:      1,
        InteractionSeverity.MEDIUM:   2,
        InteractionSeverity.HIGH:     3,
        InteractionSeverity.CRITICAL: 4,
    }