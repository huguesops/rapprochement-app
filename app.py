"""
Application Streamlit de Rapprochement Bancaire
Groupe SKAB Cameroun | Multi-Banques | Multi-Entités | 2025-2026

5 onglets:
  1. Upload & Configuration
  2. Mappage Relevés → Entités
  3. Rapprochement par Entité
  4. Synthèse & Ventilation
  5. Exports & Rapports
"""

import streamlit as st
import pandas as pd
from datetime import datetime
from pathlib import Path

# Configuration de la page
st.set_page_config(
    page_title="Rapprochement Bancaire SKAB",
    page_icon="🏦",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Initialisation des modules
from modules.db_manager import (
    init_db, get_active_session, get_all_mappages,
    get_matches, get_suspens, get_stats, add_history,
    update_suspens, delete_suspens
)
from modules.data_loader import charger_releve, charger_gl
from modules.releve_mapper import afficher_interface_mappage
from modules.reconciliation_engine import run_reconciliation_for_entite, run_all_reconciliations
from modules.reporting import afficher_boutons_exports
from modules.utils import formater_montant, formater_date, detecter_periode

# Initialiser la base de données au démarrage
if 'db_initialized' not in st.session_state:
    init_db()
    st.session_state.db_initialized = True
    st.session_state.session_id = get_active_session()

# Initialiser le session state
if 'gls' not in st.session_state:
    st.session_state.gls = {}  # {nom_entite: df_clean}
if 'releves' not in st.session_state:
    st.session_state.releves = {}  # {nom_fichier: df_clean}
if 'mappages_appliques' not in st.session_state:
    st.session_state.mappages_appliques = False
if 'reconciliation_results' not in st.session_state:
    st.session_state.reconciliation_results = {}
if 'tolerance_jours' not in st.session_state:
    st.session_state.tolerance_jours = 3
if 'seuil_levenshtein' not in st.session_state:
    st.session_state.seuil_levenshtein = 70


# ===== SIDEBAR =====
with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/2830/2830289.png", width=80)
    st.title("🏦 SKAB")
    st.caption("Groupe SKAB Cameroun")
    st.divider()
    
    st.subheader("Session en cours")
    st.info(f"Session #{st.session_state.session_id}")
    
    # Résumé rapide
    nb_gls = len(st.session_state.gls)
    nb_releves = len(st.session_state.releves)
    st.metric("📊 GLs chargés", nb_gls)
    st.metric("📋 Relevés chargés", nb_releves)
    
    # Nombre de lignes total
    total_lignes_releves = sum(len(df) for df in st.session_state.releves.values() if df is not None)
    total_lignes_gls = sum(len(df) for df in st.session_state.gls.values() if df is not None)
    st.metric("📝 Lignes relevés", total_lignes_releves)
    st.metric("📝 Écritures GL", total_lignes_gls)
    
    st.divider()
    
    # Paramètres rapides
    with st.expander("⚙️ Paramètres"):
        st.session_state.tolerance_jours = st.number_input(
            "Tolérance matching (jours)",
            min_value=0, max_value=30, value=st.session_state.tolerance_jours
        )
        st.session_state.seuil_levenshtein = st.slider(
            "Seuil Levenshtein (%)",
            min_value=50, max_value=100, value=st.session_state.seuil_levenshtein
        )
    
    # Bouton réinitialisation
    if st.button("🔄 Réinitialiser", use_container_width=True):
        for key in ['gls', 'releves', 'mappages_appliques', 'reconciliation_results']:
            if key in st.session_state:
                st.session_state[key] = {} if key not in ['mappages_appliques'] else False
        st.rerun()


# ===== TABS PRINCIPAUX =====
tabs = st.tabs([
    "📂 Upload & Configuration",
    "🗺️ Mappage Relevés → Entités",
    "🔍 Rapprochement par Entité",
    "📊 Synthèse & Ventilation",
    "📤 Exports & Rapports"
])


# ============================================================
# TAB 1: UPLOAD & CONFIGURATION
# ============================================================
with tabs[0]:
    st.header("📂 Upload & Configuration")
    st.markdown("**Étape 1 : Charger les 4 Grands Livres Odoo**")
    
    col_gl1, col_gl2 = st.columns(2)
    
    with col_gl1:
        gl_dist = st.file_uploader(
            "GL_DISTRIBUTION.xlsx", type=['xlsx'],
            key="gl_distribution"
        )
        if gl_dist and gl_dist.name not in st.session_state.gls:
            df = charger_gl(gl_dist, "DISTRIBUTION")
            if df is not None:
                st.session_state.gls["DISTRIBUTION"] = df
                st.success(f"✅ DISTRIBUTION: {len(df)} écritures")
                add_history(st.session_state.session_id, "GL_CHARGÉ", "DISTRIBUTION", f"{len(df)} lignes")
        
        gl_services = st.file_uploader(
            "GL_SERVICES.xlsx", type=['xlsx'],
            key="gl_services"
        )
        if gl_services and gl_services.name not in st.session_state.gls:
            df = charger_gl(gl_services, "SERVICES")
            if df is not None:
                st.session_state.gls["SERVICES"] = df
                st.success(f"✅ SERVICES: {len(df)} écritures")
                add_history(st.session_state.session_id, "GL_CHARGÉ", "SERVICES", f"{len(df)} lignes")
    
    with col_gl2:
        gl_nutri = st.file_uploader(
            "GL_NUTRITION.xlsx", type=['xlsx'],
            key="gl_nutrition"
        )
        if gl_nutri and gl_nutri.name not in st.session_state.gls:
            df = charger_gl(gl_nutri, "NUTRITION")
            if df is not None:
                st.session_state.gls["NUTRITION"] = df
                st.success(f"✅ NUTRITION: {len(df)} écritures")
                add_history(st.session_state.session_id, "GL_CHARGÉ", "NUTRITION", f"{len(df)} lignes")
        
        gl_eleve = st.file_uploader(
            "GL_ÉLEVAGE.xlsx", type=['xlsx'],
            key="gl_eleve"
        )
        if gl_eleve and gl_eleve.name not in st.session_state.gls:
            df = charger_gl(gl_eleve, "ÉLEVAGE")
            if df is not None:
                st.session_state.gls["ÉLEVAGE"] = df
                st.success(f"✅ ÉLEVAGE: {len(df)} écritures")
                add_history(st.session_state.session_id, "GL_CHARGÉ", "ÉLEVAGE", f"{len(df)} lignes")
    
    st.divider()
    
    # Étape 2: Charger relevés bancaires
    st.markdown("**Étape 2 : Charger les relevés bancaires**")
    st.caption("Chargez les fichiers Excel de vos relevés bancaires (UNICS, FH, BGFI, CEPAC, etc.)")
    
    uploaded_releve = st.file_uploader(
        "Déposez ou sélectionnez un fichier de relevé bancaire",
        type=['xlsx'],
        key="releve_upload",
        help="Formats supportés: UNICS, FH, BGFI, CEPAC, ADVANS, MUPECI, SCB, BICEC, etc."
    )
    
    if uploaded_releve:
        if uploaded_releve.name not in st.session_state.releves:
            df = charger_releve(uploaded_releve)
            if df is not None:
                st.session_state.releves[uploaded_releve.name] = df
                banque = df.attrs.get('banque', '')
                st.success(f"✅ {uploaded_releve.name} chargé ({len(df)} lignes, banque: {banque})")
                add_history(st.session_state.session_id, "RELEVÉ_CHARGÉ", "",
                          f"{uploaded_releve.name}: {len(df)} lignes")
                st.rerun()
    
    # Liste des relevés chargés
    if st.session_state.releves:
        st.markdown(f"**Relevés chargés ({len(st.session_state.releves)}):**")
        
        for nom_fichier, df in st.session_state.releves.items():
            banque = df.attrs.get('banque', '')
            nb_lignes = len(df)
            periode = df.attrs.get('periode', detecter_periode(df))
            
            cols = st.columns([3, 1.5, 2, 1, 0.5])
            with cols[0]:
                st.write(f"✅ **{nom_fichier}**")
            with cols[1]:
                st.write(f"🏦 {banque}")
            with cols[2]:
                st.write(f"📅 {periode}")
            with cols[3]:
                st.write(f"📊 {nb_lignes} lignes")
            with cols[4]:
                if st.button("❌", key=f"del_rel_{nom_fichier}"):
                    del st.session_state.releves[nom_fichier]
                    add_history(st.session_state.session_id, "RELEVÉ_SUPPRIMÉ", "", nom_fichier)
                    st.rerun()
    else:
        st.info("Aucun relevé chargé pour le moment.")
    
    st.divider()
    
    # Étape 3: Paramètres
    st.markdown("**Étape 3 : Paramètres de matching**")
    col_param1, col_param2 = st.columns(2)
    with col_param1:
        st.session_state.tolerance_jours = st.number_input(
            "Tolérance en jours pour le matching date",
            min_value=0, max_value=30, value=st.session_state.tolerance_jours,
            key="tol_jours_tab1"
        )
    with col_param2:
        st.session_state.seuil_levenshtein = st.slider(
            "Seuil de similarité Levenshtein (%)",
            min_value=50, max_value=100, value=st.session_state.seuil_levenshtein,
            key="seuil_lev_tab1"
        )
    
    # Statistiques de chargement
    st.divider()
    st.subheader("📊 Statistiques de chargement")
    
    col_stat1, col_stat2, col_stat3, col_stat4 = st.columns(4)
    with col_stat1:
        st.metric("Relevés chargés", len(st.session_state.releves))
    with col_stat2:
        total_lignes = sum(len(df) for df in st.session_state.releves.values() if df is not None)
        st.metric("Total lignes relevés", total_lignes)
    with col_stat3:
        st.metric("GLs chargés", len(st.session_state.gls))
    with col_stat4:
        total_gl = sum(len(df) for df in st.session_state.gls.values() if df is not None)
        st.metric("Total écritures GL", total_gl)
    
    if len(st.session_state.gls) == 4 and len(st.session_state.releves) > 0:
        st.success("✅ Prêt pour le mappage → Allez à l'onglet 2")
    else:
        if len(st.session_state.gls) < 4:
            st.warning(f"⚠️ {4 - len(st.session_state.gls)} GL(s) manquant(s). Chargez les 4 GLs.")
        if len(st.session_state.releves) == 0:
            st.warning("⚠️ Aucun relevé chargé. Chargez au moins un relevé bancaire.")


# ============================================================
# TAB 2: MAPPAGE RELEVÉS → ENTITÉS
# ============================================================
with tabs[1]:
    if len(st.session_state.releves) == 0:
        st.warning("⚠️ Veuillez d'abord charger des relevés bancaires dans l'onglet 1.")
    else:
        afficher_interface_mappage(st.session_state.releves, st.session_state.gls)
        
        # Lancer le matching si demandé
        if st.session_state.get('mappages_appliques', False):
            with st.spinner("🔍 Lancement du matching pour toutes les entités..."):
                results = run_all_reconciliations(
                    st.session_state.gls,
                    st.session_state.releves,
                    st.session_state.tolerance_jours,
                    st.session_state.seuil_levenshtein / 100.0
                )
                st.session_state.reconciliation_results = results
                st.success("✅ Matching terminé! Consultez les résultats dans l'onglet 3.")
                st.session_state.mappages_appliques = True


# ============================================================
# TAB 3: RAPPROCHEMENT PAR ENTITÉ
# ============================================================
with tabs[2]:
    st.header("🔍 Rapprochement par Entité")
    
    if not st.session_state.gls:
        st.warning("⚠️ Veuillez d'abord charger les GLs dans l'onglet 1.")
    elif not st.session_state.releves:
        st.warning("⚠️ Veuillez d'abord charger les relevés dans l'onglet 1.")
    else:
        # Sélecteur d'entité
        entites_disponibles = list(st.session_state.gls.keys())
        if not entites_disponibles:
            st.warning("Aucune entité disponible.")
        else:
            entite_selectionnee = st.selectbox(
                "Sélectionnez une entité",
                options=entites_disponibles,
                key="entite_select"
            )
            
            # Bouton pour lancer/re-lancer le matching
            col_match1, col_match2 = st.columns([3, 1])
            with col_match2:
                if st.button("🔄 Lancer le matching", type="primary", use_container_width=True):
                    with st.spinner(f"🔍 Matching pour {entite_selectionnee}..."):
                        # Récupérer les relevés mappés à cette entité
                        mappages = get_all_mappages(st.session_state.session_id)
                        releves_entite_list = []
                        for m in mappages:
                            if m['entite_assignee'] == entite_selectionnee:
                                if m['releve_name'] in st.session_state.releves:
                                    releves_entite_list.append(st.session_state.releves[m['releve_name']])
                        
                        if releves_entite_list:
                            releves_combines = pd.concat(releves_entite_list, ignore_index=True)
                        else:
                            releves_combines = pd.DataFrame()
                        
                        result = run_reconciliation_for_entite(
                            entite_selectionnee,
                            releves_combines,
                            st.session_state.gls.get(entite_selectionnee),
                            st.session_state.tolerance_jours,
                            st.session_state.seuil_levenshtein / 100.0
                        )
                        st.session_state.reconciliation_results[entite_selectionnee] = result
                        st.success("✅ Matching terminé!")
                        st.rerun()
            
            # Afficher les résultats
            gl_df = st.session_state.gls.get(entite_selectionnee)
            if gl_df is None or gl_df.empty:
                st.warning(f"Aucun GL chargé pour {entite_selectionnee}.")
            else:
                # Récupérer les résultats depuis la DB
                matches = get_matches(st.session_state.session_id, entite_selectionnee)
                suspens = get_suspens(st.session_state.session_id, entite_selectionnee)
                
                # Statistiques
                stats = get_stats_for_entite(st.session_state.session_id, entite_selectionnee)
                nb_matches = stats.get('nb_matches', 0)
                nb_suspens = stats.get('nb_suspens', 0)
                total = nb_matches + nb_suspens
                taux = round(nb_matches / max(total, 1) * 100, 1)
                
                # Nombre de lignes relevés pour cette entité
                mappages = get_all_mappages(st.session_state.session_id)
                lignes_releves_entite = 0
                for m in mappages:
                    if m['entite_assignee'] == entite_selectionnee and m['releve_name'] in st.session_state.releves:
                        lignes_releves_entite += len(st.session_state.releves[m['releve_name']])
                
                # SECTION A: STATISTIQUES
                st.subheader("📈 Statistiques")
                col_s1, col_s2, col_s3, col_s4, col_s5 = st.columns(5)
                with col_s1:
                    st.metric("📋 Lignes relevés", lignes_releves_entite)
                with col_s2:
                    st.metric("📝 Écritures GL", len(gl_df))
                with col_s3:
                    st.metric("✅ Appairés", nb_matches)
                with col_s4:
                    st.metric("⚠️ Suspens", nb_suspens)
                with col_s5:
                    st.metric("🎯 Taux", f"{taux}%")
                
                # Répartition par type de match
                if stats.get('matches_par_type'):
                    st.caption("Répartition par type de match: " + 
                              " | ".join([f"{k}: {v}" for k, v in stats['matches_par_type'].items()]))
                
                st.divider()
                
                # SECTION B: APPAIRAGES VALIDÉS
                st.subheader("✅ Appairages Validés")
                if matches:
                    df_matches = pd.DataFrame(matches)
                    display_cols = ['date_operation', 'banque', 'libelle_releve', 'montant', 'type_match', 'confiance']
                    display_cols = [c for c in display_cols if c in df_matches.columns]
                    
                    if not df_matches.empty:
                        # Formater pour l'affichage
                        df_display = df_matches[display_cols].copy()
                        if 'montant' in df_display.columns:
                            df_display['montant'] = df_display['montant'].apply(
                                lambda x: f"{x:,.0f}".replace(",", " ") if pd.notna(x) else ""
                            )
                        if 'confiance' in df_display.columns:
                            df_display['confiance'] = df_display['confiance'].apply(
                                lambda x: f"{x*100:.0f}%" if pd.notna(x) and isinstance(x, (int, float)) and x <= 1 else 
                                         f"{x:.0f}%" if pd.notna(x) else ""
                            )
                        
                        df_display.columns = ['Date', 'Banque', 'Libellé', 'Montant', 'Type', 'Confiance']
                        st.dataframe(df_display, use_container_width=True, height=300)
                else:
                    st.info("Aucun appairage pour le moment. Lancez le matching.")
                
                st.divider()
                
                # SECTION C: SUSPENS À INVESTIGUER
                st.subheader("⚠️ Suspens à Investiguer")
                if suspens:
                    for s in suspens:
                        with st.expander(f"🔴 {formater_date(s.get('date_operation', ''))} | "
                                       f"{s.get('libelle', '')[:60]}... | "
                                       f"{formater_montant(s.get('montant', 0))}"):
                            
                            col_d1, col_d2 = st.columns(2)
                            with col_d1:
                                st.write(f"**Date:** {formater_date(s.get('date_operation', ''))}")
                                st.write(f"**Type:** {s.get('type_suspens', '')}")
                                st.write(f"**Source:** {s.get('source', '')}")
                                st.write(f"**Libellé:** {s.get('libelle', '')}")
                            with col_d2:
                                st.write(f"**Montant:** {formater_montant(s.get('montant', 0))}")
                                st.write(f"**Banque:** {s.get('banque', '')}")
                                st.write(f"**Statut:** {s.get('statut', 'Ouvert')}")
                            
                            # Sélecteur de motif
                            motifs = [
                                "À éclaircir",
                                "Chèque en attente",
                                "Virement futur",
                                "Erreur GL",
                                "Erreur Relevé",
                                "Reversal",
                                "Autre"
                            ]
                            
                            idx_motif = 0
                            if s.get('motif') in motifs:
                                idx_motif = motifs.index(s['motif'])
                            
                            nouveau_motif = st.selectbox(
                                "Motif",
                                options=motifs,
                                index=idx_motif,
                                key=f"motif_{s['suspens_id']}"
                            )
                            
                            observations = st.text_area(
                                "Observations",
                                value=s.get('observations', ''),
                                key=f"obs_{s['suspens_id']}"
                            )
                            
                            nouveau_statut = st.selectbox(
                                "Statut",
                                options=["Ouvert", "Pointé"],
                                index=0 if s.get('statut') == 'Ouvert' else 1,
                                key=f"statut_{s['suspens_id']}"
                            )
                            
                            col_btn1, col_btn2 = st.columns([1, 1])
                            with col_btn1:
                                if st.button("💾 Sauvegarder", key=f"save_{s['suspens_id']}"):
                                    update_suspens(
                                        s['suspens_id'],
                                        motif=nouveau_motif,
                                        observations=observations,
                                        statut=nouveau_statut
                                    )
                                    add_history(st.session_state.session_id, "SUSPENS_MODIFIÉ",
                                              entite_selectionnee,
                                              f"Suspens #{s['suspens_id']}: {nouveau_motif}")
                                    st.success("✅ Sauvegardé!")
                                    st.rerun()
                            with col_btn2:
                                if st.button("❌ Supprimer", key=f"del_{s['suspens_id']}"):
                                    delete_suspens(s['suspens_id'])
                                    add_history(st.session_state.session_id, "SUSPENS_SUPPRIMÉ",
                                              entite_selectionnee, f"Suspens #{s['suspens_id']}")
                                    st.rerun()
                else:
                    if matches:
                        st.success("🎉 Aucun suspens! Toutes les opérations sont appairées.")
                    else:
                        st.info("Aucune donnée. Lancez le matching pour voir les résultats.")


# ============================================================
# TAB 4: SYNTHÈSE & VENTILATION
# ============================================================
with tabs[3]:
    st.header("📊 Synthèse & Ventilation")
    
    if not st.session_state.releves:
        st.warning("⚠️ Veuillez d'abord charger des données dans l'onglet 1.")
    else:
        stats = get_stats(st.session_state.session_id)
        
        # Tableau de synthèse
        st.subheader("Vue d'ensemble des 4 entités")
        
        entites = ['DISTRIBUTION', 'NUTRITION', 'SERVICES', 'ÉLEVAGE']
        synth_data = []
        
        for entite in entites:
            nb_matches = stats.get('matches_par_entite', {}).get(entite, 0)
            nb_suspens = stats.get('suspens_par_entite', {}).get(entite, 0)
            total = nb_matches + nb_suspens
            taux = round(nb_matches / max(total, 1) * 100, 1) if total > 0 else 0
            
            # Compter les lignes relevés pour cette entité
            mappages = get_all_mappages(st.session_state.session_id)
            lignes_releves = 0
            banques = set()
            for m in mappages:
                if m['entite_assignee'] == entite and m['releve_name'] in st.session_state.releves:
                    lignes_releves += len(st.session_state.releves[m['releve_name']])
                    banques.add(m.get('banque', ''))
            
            synth_data.append({
                'Entité': entite,
                'Relevés': lignes_releves,
                'Banques': ', '.join(sorted(banques)) if banques else '-',
                'Appairés': nb_matches,
                'Suspens': nb_suspens,
                'Total': total,
                '% OK': f"{taux}%"
            })
        
        # Total
        total_releves = sum(row['Relevés'] for row in synth_data)
        total_matches = sum(row['Appairés'] for row in synth_data)
        total_suspens = sum(row['Suspens'] for row in synth_data)
        total_global = total_matches + total_suspens
        taux_global = round(total_matches / max(total_global, 1) * 100, 1)
        
        synth_data.append({
            'Entité': '**TOTAL GROUPE**',
            'Relevés': total_releves,
            'Banques': '-',
            'Appairés': total_matches,
            'Suspens': total_suspens,
            'Total': total_global,
            '% OK': f"{taux_global}%"
        })
        
        df_synth = pd.DataFrame(synth_data)
        st.dataframe(df_synth, use_container_width=True, hide_index=True)
        
        st.divider()
        
        # Graphiques
        st.subheader("📈 Visualisations")
        
        col_chart1, col_chart2 = st.columns(2)
        
        with col_chart1:
            st.markdown("**Taux d'appairage par entité**")
            if synth_data:
                chart_data = pd.DataFrame(synth_data[:-1])  # Exclure total
                if not chart_data.empty and '% OK' in chart_data.columns:
                    taux_values = chart_data['% OK'].str.replace('%', '').astype(float)
                    import plotly.express as px
                    fig = px.bar(
                        chart_data, x='Entité', y=taux_values,
                        text=taux_values.apply(lambda x: f"{x}%"),
                        color='Entité',
                        color_discrete_sequence=px.colors.qualitative.Set2,
                        labels={'y': 'Taux d\'appairage (%)'}
                    )
                    fig.update_traces(textposition='outside')
                    fig.update_layout(showlegend=False, height=350)
                    st.plotly_chart(fig, use_container_width=True)
                else:
                    st.info("Données insuffisantes pour le graphique.")
        
        with col_chart2:
            st.markdown("**Suspens par motif**")
            suspens_motifs = stats.get('suspens_par_motif', {})
            if suspens_motifs:
                import plotly.express as px
                df_motifs = pd.DataFrame(
                    list(suspens_motifs.items()),
                    columns=['Motif', 'Nombre']
                )
                fig = px.pie(
                    df_motifs, values='Nombre', names='Motif',
                    color_discrete_sequence=px.colors.qualitative.Set3
                )
                fig.update_layout(height=350)
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("Aucun suspens à afficher.")
        
        st.divider()
        
        # Détail des suspens par entité
        st.subheader("📋 Détail des suspens par entité")
        tab_entites = st.tabs(entites)
        
        for i, entite in enumerate(entites):
            with tab_entites[i]:
                suspens = get_suspens(st.session_state.session_id, entite)
                if suspens:
                    df_susp = pd.DataFrame(suspens)
                    cols = ['date_operation', 'type_suspens', 'libelle', 'montant', 'motif', 'statut']
                    cols = [c for c in cols if c in df_susp.columns]
                    if cols:
                        df_display = df_susp[cols].copy()
                        if 'montant' in df_display.columns:
                            df_display['montant'] = df_display['montant'].apply(
                                lambda x: f"{x:,.0f}".replace(",", " ") if pd.notna(x) else ""
                            )
                        df_display.columns = ['Date', 'Type', 'Libellé', 'Montant', 'Motif', 'Statut']
                        st.dataframe(df_display, use_container_width=True)
                else:
                    st.success(f"✅ {entite} : Aucun suspens.")


# ============================================================
# TAB 5: EXPORTS & RAPPORTS
# ============================================================
with tabs[4]:
    st.header("📤 Exports & Rapports")
    
    if not st.session_state.releves:
        st.warning("⚠️ Veuillez d'abord charger des données et effectuer le rapprochement.")
    else:
        # Vérifier qu'il y a des résultats
        stats = get_stats(st.session_state.session_id)
        total_matches = stats.get('total_matches', 0)
        
        if total_matches == 0:
            st.warning("⚠️ Aucun résultat de rapprochement trouvé. "
                      "Veillez à mapper les relevés (onglet 2) et lancer le matching (onglet 3).")
        else:
            st.success(f"✅ {total_matches} appairages et {stats.get('total_suspens', 0)} suspens disponibles pour export.")
            
            # Afficher les boutons d'export
            afficher_boutons_exports(st.session_state.session_id)
            
            st.divider()
            
            # Aperçu de l'historique
            st.subheader("📜 Historique des actions")
            from modules.db_manager import get_history
            history = get_history(st.session_state.session_id, limit=50)
            if history:
                df_history = pd.DataFrame(history)
                cols = ['timestamp', 'action', 'entite', 'details']
                cols = [c for c in cols if c in df_history.columns]
                if cols:
                    df_display = df_history[cols].copy()
                    df_display.columns = ['Date', 'Action', 'Entité', 'Détails']
                    st.dataframe(df_display, use_container_width=True, height=300)


# ===== FOOTER =====
st.divider()
st.caption(f"🏦 Application de Rapprochement Bancaire SKAB Cameroun | "
          f"Session #{st.session_state.session_id} | "
          f"Dernière actualisation: {datetime.now().strftime('%H:%M:%S')}")