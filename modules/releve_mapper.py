"""
UI et logique de mappage des relevés bancaires aux entités
Onglet 2 de l'application Streamlit
"""

import streamlit as st
import pandas as pd
from modules.db_manager import (
    save_mappage, delete_mappage,
    get_all_mappages, add_history
)
from modules.utils import detecter_banque, detecter_periode


ENTITES = [
    "DISTRIBUTION SA",
    "NUTRITION SA",
    "SERVICES SA",
    "ÉLEVAGE SA",
    "À DÉTERMINER"
]

ENTITES_SHORT = {
    "DISTRIBUTION SA": "DISTRIBUTION",
    "NUTRITION SA": "NUTRITION",
    "SERVICES SA": "SERVICES",
    "ÉLEVAGE SA": "ÉLEVAGE",
}


def get_entite_short(entite_long: str) -> str:
    """Convertit nom long en nom court."""
    return ENTITES_SHORT.get(entite_long, entite_long)


def afficher_interface_mappage(releves_dict: dict, gls_dict: dict, session_id):
    """
    Affiche l'interface de mappage des relevés aux entités.
    
    Args:
        releves_dict: dict {nom_fichier: df_clean} des relevés chargés
        gls_dict: dict {nom_entite: df_clean} des GLs chargés
        session_id: identifiant de la session de travail en cours
    """
    st.header("🗺️ Mappage Relevés → Entités")
    
    if not releves_dict:
        st.warning("Aucun relevé chargé. Revenez à l'onglet 1 pour charger des relevés.")
        return
    
    # Récupérer les mappages existants
    mappages_existants = get_all_mappages(session_id)
    mappages_map = {m['releve_name']: m['entite_assignee'] for m in mappages_existants}
    
    # Créer le tableau de mappage
    st.subheader("Assignez chaque relevé à une entité")
    st.caption("Un relevé bancaire = une seule entité (pas ligne par ligne). "
               "Exemple: 'Le relevé FH 2025 correspond aux opérations de DISTRIBUTION SA'")
    
    # Préparer les données pour le tableau
    rows_data = []
    for nom_fichier, df in releves_dict.items():
        banque = df.attrs.get('banque', detecter_banque(nom_fichier))
        periode = df.attrs.get('periode', detecter_periode(df))
        nb_lignes = len(df)
        entite_actuelle = mappages_map.get(nom_fichier, "À DÉTERMINER")
        rows_data.append({
            'fichier': nom_fichier,
            'banque': banque,
            'periode': periode,
            'lignes': nb_lignes,
            'entite': entite_actuelle
        })
    
    # Afficher avec des selectbox
    mapping_updated = False
    
    for i, row in enumerate(rows_data):
        col1, col2, col3, col4, col5, col6 = st.columns([3, 1.5, 2, 1, 2, 0.5])
        
        with col1:
            st.write(f"**{row['fichier']}**")
        with col2:
            st.write(f"🏦 {row['banque']}")
        with col3:
            st.write(f"📅 {row['periode']}")
        with col4:
            st.write(f"📊 {row['lignes']} lignes")
        with col5:
            # Utiliser une clé unique pour chaque selectbox
            key = f"mappage_{i}_{row['fichier']}"
            entite_key = f"entite_{i}"
            
            idx_default = 0
            if row['entite'] in ENTITES:
                idx_default = ENTITES.index(row['entite'])
            
            new_entite = st.selectbox(
                "Entité",
                options=ENTITES,
                index=idx_default,
                key=key,
                label_visibility="collapsed"
            )
            
            if new_entite != row['entite']:
                # Sauvegarder en DB
                save_mappage(
                    session_id, row['fichier'], row['banque'],
                    row['periode'], row['lignes'],
                    get_entite_short(new_entite)
                )
                row['entite'] = new_entite
                mapping_updated = True
                add_history(session_id, "MAPPAGE_MODIFIÉ",
                          get_entite_short(new_entite),
                          f"{row['fichier']} → {new_entite}")
        
        with col6:
            if st.button("❌", key=f"del_{i}_{row['fichier']}"):
                delete_mappage(session_id, row['fichier'])
                add_history(session_id, "MAPPAGE_SUPPRIMÉ", "", f"{row['fichier']}")
                st.rerun()
    
    st.divider()
    
    # Résumé des mappages
    st.subheader("📋 Résumé des mappages")
    
    # Compter par entité
    mappages_actuels = get_all_mappages(session_id)
    if mappages_actuels:
        df_mappages = pd.DataFrame(mappages_actuels)
        
        if not df_mappages.empty and 'entite_assignee' in df_mappages.columns:
            summary = df_mappages['entite_assignee'].value_counts().reset_index()
            summary.columns = ['Entité', 'Nombre de relevés']
            st.dataframe(summary, use_container_width=True)
        
        # Appliquer les mappages: associer chaque relevé à son GL
        if st.button("🔄 Appliquer les mappages et lancer le matching", type="primary"):
            st.session_state['mappages_appliques'] = True
            # Vérifier que tous les relevés ont une entité assignée (pas À DÉTERMINER)
            non_assignes = [m for m in mappages_actuels if m['entite_assignee'] == 'À DÉTERMINER']
            if non_assignes:
                st.warning(f"{len(non_assignes)} relevé(s) encore non assigné(s). "
                          f"Veuillez leur attribuer une entité.")
            else:
                st.success("✅ Tous les relevés sont mappés. Rendez-vous à l'onglet 3 pour le rapprochement détaillé.")
    else:
        st.info("Aucun mappage sauvegardé pour le moment.")
    
    return mapping_updated


def get_mapping_summary(session_id) -> dict:
    """
    Retourne un résumé du mappage pour affichage.
    """
    mappages = get_all_mappages(session_id)
    if not mappages:
        return {}
    
    summary = {}
    for m in mappages:
        entite = m['entite_assignee']
        if entite not in summary:
            summary[entite] = []
        summary[entite].append(m['releve_name'])
    
    return summary