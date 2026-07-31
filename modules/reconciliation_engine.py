"""
Moteur de rapprochement bancaire
Algorithme de matching à 3 niveaux: exact, montant+date, Levenshtein

IMPORTANT — architecture réelle du Groupe SKAB:
Un relevé bancaire n'appartient PAS à une seule entité: les 4 entités
(DISTRIBUTION, NUTRITION, SERVICES, ÉLEVAGE) partagent les mêmes comptes
bancaires, donc un même relevé peut contenir des opérations mélangées de
plusieurs entités. Il n'y a donc pas de mappage manuel "ce relevé =
cette entité" possible.

À la place, l'entité d'une opération est déterminée AUTOMATIQUEMENT par
le rapprochement lui-même: chaque ligne de relevé est comparée aux GL des
4 entités à la fois, et l'entité retenue est celle dont le GL produit le
meilleur appairage. Les lignes qui ne matchent aucun GL restent en
suspens, avec une entité "NON DÉTERMINÉE" que l'utilisateur peut
réattribuer manuellement lors de l'investigation (voir
reassign_suspens_entite dans db_manager.py).
"""

import pandas as pd
import numpy as np
from datetime import timedelta
from modules.utils import levenshtein_similarite, nettoyer_libelle, formater_date
from modules.db_manager import (
    save_match, clear_matches_for_entite,
    save_suspens, clear_suspens_for_entite, add_history
)

# Pseudo-entité utilisée pour les opérations de relevé qu'aucun GL n'a permis
# d'attribuer automatiquement. L'utilisateur peut ensuite les réattribuer
# manuellement à la bonne entité depuis l'onglet Rapprochement.
NON_DETERMINEE = "NON DÉTERMINÉE"


def _build_match(row_r, row_g, type_match: str, confiance: float) -> dict:
    return {
        'entite': row_g.get('entite', ''),
        'banque': row_r.get('banque', ''),
        'date_operation': str(row_r.get('date', '')),
        'libelle_releve': str(row_r.get('libelle', '')),
        'libelle_gl': str(row_g.get('libelle', '')),
        'montant': row_r.get('montant', 0),
        'type_match': type_match,
        'confiance': confiance,
        'gl_piece': str(row_g.get('piece', '')),
        'gl_compte': str(row_g.get('compte', '')),
    }


def run_global_reconciliation(
    gls_dict: dict,
    releves_dict: dict,
    session_id,
    tolerance_jours: int = 3,
    seuil_levenshtein: float = 0.70
) -> dict:
    """
    Exécute le rapprochement pour TOUTES les entités à la fois.

    Chaque ligne de CHAQUE relevé chargé est comparée aux écritures des
    4 GL simultanément (et non au GL d'une seule entité présupposée) —
    l'entité est déduite automatiquement par le GL avec lequel l'opération
    matche. Aucun mappage manuel préalable n'est nécessaire.

    Args:
        gls_dict: dict {nom_entite: df_gl}
        releves_dict: dict {nom_fichier: df_releve}
        session_id: identifiant de la session de travail en cours
        tolerance_jours: Tolérance en jours pour le matching date
        seuil_levenshtein: Seuil minimal de similarité Levenshtein

    Returns:
        dict avec les statistiques globales et par entité
    """
    entites = [e for e, df in gls_dict.items() if df is not None and not df.empty]

    # Nettoyer les anciens résultats (4 entités + le panier "non déterminée")
    for entite in entites:
        clear_matches_for_entite(session_id, entite)
        clear_suspens_for_entite(session_id, entite)
    clear_suspens_for_entite(session_id, NON_DETERMINEE)

    releves_list = [df for df in releves_dict.values() if df is not None and not df.empty]
    if not releves_list:
        add_history(session_id, "RECONCILIATION_SKIP", "", "Aucun relevé chargé")
        return {'total_matches': 0, 'total_releve': 0, 'total_gl': 0,
                'non_determinees': 0, 'matches_par_entite': {}}

    if not entites:
        add_history(session_id, "RECONCILIATION_SKIP", "", "Aucun GL chargé")
        return {'total_matches': 0, 'total_releve': 0, 'total_gl': 0,
                'non_determinees': 0, 'matches_par_entite': {}}

    # Combiner tous les relevés chargés en un seul jeu de données
    releves = pd.concat(releves_list, ignore_index=True)

    # Combiner tous les GL, en étiquetant chaque ligne avec son entité
    gl_list = []
    for entite in entites:
        d = gls_dict[entite].copy()
        d['entite'] = entite  # garantit l'étiquette correcte quelle que soit la source
        gl_list.append(d)
    gl = pd.concat(gl_list, ignore_index=True)

    # Filet de sécurité: garantir la colonne 'montant' (formats bancaires
    # imprévus, fichiers persistés avant un correctif de nettoyage, etc.)
    for df_ in (releves, gl):
        if 'montant' not in df_.columns:
            df_['montant'] = 0.0
        df_['montant'] = pd.to_numeric(df_['montant'], errors='coerce').fillna(0.0)
    releves['montant_abs'] = releves['montant'].abs()
    gl['montant_abs'] = gl['montant'].abs()

    releve_matched = set()
    gl_matched = set()
    matches = []

    # --- ÉTAPE 1: MATCH EXACT (référence/pièce trouvée dans le libellé) ---
    for idx_r, row_r in releves.iterrows():
        libelle_r = str(row_r.get('libelle', '')).lower()
        if not libelle_r:
            continue

        for idx_g, row_g in gl.iterrows():
            if idx_g in gl_matched:
                continue

            piece_g = str(row_g.get('piece', '')).lower().strip()
            if not piece_g or piece_g == 'nan':
                continue

            if piece_g in libelle_r:
                montant_r = abs(row_r.get('montant', 0))
                montant_g = abs(row_g.get('montant', 0))

                if abs(montant_r - montant_g) <= max(1, montant_r * 0.01):
                    m = _build_match(row_r, row_g, 'exact', 1.0)
                    matches.append(m)
                    gl_matched.add(idx_g)
                    releve_matched.add(idx_r)
                    break

    # --- ÉTAPE 2: MATCH MONTANT + DATE (tolérance en jours) ---
    for idx_r, row_r in releves.iterrows():
        if idx_r in releve_matched:
            continue

        date_r = row_r.get('date')
        montant_r = abs(row_r.get('montant', 0))
        if date_r is None or montant_r == 0:
            continue

        for idx_g, row_g in gl.iterrows():
            if idx_g in gl_matched:
                continue

            date_g = row_g.get('date')
            montant_g = abs(row_g.get('montant', 0))
            if date_g is None or montant_g == 0:
                continue

            if abs(montant_r - montant_g) > max(1, montant_r * 0.01):
                continue

            try:
                diff_jours = abs((date_r - date_g).days)
            except Exception:
                continue

            if diff_jours <= tolerance_jours:
                confiance = 0.80 - (diff_jours / max(tolerance_jours * 10, 1))
                confiance = max(0.50, min(0.80, confiance))

                m = _build_match(row_r, row_g, 'montant_date', round(confiance, 2))
                matches.append(m)
                gl_matched.add(idx_g)
                releve_matched.add(idx_r)
                break

    # --- ÉTAPE 3: MATCH LEVENSHTEIN (similarité de libellé) ---
    for idx_r, row_r in releves.iterrows():
        if idx_r in releve_matched:
            continue

        libelle_r = str(row_r.get('libelle', ''))
        montant_r = abs(row_r.get('montant', 0))
        if not libelle_r or montant_r == 0:
            continue

        best_score, best_idx, best_row = 0, None, None

        for idx_g, row_g in gl.iterrows():
            if idx_g in gl_matched:
                continue

            libelle_g = str(row_g.get('libelle', ''))
            montant_g = abs(row_g.get('montant', 0))
            if not libelle_g or montant_g == 0:
                continue

            if abs(montant_r - montant_g) > max(100, montant_r * 0.05):
                continue

            score = levenshtein_similarite(libelle_r, libelle_g)
            if score > best_score:
                best_score, best_idx, best_row = score, idx_g, row_g

        if best_score >= seuil_levenshtein and best_row is not None:
            m = _build_match(row_r, best_row, 'levenshtein', round(best_score, 2))
            matches.append(m)
            gl_matched.add(best_idx)
            releve_matched.add(idx_r)

    # --- Sauvegarder les appairages ---
    for m in matches:
        save_match(session_id, **m)

    # --- SUSPENS: lignes relevé non attribuées (entité inconnue) ---
    for idx_r, row_r in releves.iterrows():
        if idx_r in releve_matched:
            continue
        save_suspens(
            session_id, NON_DETERMINEE, 'RELEVE_SEUL', 'releve',
            str(row_r.get('date', '')),
            str(row_r.get('libelle', '')),
            row_r.get('montant', 0),
            row_r.get('banque', ''),
            motif="À éclaircir",
            observations="Aucune correspondance trouvée dans les 4 GL — "
                        "à assigner manuellement à une entité si connue.",
            statut="Ouvert"
        )

    # --- SUSPENS: écritures GL non retrouvées dans les relevés (par entité) ---
    for idx_g, row_g in gl.iterrows():
        if idx_g in gl_matched:
            continue
        montant_g = abs(row_g.get('montant', 0))
        if montant_g == 0:
            continue
        entite_g = row_g.get('entite', '')
        save_suspens(
            session_id, entite_g, 'GL_SEUL', 'gl',
            str(row_g.get('date', '')),
            str(row_g.get('libelle', '')),
            row_g.get('montant', 0),
            '',
            motif="À éclaircir",
            observations="Écriture GL non retrouvée dans les relevés chargés.",
            statut="Ouvert"
        )

    non_determinees = len(releves) - len(releve_matched)
    add_history(
        session_id, "RECONCILIATION_GLOBALE", "",
        f"{len(matches)} appairages sur {len(releves)} lignes de relevé "
        f"({non_determinees} non déterminées), {len(gl) - len(gl_matched)} écritures GL orphelines"
    )

    matches_par_entite = {}
    for entite in entites:
        matches_par_entite[entite] = sum(1 for m in matches if m['entite'] == entite)

    return {
        'total_matches': len(matches),
        'total_releve': len(releves),
        'total_gl': len(gl),
        'non_determinees': non_determinees,
        'matches_par_entite': matches_par_entite,
    }
