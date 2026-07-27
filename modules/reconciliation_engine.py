"""
Moteur de rapprochement bancaire
Algorithme de matching à 3 niveaux: exact, montant+date, Levenshtein
"""

import pandas as pd
import numpy as np
from datetime import timedelta
from modules.utils import levenshtein_similarite, nettoyer_libelle, formater_date
from modules.db_manager import (
    get_active_session, save_match, clear_matches_for_entite,
    save_suspens, clear_suspens_for_entite, add_history,
    get_mappages_by_entite
)


def run_reconciliation_for_entite(
    entite: str,
    releves_entite: pd.DataFrame,
    gl_entite: pd.DataFrame,
    tolerance_jours: int = 3,
    seuil_levenshtein: float = 0.70
) -> dict:
    """
    Exécute le matching complet pour une entité.
    
    Args:
        entite: Nom de l'entité (ex: "DISTRIBUTION")
        releves_entite: DataFrame combiné des relevés mappés à cette entité
        gl_entite: DataFrame du GL de cette entité
        tolerance_jours: Tolérance en jours pour le matching date
        seuil_levenshtein: Seuil minimal de similarité Levenshtein
    
    Returns:
        dict avec les résultats: matches, suspens, stats
    """
    session_id = get_active_session()
    
    # Nettoyer les anciens résultats pour cette entité
    clear_matches_for_entite(session_id, entite)
    clear_suspens_for_entite(session_id, entite)
    
    if releves_entite is None or releves_entite.empty:
        add_history(session_id, "RECONCILIATION_SKIP", entite, "Aucun relevé")
        return {'matches': [], 'suspens': [], 'stats': {'total': 0, 'matches': 0, 'suspens': 0}}
    
    if gl_entite is None or gl_entite.empty:
        add_history(session_id, "RECONCILIATION_SKIP", entite, "Aucun GL")
        return {'matches': [], 'suspens': [], 'stats': {'total': 0, 'matches': 0, 'suspens': 0}}
    
    # S'assurer que les colonnes nécessaires existent
    releves = releves_entite.copy()
    gl = gl_entite.copy()
    
    # Ajouter montant_abs si pas présent
    if 'montant_abs' not in releves.columns:
        releves['montant_abs'] = releves['montant'].abs()
    if 'montant_abs' not in gl.columns:
        gl['montant_abs'] = gl['montant'].abs()
    
    # Index pour suivre les lignes déjà matchées
    gl_matched = set()
    releve_matched = set()
    
    matches = []
    suspens = []
    
    # --- ÉTAPE 1: MATCH EXACT (par référence/pièce) ---
    for idx_r, row_r in releves.iterrows():
        if idx_r in releve_matched:
            continue
        
        libelle_r = str(row_r.get('libelle', '')).lower()
        if not libelle_r:
            continue
        
        for idx_g, row_g in gl.iterrows():
            if idx_g in gl_matched:
                continue
            
            piece_g = str(row_g.get('piece', '')).lower().strip()
            if not piece_g or piece_g == 'nan' or piece_g == '':
                continue
            
            # Vérifier si la pièce est contenue dans le libellé du relevé
            if piece_g in libelle_r:
                # Vérifier que les montants correspondent (ou sont proches)
                montant_r = abs(row_r.get('montant', 0))
                montant_g = abs(row_g.get('montant', 0))
                
                if abs(montant_r - montant_g) <= max(1, montant_r * 0.01):
                    # Match exact trouvé
                    match = {
                        'entite': entite,
                        'banque': row_r.get('banque', ''),
                        'date_operation': str(row_r.get('date', '')),
                        'libelle_releve': str(row_r.get('libelle', '')),
                        'libelle_gl': str(row_g.get('libelle', '')),
                        'montant': row_r.get('montant', 0),
                        'type_match': 'exact',
                        'confiance': 1.0,
                        'gl_piece': piece_g,
                        'gl_compte': str(row_g.get('compte', ''))
                    }
                    matches.append(match)
                    save_match(session_id, **match)
                    
                    gl_matched.add(idx_g)
                    releve_matched.add(idx_r)
                    break
    
    # --- ÉTAPE 2: MATCH MONTANT + DATE ---
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
            
            # Comparer montants
            if abs(montant_r - montant_g) > max(1, montant_r * 0.01):
                continue
            
            # Comparer dates (avec tolérance)
            try:
                diff_jours = abs((date_r - date_g).days)
            except:
                continue
            
            if diff_jours <= tolerance_jours:
                # Match montant + date trouvé
                confiance = 0.80 - (diff_jours / (tolerance_jours * 10))
                confiance = max(0.50, min(0.80, confiance))
                
                match = {
                    'entite': entite,
                    'banque': row_r.get('banque', ''),
                    'date_operation': str(row_r.get('date', '')),
                    'libelle_releve': str(row_r.get('libelle', '')),
                    'libelle_gl': str(row_g.get('libelle', '')),
                    'montant': row_r.get('montant', 0),
                    'type_match': 'montant_date',
                    'confiance': round(confiance, 2),
                    'gl_piece': str(row_g.get('piece', '')),
                    'gl_compte': str(row_g.get('compte', ''))
                }
                matches.append(match)
                save_match(session_id, **match)
                
                gl_matched.add(idx_g)
                releve_matched.add(idx_r)
                break
    
    # --- ÉTAPE 3: MATCH LEVENSHTEIN ---
    for idx_r, row_r in releves.iterrows():
        if idx_r in releve_matched:
            continue
        
        libelle_r = str(row_r.get('libelle', ''))
        montant_r = abs(row_r.get('montant', 0))
        
        if not libelle_r or montant_r == 0:
            continue
        
        best_score = 0
        best_idx = None
        best_row = None
        
        for idx_g, row_g in gl.iterrows():
            if idx_g in gl_matched:
                continue
            
            libelle_g = str(row_g.get('libelle', ''))
            montant_g = abs(row_g.get('montant', 0))
            
            if not libelle_g or montant_g == 0:
                continue
            
            # Vérifier d'abord que les montants sont proches
            if abs(montant_r - montant_g) > max(100, montant_r * 0.05):
                continue
            
            # Calculer similarité Levenshtein
            score = levenshtein_similarite(libelle_r, libelle_g)
            
            if score > best_score:
                best_score = score
                best_idx = idx_g
                best_row = row_g
        
        if best_score >= seuil_levenshtein and best_row is not None:
            match = {
                'entite': entite,
                'banque': row_r.get('banque', ''),
                'date_operation': str(row_r.get('date', '')),
                'libelle_releve': str(row_r.get('libelle', '')),
                'libelle_gl': str(best_row.get('libelle', '')),
                'montant': row_r.get('montant', 0),
                'type_match': 'levenshtein',
                'confiance': round(best_score, 2),
                'gl_piece': str(best_row.get('piece', '')),
                'gl_compte': str(best_row.get('compte', ''))
            }
            matches.append(match)
            save_match(session_id, **match)
            
            gl_matched.add(best_idx)
            releve_matched.add(idx_r)
    
    # --- ÉTAPE 4: GÉNÉRER LES SUSPENS ---
    
    # Suspens: lignes relevé non matchées
    for idx_r, row_r in releves.iterrows():
        if idx_r in releve_matched:
            continue
        
        save_suspens(
            session_id, entite, 'RELEVE_SEUL', 'releve',
            str(row_r.get('date', '')),
            str(row_r.get('libelle', '')),
            row_r.get('montant', 0),
            row_r.get('banque', ''),
            motif="À éclaircir",
            observations="Opération relevé non trouvée dans le GL",
            statut="Ouvert"
        )
        suspens.append({
            'type': 'RELEVE_SEUL',
            'source': 'releve',
            'date': str(row_r.get('date', '')),
            'libelle': str(row_r.get('libelle', '')),
            'montant': row_r.get('montant', 0),
            'banque': row_r.get('banque', '')
        })
    
    # Suspens: lignes GL non matchées
    for idx_g, row_g in gl.iterrows():
        if idx_g in gl_matched:
            continue
        
        montant_g = abs(row_g.get('montant', 0))
        if montant_g == 0:
            continue
        
        save_suspens(
            session_id, entite, 'GL_SEUL', 'gl',
            str(row_g.get('date', '')),
            str(row_g.get('libelle', '')),
            row_g.get('montant', 0),
            '',
            motif="À éclaircir",
            observations="Écriture GL non retrouvée dans le relevé",
            statut="Ouvert"
        )
        suspens.append({
            'type': 'GL_SEUL',
            'source': 'gl',
            'date': str(row_g.get('date', '')),
            'libelle': str(row_g.get('libelle', '')),
            'montant': row_g.get('montant', 0),
            'banque': ''
        })
    
    # Statistiques
    stats = {
        'total_releve': len(releves),
        'total_gl': len(gl),
        'matches': len(matches),
        'suspens': len(suspens),
        'taux_appairage': round(len(matches) / max(len(releves), 1) * 100, 1),
        'matches_exact': sum(1 for m in matches if m['type_match'] == 'exact'),
        'matches_montant_date': sum(1 for m in matches if m['type_match'] == 'montant_date'),
        'matches_levenshtein': sum(1 for m in matches if m['type_match'] == 'levenshtein'),
    }
    
    add_history(session_id, "RECONCILIATION_DONE", entite,
                f"{stats['matches']} matches, {stats['suspens']} suspens, "
                f"taux: {stats['taux_appairage']}%")
    
    return {
        'matches': matches,
        'suspens': suspens,
        'stats': stats
    }


def run_all_reconciliations(
    gls_dict: dict,
    releves_dict: dict,
    tolerance_jours: int = 3,
    seuil_levenshtein: float = 0.70
) -> dict:
    """
    Exécute le matching pour toutes les entités.
    
    Args:
        gls_dict: dict {nom_entite: df_gl}
        releves_dict: dict {nom_fichier: df_releve}
        tolerance_jours: Tolérance en jours
        seuil_levenshtein: Seuil Levenshtein
    
    Returns:
        dict {entite: resultat}
    """
    session_id = get_active_session()
    results = {}
    
    # Récupérer les mappages
    mappages = get_mappages_by_entite(session_id, "")  # On va plutôt itérer
    
    # Grouper les relevés par entité selon les mappages
    from modules.db_manager import get_all_mappages
    all_mappages = get_all_mappages(session_id)
    
    releves_par_entite = {}
    for m in all_mappages:
        entite = m['entite_assignee']
        if entite == 'À DÉTERMINER':
            continue
        if entite not in releves_par_entite:
            releves_par_entite[entite] = []
        if m['releve_name'] in releves_dict:
            releves_par_entite[entite].append(releves_dict[m['releve_name']])
    
    # Pour chaque entité avec GL chargé
    for entite, gl_df in gls_dict.items():
        if gl_df is None or gl_df.empty:
            continue
        
        # Récupérer les relevés pour cette entité
        releves_entite_list = releves_par_entite.get(entite, [])
        
        if not releves_entite_list:
            # Aucun relevé mappé à cette entité
            results[entite] = {
                'matches': [],
                'suspens': [],
                'stats': {'total_releve': 0, 'total_gl': len(gl_df),
                         'matches': 0, 'suspens': 0, 'taux_appairage': 0}
            }
            continue
        
        # Combiner tous les relevés de cette entité
        releves_combines = pd.concat(releves_entite_list, ignore_index=True)
        
        # Exécuter le matching
        result = run_reconciliation_for_entite(
            entite, releves_combines, gl_df,
            tolerance_jours, seuil_levenshtein
        )
        results[entite] = result
    
    return results