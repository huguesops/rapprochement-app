"""
Chargement des fichiers Excel: relevés bancaires multi-format + GLs Odoo
Gère les formats variés: UNICS, FH, BGFI, CEPAC, ADVANS, etc.
"""

import pandas as pd
import streamlit as st
from pathlib import Path
from io import BytesIO

from modules.data_cleaner import nettoyer_releve, nettoyer_gl
from modules.utils import detecter_banque, detecter_periode


def charger_releve(uploaded_file) -> pd.DataFrame:
    """
    Charge un fichier Excel de relevé bancaire.
    Retourne un DataFrame nettoyé ou None en cas d'erreur.
    """
    if uploaded_file is None:
        return None
    
    try:
        # Lire le fichier Excel
        df = pd.read_excel(uploaded_file, engine='openpyxl')
        
        if df.empty:
            st.error(f"Le fichier {uploaded_file.name} est vide.")
            return None
        
        # Nettoyer selon le format
        df_clean = nettoyer_releve(df, uploaded_file.name)
        
        if df_clean is None or df_clean.empty:
            st.error(f"Impossible de traiter le fichier {uploaded_file.name}.")
            return None
        
        # Métadonnées
        df_clean.attrs['nom_fichier'] = uploaded_file.name
        df_clean.attrs['banque'] = detecter_banque(uploaded_file.name)
        df_clean.attrs['nb_lignes'] = len(df_clean)
        df_clean.attrs['periode'] = detecter_periode(df_clean)
        
        return df_clean
        
    except Exception as e:
        st.error(f"Erreur lors du chargement de {uploaded_file.name}: {str(e)}")
        return None


def charger_gl(uploaded_file, nom_entite: str) -> pd.DataFrame:
    """
    Charge un fichier Excel de Grand Livre Odoo pour une entité.
    """
    if uploaded_file is None:
        return None
    
    try:
        df = pd.read_excel(uploaded_file, engine='openpyxl')
        
        if df.empty:
            st.error(f"Le fichier GL {uploaded_file.name} est vide.")
            return None
        
        df_clean = nettoyer_gl(df, nom_entite)
        
        if df_clean is None or df_clean.empty:
            st.error(f"Impossible de traiter le fichier GL {uploaded_file.name}.")
            return None
        
        df_clean.attrs['nom_fichier'] = uploaded_file.name
        df_clean.attrs['entite'] = nom_entite
        df_clean.attrs['nb_lignes'] = len(df_clean)
        
        return df_clean
        
    except Exception as e:
        st.error(f"Erreur lors du chargement du GL {uploaded_file.name}: {str(e)}")
        return None


def charger_releve_depuis_chemin(chemin: str) -> pd.DataFrame:
    """
    Charge un relevé depuis un chemin de fichier local.
    Utile pour les exports/imports.
    """
    try:
        df = pd.read_excel(chemin, engine='openpyxl')
        nom_fichier = Path(chemin).name
        df_clean = nettoyer_releve(df, nom_fichier)
        if df_clean is not None:
            df_clean.attrs['nom_fichier'] = nom_fichier
            df_clean.attrs['banque'] = detecter_banque(nom_fichier)
            df_clean.attrs['nb_lignes'] = len(df_clean)
        return df_clean
    except Exception as e:
        print(f"Erreur chargement {chemin}: {e}")
        return None


def get_releves_combines(releves_dict: dict) -> pd.DataFrame:
    """
    Combine plusieurs relevés en un seul DataFrame.
    Utile pour le matching consolidé par entité.
    
    Args:
        releves_dict: dict {nom_fichier: df_clean}
    
    Returns:
        DataFrame combiné
    """
    if not releves_dict:
        return pd.DataFrame()
    
    frames = []
    for nom, df in releves_dict.items():
        if df is not None and not df.empty:
            df['fichier_source'] = nom
            frames.append(df)
    
    if frames:
        return pd.concat(frames, ignore_index=True)
    return pd.DataFrame()


def get_gl_combines(gls_dict: dict) -> pd.DataFrame:
    """
    Combine plusieurs GLs en un seul DataFrame.
    
    Args:
        gls_dict: dict {nom_entite: df_clean}
    
    Returns:
        DataFrame combiné
    """
    if not gls_dict:
        return pd.DataFrame()
    
    frames = []
    for entite, df in gls_dict.items():
        if df is not None and not df.empty:
            df['entite_source'] = entite
            frames.append(df)
    
    if frames:
        return pd.concat(frames, ignore_index=True)
    return pd.DataFrame()