"""
Persistance disque des fichiers GL / relevés chargés.

PROBLÈME RÉSOLU:
  Avant, les DataFrames issus des uploads (st.file_uploader) n'étaient
  gardés qu'en mémoire (st.session_state). Or Streamlit perd cette mémoire
  à chaque rafraîchissement de page, déconnexion réseau/WebSocket, ouverture
  d'un nouvel onglet, ou redémarrage de l'application — obligeant à tout
  réuploader.

SOLUTION:
  Dès qu'un fichier est chargé et nettoyé, on le sérialise immédiatement sur
  disque (data/uploads/<session_id>/...) et on référence son emplacement
  dans la table SQLite `fichiers_charges`. Au démarrage de l'application (ou
  chaque fois que le session_state Streamlit a été perdu), on restaure
  automatiquement tous les fichiers de la session active depuis le disque,
  sans aucune action de l'utilisateur.
"""

import pickle
from pathlib import Path

import pandas as pd

from modules.db_manager import (
    save_fichier_charge, get_fichiers_charges,
    delete_fichier_charge, delete_all_fichiers_charges
)

DATA_DIR = Path(__file__).parent.parent / "data" / "uploads"


def _nom_sur_disque(type_fichier: str, nom_fichier: str) -> str:
    """Construit un nom de fichier sûr pour le stockage disque."""
    safe = nom_fichier.replace("/", "_").replace("\\", "_")
    return f"{type_fichier}__{safe}.pkl"


def _chemin_pour(session_id, type_fichier: str, nom_fichier: str) -> Path:
    dossier = DATA_DIR / str(session_id)
    dossier.mkdir(parents=True, exist_ok=True)
    return dossier / _nom_sur_disque(type_fichier, nom_fichier)


def sauvegarder_fichier(session_id, type_fichier: str, nom_fichier: str,
                        df: pd.DataFrame, entite: str = "", banque: str = "",
                        periode: str = "") -> None:
    """
    Sérialise un DataFrame nettoyé sur disque et enregistre sa référence en DB.
    type_fichier: 'gl' ou 'releve'
    """
    if df is None:
        return
    chemin = _chemin_pour(session_id, type_fichier, nom_fichier)
    with open(chemin, "wb") as f:
        pickle.dump(df, f, protocol=pickle.HIGHEST_PROTOCOL)

    save_fichier_charge(
        session_id=session_id,
        type_fichier=type_fichier,
        nom_fichier=nom_fichier,
        chemin_donnees=str(chemin),
        entite=entite,
        banque=banque,
        periode=periode,
        nb_lignes=len(df)
    )


def supprimer_fichier(session_id, type_fichier: str, nom_fichier: str) -> None:
    """Supprime un fichier persisté (disque + référence DB)."""
    chemin = _chemin_pour(session_id, type_fichier, nom_fichier)
    try:
        chemin.unlink(missing_ok=True)
    except Exception:
        pass
    delete_fichier_charge(session_id, type_fichier, nom_fichier)


def reinitialiser_session(session_id) -> None:
    """Supprime tous les fichiers persistés (disque + DB) pour une session."""
    dossier = DATA_DIR / str(session_id)
    if dossier.exists():
        for f in dossier.glob("*.pkl"):
            try:
                f.unlink()
            except Exception:
                pass
    delete_all_fichiers_charges(session_id)


def restaurer_session(session_id) -> tuple[dict, dict]:
    """
    Reconstruit (gls, releves) depuis le disque pour la session donnée.
    Retourne deux dicts prêts à être injectés dans st.session_state.
    En cas de fichier manquant/corrompu, il est simplement ignoré (dégradation
    silencieuse — l'utilisateur peut re-uploader ce fichier précis).
    """
    gls = {}
    releves = {}

    # Récupération défensive de la liste des fichiers en DB
    try:
        fichiers = get_fichiers_charges(session_id)
    except Exception:
        fichiers = []

    if not fichiers:
        return gls, releves

    for f in fichiers:
        # S'assure que chaque élément est un dict et contient le chemin attendu
        if not isinstance(f, dict):
            continue

        # Supporter plusieurs noms possibles pour la colonne chemin (robustesse)
        chemin_str = f.get("chemin_donnees") or f.get("chemin") or f.get("chemin_donnee")
        if not chemin_str:
            continue

        chemin = Path(chemin_str)
        if not chemin.exists():
            continue
        try:
            with open(chemin, "rb") as fh:
                df = pickle.load(fh)
        except Exception:
            continue

        if not isinstance(df, pd.DataFrame):
            continue

        if f.get("type_fichier") == "gl":
            df.attrs["nom_fichier"] = f.get("nom_fichier", "")
            df.attrs["entite"] = f.get("entite", "")
            df.attrs["nb_lignes"] = len(df)
            gls[f.get("entite", "")] = df
        else:
            df.attrs["nom_fichier"] = f.get("nom_fichier", "")
            df.attrs["banque"] = f.get("banque", "")
            df.attrs["periode"] = f.get("periode", "")
            df.attrs["nb_lignes"] = len(df)
            releves[f.get("nom_fichier", "")] = df

    return gls, releves


def a_des_fichiers_persistes(session_id) -> bool:
    """Vérifie rapidement si une session a des fichiers persistés (sans les charger)."""
    try:
        fichiers = get_fichiers_charges(session_id)
        return bool(fichiers)
    except Exception:
        return False
