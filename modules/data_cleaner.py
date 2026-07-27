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


def nettoyer_releve(df: pd.DataFrame, nom_fichier: str) -> pd.DataFrame:
    """
    Nettoie et normalise un relevé bancaire.
    Détecte automatiquement le format (UNICS, FH, etc.) et applique les transformations.
    """
    if df is None or df.empty:
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
        return _nettoyer_format_fh(df, nom_fichier)
    elif format_unics or 'UNICS' in nom:
        return _nettoyer_format_unics(df, nom_fichier)
    else:
        # Format générique
        return _nettoyer_format_generique(df, nom_fichier)


def _nettoyer_format_unics(df: pd.DataFrame, nom_fichier: str) -> pd.DataFrame:
    """Nettoie le format UNICS: Date | Libellé | Montant | Solde courant."""
    result = pd.DataFrame()
    
    # Renommer colonnes
    col_map = {}
    for c in df.columns:
        if 'date' in c:
            col_map[c] = 'date'
        elif 'libell' in c or 'libelle' in c:
            col_map[c] = 'libelle'
        elif 'montant' in c:
            col_map[c] = 'montant'
        elif 'solde' in c:
            col_map[c] = 'solde'
    df = df.rename(columns=col_map)
    
    result['date_raw'] = df['date'].astype(str)
    result['date'] = df['date'].apply(parser_date_flexible)
    result['libelle'] = df['libelle'].apply(nettoyer_libelle)
    
    # Montant: positif = crédit, négatif = débit
    if 'montant' in df.columns:
        result['montant'] = df['montant'].apply(
            lambda x: normaliser_montant_str(str(x)) if pd.notna(x) else 0.0
        )
        result['debit'] = result['montant'].apply(lambda x: abs(x) if x < 0 else 0.0)
        result['credit'] = result['montant'].apply(lambda x: x if x > 0 else 0.0)
    
    if 'solde' in df.columns:
        result['solde'] = df['solde'].apply(
            lambda x: normaliser_montant_str(str(x)) if pd.notna(x) else 0.0
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
            lambda x: normaliser_montant_str(str(x)) if pd.notna(x) else 0.0
        )
    else:
        result['debit'] = 0.0
    
    if 'credit' in df.columns:
        result['credit'] = df['credit'].apply(
            lambda x: normaliser_montant_str(str(x)) if pd.notna(x) else 0.0
        )
    else:
        result['credit'] = 0.0
    
    # Montant net
    result['montant'] = result['credit'] - result['debit']
    
    if 'solde' in df.columns:
        result['solde'] = df['solde'].apply(
            lambda x: normaliser_montant_str(str(x)) if pd.notna(x) else 0.0
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
            lambda x: normaliser_montant_str(str(x)) if pd.notna(x) else 0.0
        )
        result['debit'] = result['montant'].apply(lambda x: abs(x) if x < 0 else 0.0)
        result['credit'] = result['montant'].apply(lambda x: x if x > 0 else 0.0)
    elif debit_col or credit_col:
        if debit_col:
            result['debit'] = df[debit_col].apply(
                lambda x: normaliser_montant_str(str(x)) if pd.notna(x) else 0.0
            )
        else:
            result['debit'] = 0.0
        if credit_col:
            result['credit'] = df[credit_col].apply(
                lambda x: normaliser_montant_str(str(x)) if pd.notna(x) else 0.0
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


def nettoyer_gl(df: pd.DataFrame, nom_entite: str) -> pd.DataFrame:
    """
    Nettoie et normalise un Grand Livre Odoo 18.
    Colonnes attendues: Date | Compte | Libellé | Débit | Crédit | Solde | Pièce/Journal
    """
    if df is None or df.empty:
        return None
    
    df = df.copy()
    df.columns = [str(col).strip().lower() for col in df.columns]
    
    result = pd.DataFrame()
    
    # Mapper les colonnes Odoo
    col_map = {}
    for c in df.columns:
        if 'date' in c:
            col_map[c] = 'date'
        elif 'compte' in c or 'account' in c or 'compte' in c:
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
    
    # Date
    if 'date' in df.columns:
        result['date'] = df['date'].apply(parser_date_flexible)
    else:
        result['date'] = None
    
    # Compte (garder comme string)
    if 'compte' in df.columns:
        result['compte'] = df['compte'].astype(str).str.strip()
    else:
        result['compte'] = ''
    
    # Libellé
    if 'libelle' in df.columns:
        result['libelle'] = df['libelle'].apply(
            lambda x: nettoyer_libelle(str(x)) if pd.notna(x) else ''
        )
    else:
        result['libelle'] = ''
    
    # Débit
    if 'debit' in df.columns:
        result['debit'] = df['debit'].apply(
            lambda x: normaliser_montant_str(str(x)) if pd.notna(x) else 0.0
        )
    else:
        result['debit'] = 0.0
    
    # Crédit
    if 'credit' in df.columns:
        result['credit'] = df['credit'].apply(
            lambda x: normaliser_montant_str(str(x)) if pd.notna(x) else 0.0
        )
    else:
        result['credit'] = 0.0
    
    # Montant net (crédit - débit pour sens unique)
    result['montant'] = result['credit'] - result['debit']
    
    # Pièce
    if 'piece' in df.columns:
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
