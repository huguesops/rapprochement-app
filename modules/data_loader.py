"""
Chargement des fichiers Excel: releves bancaires multi-format + GLs Odoo
Gere les Formats variés: UNICS, FH, BGFI, CEPAC, ADVANS, etc.
"""

import pandas as pd
import streamlit as st
from pathlib import Path

from modules.data_cleaner import nettoyer_releve, nettoyer_gl
from modules.utils import detecter_banque, detecter_periode


def charger_releve(uploaded_file) -> pd.DataFrame | None:
    """Charge un fichier Excel de releve bancaire."""
    if uploaded_file is None:
        return None

    try:
        df = pd.read_excel(uploaded_file, engine='openpyxl')

        if not isinstance(df, pd.DataFrame) or (hasattr(df, 'empty') and df.empty):
            st.error(f"Le fichier {uploaded_file.name} est vide ou invalide.")
            return None

        df_clean = nettoyer_releve(df, uploaded_file.name)

        if df_clean is None:
            st.error(f"Impossible de traiter le fichier {uploaded_file.name}: le nettoyage a retourne None.")
            return None

        if hasattr(df_clean, 'empty') and df_clean.empty:
            st.error(f"Impossible de traiter le fichier {uploaded_file.name}: le resultat est vide.")
            return None

        df_clean.attrs['nom_fichier'] = uploaded_file.name
        df_clean.attrs['banque'] = detecter_banque(uploaded_file.name)
        df_clean.attrs['nb_lignes'] = len(df_clean)
        df_clean.attrs['periode'] = detecter_periode(df_clean)

        return df_clean

    except Exception as e:
        st.error(f"Erreur lors du chargement de {uploaded_file.name}: {str(e)}")
        import traceback
        st.write(traceback.format_exc())
        return None


def charger_gl(uploaded_file, nom_entite: str) -> pd.DataFrame | None:
    """Charge un fichier Excel de Grand Livre Odoo pour une entité."""
    if uploaded_file is None:
        return None

    try:
        df = pd.read_excel(uploaded_file, engine='openpyxl')

        if not isinstance(df, pd.DataFrame) or (hasattr(df, 'empty') and df.empty):
            st.error(f"Le fichier GL {uploaded_file.name} est vide ou invalide.")
            return None

        df_clean = nettoyer_gl(df, nom_entite)

        if df_clean is None:
            st.error(f"Impossible de traiter le fichier GL {uploaded_file.name}: nettoyage a retourne None.")
            if hasattr(df, 'columns'):
                with st.expander("🔍 Détails techniques (colonnes détectées)"):
                    st.write(list(df.columns))
            return None

        df_clean.attrs['nom_fichier'] = uploaded_file.name
        df_clean.attrs['entite'] = nom_entite
        df_clean.attrs['nb_lignes'] = len(df_clean)

        return df_clean

    except Exception as e:
        st.error(f"Erreur lors du chargement du GL {uploaded_file.name}: {str(e)}")
        import traceback
        st.write(traceback.format_exc())
        return None


def charger_releve_depuis_chemin(chemin: str) -> pd.DataFrame | None:
    """Charge un releve depuis un chemin de fichier local."""
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


def get_releves_combines(releves_dict: dict) -> pd.DataFrame | None:
    """Combine plusieurs releves en un seul DataFrame."""
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


def get_gl_combines(gls_dict: dict) -> pd.DataFrame | None:
    """Combine plusieurs GLs en un seul DataFrame."""
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
