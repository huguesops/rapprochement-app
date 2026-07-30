"""
Nettoyage et normalisation des données bancaires et GL
Gère les formats variés: UNICS, FH, BGFI, CEPAC, ADVANS, etc.
"""

import pandas as pd
import numpy as np
from datetime import datetime
from modules.utils import (
    normaliser_montant_str, parser_date_flexible, nettoyer_libelle
)


def _is_null(value) -> bool:
    """Retourne True si la valeur est nulle/NaN/None, sans risquer une erreur de Series."""
    try:
        if value is None:
            return True
        if isinstance(value, float) and np.isnan(value):
            return True
        if isinstance(value, pd.Series):
            return False
        return False
    except Exception:
        return False


def _safe_str(value) -> str:
    """Convertit proprement en chaîne, même si value est une Series."""
    try:
        if isinstance(value, pd.Series):
            return ""
        return str(value)
    except Exception:
        return ""


def nettoyer_releve(df: pd.DataFrame, nom_fichier: str) -> pd.DataFrame | None:
    """
    Nettoie et normalise un relevé bancaire.
    Détecte automatiquement le format (UNICS, FH, etc.) et applique les transformations.
    """
    if df is None or (hasattr(df, 'empty') and df.empty):
        return None
    
    df = df.copy()
    nom = nom_fichier.upper()
    
    # Normaliser les noms de colonnes
    df.columns = [str(col).strip().lower() for col in df.columns]
    
    # Détection du format
    format_unics = any('libellé' in c or 'libelle' in c for c in df.columns) and \
                   any('solde' in c for c in df.columns) and \
                   any('montant' in c for c in df.columns)
    
    format_fh = any('batch' in c or 'ref' in c for c in df.columns) and \
                any('d. valeur' in c or 'd.valeur' in c for c in df.columns) and \
                any('débit' in c or 'debit' in c for c in df.columns) and \
                any('crédit' in c or 'credit' in c for c in df.columns)
    
    if format_fh or 'FH' in nom:
        try:
            result = _nettoyer_format_fh(df, nom_fichier)
        except Exception:
            result = _nettoyer_format_generique(df, nom_fichier)
    elif format_unics or 'UNICS' in nom:
        try:
            result = _nettoyer_format_unics(df, nom_fichier)
        except Exception:
            result = _nettoyer_format_generique(df, nom_fichier)
    else:
        # Format générique
        result = _nettoyer_format_generique(df, nom_fichier)

    # Filet de sécurité: quel que soit le format détecté (même un format
    # futur/inconnu mal reconnu), on garantit que les colonnes essentielles
    # existent toujours pour que le moteur de rapprochement ne plante jamais.
    if result is not None:
        if 'montant' not in result.columns:
            result['montant'] = 0.0
        result['montant'] = pd.to_numeric(result['montant'], errors='coerce').fillna(0.0)
        if 'debit' not in result.columns:
            result['debit'] = result['montant'].apply(lambda x: abs(x) if x < 0 else 0.0)
        if 'credit' not in result.columns:
            result['credit'] = result['montant'].apply(lambda x: x if x > 0 else 0.0)
        if 'libelle' not in result.columns:
            result['libelle'] = ''
        if 'date' not in result.columns:
            result['date'] = None

    return result


def _nettoyer_format_unics(df: pd.DataFrame, nom_fichier: str) -> pd.DataFrame:
    """
    Nettoie le format UNICS.
    Deux variantes existent en pratique:
      - Date | Libellé | Montant | Solde courant  (montant signé, +crédit/-débit)
      - Date | ... | Debit | Credit | Balance      (colonnes séparées, cas réel observé)
    """
    result = pd.DataFrame()
    
    # Renommer colonnes (ordre important: tester les motifs les plus
    # spécifiques d'abord pour éviter les collisions, ex: "Value Date"
    # contient aussi "date" et ne doit pas écraser la colonne "Date" principale)
    col_map = {}
    for c in df.columns:
        if 'value' in c or 'valeur' in c:
            continue  # date de valeur ignorée, pas utilisée pour le matching
        elif 'date' in c and 'date' not in col_map.values():
            col_map[c] = 'date'
        elif 'libell' in c or 'libelle' in c or 'particular' in c:
            col_map[c] = 'libelle'
        elif 'montant' in c:
            col_map[c] = 'montant'
        elif 'débit' in c or 'debit' in c:
            col_map[c] = 'debit'
        elif 'crédit' in c or 'credit' in c:
            col_map[c] = 'credit'
        elif 'solde' in c or 'balance' in c:
            col_map[c] = 'solde'
    df = df.rename(columns=col_map)
    
    result['date_raw'] = df['date'].astype(str) if 'date' in df.columns else ''
    result['date'] = df['date'].apply(parser_date_flexible) if 'date' in df.columns else None
    result['libelle'] = df['libelle'].apply(nettoyer_libelle) if 'libelle' in df.columns else ''
    
    if 'montant' in df.columns:
        # Variante 1: montant signé unique (+crédit / -débit)
        result['montant'] = df['montant'].apply(
            lambda x: normaliser_montant_str(str(x)) if not _is_null(x) else 0.0
        )
        result['debit'] = result['montant'].apply(lambda x: abs(x) if x < 0 else 0.0)
        result['credit'] = result['montant'].apply(lambda x: x if x > 0 else 0.0)
    elif 'debit' in df.columns or 'credit' in df.columns:
        # Variante 2: colonnes Débit/Crédit séparées (cas réel des relevés UNICS)
        result['debit'] = df['debit'].apply(
            lambda x: normaliser_montant_str(str(x)) if not _is_null(x) else 0.0
        ) if 'debit' in df.columns else 0.0
        result['credit'] = df['credit'].apply(
            lambda x: normaliser_montant_str(str(x)) if not _is_null(x) else 0.0
        ) if 'credit' in df.columns else 0.0
        result['montant'] = result['credit'] - result['debit']
    else:
        # Aucune colonne de montant reconnue: on garantit quand même la colonne
        # pour ne jamais faire planter le moteur de rapprochement en aval.
        result['montant'] = 0.0
        result['debit'] = 0.0
        result['credit'] = 0.0
    
    if 'solde' in df.columns:
        result['solde'] = df['solde'].apply(
            lambda x: normaliser_montant_str(str(x)) if not _is_null(x) else 0.0
        )
    
    result['banque'] = 'UNICS'
    result['fichier'] = nom_fichier
    return result


def _nettoyer_format_fh(df: pd.DataFrame, nom_fichier: str) -> pd.DataFrame:
    """Nettoie le format FH: Date | Batch/Ref | Libelle | D.Valeur | Débit | Crédit | Solde."""
    result = pd.DataFrame()
    
    # Renommer colonnes
    col_map = {}
    for c in df.columns:
        if c == 'date':
            col_map[c] = 'date'
        elif 'batch' in c or 'ref' in c:
            col_map[c] = 'reference'
        elif 'libell' in c or 'libelle' in c:
            col_map[c] = 'libelle'
        elif 'valeur' in c:
            col_map[c] = 'date_valeur'
        elif 'débit' in c or 'debit' in c:
            col_map[c] = 'debit'
        elif 'crédit' in c or 'credit' in c:
            col_map[c] = 'credit'
        elif 'solde' in c:
            col_map[c] = 'solde'
    df = df.rename(columns=col_map)
    
    result['date_raw'] = df['date'].astype(str)
    result['date'] = df['date'].apply(parser_date_flexible)
    result['libelle'] = df['libelle'].apply(nettoyer_libelle)
    
    if 'reference' in df.columns:
        result['reference'] = df['reference'].astype(str)
    
    if 'date_valeur' in df.columns:
        result['date_valeur'] = df['date_valeur'].apply(parser_date_flexible)
    
    # Normaliser débit/crédit (avec séparateurs de milliers)
    if 'debit' in df.columns:
        result['debit'] = df['debit'].apply(
            lambda x: normaliser_montant_str(str(x)) if not _is_null(x) else 0.0
        )
    else:
        result['debit'] = 0.0
    
    if 'credit' in df.columns:
        result['credit'] = df['credit'].apply(
            lambda x: normaliser_montant_str(str(x)) if not _is_null(x) else 0.0
        )
    else:
        result['credit'] = 0.0
    
    # Montant net
    result['montant'] = result['credit'] - result['debit']
    
    if 'solde' in df.columns:
        result['solde'] = df['solde'].apply(
            lambda x: normaliser_montant_str(str(x)) if not _is_null(x) else 0.0
        )
    
    result['banque'] = 'FINANCIAL HOUSE'
    result['fichier'] = nom_fichier
    return result


def _nettoyer_format_generique(df: pd.DataFrame, nom_fichier: str) -> pd.DataFrame:
    """
    Nettoie un format générique en essayant de détecter les colonnes.
    """
    result = pd.DataFrame()
    banque = nom_fichier.replace('.xlsx', '').replace('.xls', '').replace('RELEVE_', '').replace('_', ' ')
    
    col_map = {}
    for c in df.columns:
        if 'date' in c:
            col_map[c] = 'date'
        elif 'libell' in c or 'libelle' in c or 'description' in c or 'narrative' in c:
            col_map[c] = 'libelle'
    df = df.rename(columns=col_map)
    
    if 'date' in df.columns:
        result['date_raw'] = df['date'].astype(str)
        result['date'] = df['date'].apply(parser_date_flexible)
    else:
        result['date_raw'] = ''
        result['date'] = None
    
    if 'libelle' in df.columns:
        result['libelle'] = df['libelle'].apply(nettoyer_libelle)
    else:
        result['libelle'] = ''
    
    # Chercher colonnes montant/débit/crédit
    montant_col = None
    debit_col = None
    credit_col = None
    
    for c in df.columns:
        c_lower = str(c).lower()
        if 'montant' in c_lower or 'amount' in c_lower:
            montant_col = c
        elif 'débit' in c_lower or 'debit' in c_lower or 'sortie' in c_lower:
            debit_col = c
        elif 'crédit' in c_lower or 'credit' in c_lower or 'entree' in c_lower or 'entrée' in c_lower:
            credit_col = c
    
    if montant_col:
        result['montant'] = df[montant_col].apply(
            lambda x: normaliser_montant_str(str(x)) if not _is_null(x) else 0.0
        )
        result['debit'] = result['montant'].apply(lambda x: abs(x) if x < 0 else 0.0)
        result['credit'] = result['montant'].apply(lambda x: x if x > 0 else 0.0)
    elif debit_col or credit_col:
        if debit_col:
            result['debit'] = df[debit_col].apply(
                lambda x: normaliser_montant_str(str(x)) if not _is_null(x) else 0.0
            )
        else:
            result['debit'] = 0.0
        if credit_col:
            result['credit'] = df[credit_col].apply(
                lambda x: normaliser_montant_str(str(x)) if not _is_null(x) else 0.0
            )
        else:
            result['credit'] = 0.0
        result['montant'] = result['credit'] - result['debit']
    else:
        # Prendre la première colonne numérique
        for c in df.columns:
            if df[c].dtype in ['int64', 'float64']:
                result['montant'] = df[c]
                result['debit'] = result['montant'].apply(lambda x: abs(x) if x < 0 else 0.0)
                result['credit'] = result['montant'].apply(lambda x: x if x > 0 else 0.0)
                break
    
    result['banque'] = banque.strip()
    result['fichier'] = nom_fichier
    return result


def nettoyer_gl(df: pd.DataFrame, nom_entite: str) -> pd.DataFrame | None:
    """
    Nettoie et normalise un Grand Livre Odoo 18.
    Colonnes attendues: Date | Compte | Libellé | Débit | Crédit | Solde | Pièce/Journal
    """
    if df is None:
        return None
    
    # Gérer le cas où df n'est pas vide mais n'a aucune colonne valide
    try:
        if hasattr(df, 'empty') and df.empty:
            return None
    except Exception:
        return None
    
    df = df.copy()
    df.columns = [str(col).strip().lower() for col in df.columns]
    
    result = pd.DataFrame()
    
    # Mapper les colonnes Odoo
    col_map = {}
    for c in df.columns:
        if 'date' in c:
            col_map[c] = 'date'
        elif 'compte' in c or 'account' in c:
            col_map[c] = 'compte'
        elif 'libell' in c or 'libelle' in c or 'label' in c or 'name' in c:
            col_map[c] = 'libelle'
        elif 'débit' in c or 'debit' in c:
            col_map[c] = 'debit'
        elif 'crédit' in c or 'credit' in c:
            col_map[c] = 'credit'
        elif 'solde' in c or 'balance' in c:
            col_map[c] = 'solde'
        elif 'pièce' in c or 'piece' in c or 'ref' in c or 'reference' in c or 'journal' in c:
            col_map[c] = 'piece'
    
    df = df.rename(columns=col_map)
    
    # Date — forcer un booléen Python pour éviter "truth value of a Series is ambiguous"
    has_date_col = bool('date' in df.columns)
    if has_date_col:
        result['date'] = df['date'].apply(parser_date_flexible)
    else:
        result['date'] = None
    
    # Compte (garder comme string)
    if 'compte' in df.columns:
        result['compte'] = df['compte'].astype(str).str.strip()
    else:
        result['compte'] = ''
    
    # Libellé — test booléen explicite sans pd.notna
    if 'libelle' in df.columns:
        result['libelle'] = df['libelle'].apply(
            lambda x: nettoyer_libelle(_safe_str(x)) if _is_null(x) is False else ''
        )
    else:
        result['libelle'] = ''
    
    # Débit
    if 'debit' in df.columns:
        result['debit'] = df['debit'].apply(
            lambda x: normaliser_montant_str(_safe_str(x)) if _is_null(x) is False else 0.0
        )
    else:
        result['debit'] = 0.0
    
    # Crédit
    if 'credit' in df.columns:
        result['credit'] = df['credit'].apply(
            lambda x: normaliser_montant_str(_safe_str(x)) if _is_null(x) is False else 0.0
        )
    else:
        result['credit'] = 0.0
    
    # Montant net (crédit - débit pour sens unique)
    result['montant'] = result['credit'] - result['debit']
    
    # Pièce — forcer un booléen Python
    has_piece_col = bool('piece' in df.columns)
    if has_piece_col:
        result['piece'] = df['piece'].astype(str).str.strip()
    else:
        result['piece'] = ''
    
    result['entite'] = nom_entite
    return result


def nettoyer_montant_absolu(df: pd.DataFrame) -> pd.DataFrame:
    """
    Ajoute une colonne 'montant_abs' pour faciliter les comparaisons.
    """
    if 'montant' in df.columns:
        df['montant_abs'] = df['montant'].abs()
    return df
