"""
Application Streamlit de Rapprochement Bancaire
Groupe SKAB Cameroun | Multi-Banques | Multi-Entités | 2025-2026

IMPORTANT — architecture réelle: les 4 entités partagent les mêmes comptes
bancaires. Un relevé peut donc contenir des opérations de plusieurs
entités mélangées: il n'y a PAS de mappage manuel "ce relevé = cette
entité". L'entité de chaque opération est déterminée automatiquement par
le rapprochement lui-même (comparaison de chaque ligne de relevé aux 4 GL
à la fois — voir modules/reconciliation_engine.py).

5 onglets:
  1. Upload & Configuration
  2. Rapprochement Global (détection automatique de l'entité)
  3. Rapprochement par Entité (revue + investigation des suspens)
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
    init_db, get_active_session, get_all_sessions,
    get_session, create_session,
    get_matches, get_suspens, get_stats, get_stats_for_entite, add_history,
    update_suspens, delete_suspens
)
from modules.data_loader import charger_releve, charger_gl
from modules.reconciliation_engine import run_global_reconciliation, NON_DETERMINEE
from modules.reporting import afficher_boutons_exports
from modules.utils import formater_montant, formater_date, detecter_periode
from modules import persistence

ENTITES_GL = ['DISTRIBUTION', 'NUTRITION', 'SERVICES', 'ÉLEVAGE']

# Initialiser la base de données au démarrage
if 'db_initialized' not in st.session_state:
    init_db()
    st.session_state.db_initialized = True

# ----------------------------------------------------------------------
# Résolution de la session de travail
# ----------------------------------------------------------------------
# IMPORTANT: avant, la session était choisie via get_active_session(), qui
# renvoie TOUJOURS la même session pour TOUT LE MONDE. Résultat: si un
# collègue ouvre l'app ailleurs, charge un fichier ou clique sur
# "Réinitialiser", cela affecte immédiatement tous les autres utilisateurs —
# ce qui ressemble exactement à des "fichiers qui disparaissent par
# moments". On mémorise maintenant la session choisie dans l'URL
# (?session=ID), stable pour un même utilisateur à travers les
# rafraîchissements de page, mais indépendante d'un utilisateur à l'autre
# tant qu'ils n'ouvrent pas explicitement le même lien.
if 'session_id' not in st.session_state:
    session_depuis_url = st.query_params.get("session")
    session_valide = None
    if session_depuis_url:
        try:
            candidat = int(session_depuis_url)
            if get_session(candidat):
                session_valide = candidat
        except ValueError:
            session_valide = None

    if session_valide is None:
        session_valide = get_active_session()

    st.session_state.session_id = session_valide
    st.query_params["session"] = str(session_valide)

# Initialiser le session state
# NB: st.session_state est perdu à chaque rafraîchissement de page, coupure
# réseau/WebSocket ou nouvel onglet. C'est la 2e cause des "fichiers qui
# disparaissent". On restaure donc automatiquement depuis le disque
# (voir modules/persistence.py) dès que ce state n'existe plus.
if 'gls' not in st.session_state or 'releves' not in st.session_state:
    gls_restaures, releves_restaures = persistence.restaurer_session(st.session_state.session_id)
    st.session_state.gls = gls_restaures
    st.session_state.releves = releves_restaures
    if gls_restaures or releves_restaures:
        st.session_state.donnees_restaurees = True

if 'reconciliation_results' not in st.session_state:
    st.session_state.reconciliation_results = {}
if 'tolerance_jours' not in st.session_state:
    st.session_state.tolerance_jours = 3
if 'seuil_levenshtein' not in st.session_state:
    st.session_state.seuil_levenshtein = 70
if 'uploader_reset_counter' not in st.session_state:
    st.session_state.uploader_reset_counter = 0

# Bannière d'information si des données ont été restaurées automatiquement
if st.session_state.pop('donnees_restaurees', False):
    st.toast(
        f"🔄 {len(st.session_state.gls)} GL(s) et {len(st.session_state.releves)} relevé(s) "
        f"restaurés automatiquement — pas besoin de réuploader.",
        icon="✅"
    )


# ===== SIDEBAR =====
with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/2830/2830289.png", width=80)
    st.title("🏦 SKAB")
    st.caption("Groupe SKAB Cameroun")
    st.divider()

    st.subheader("Session de travail")

    session_courante = get_session(st.session_state.session_id) or {}
    st.info(f"📌 {session_courante.get('nom') or f'Session #{st.session_state.session_id}'}")

    with st.expander("🔀 Changer / créer une session"):
        st.caption(
            "Chaque session est isolée: ses fichiers, appairages et suspens "
            "ne sont visibles que par ceux qui ouvrent ce même lien de session. "
            "Partagez l'URL de la page à vos collègues pour travailler ensemble "
            "sur la même session."
        )

        toutes_sessions = get_all_sessions()
        options = {
            f"{s['nom'] or ('Session #' + str(s['session_id']))} "
            f"({s['created_at'][:16] if s.get('created_at') else ''})": s['session_id']
            for s in toutes_sessions
        }
        libelles = list(options.keys())
        session_actuelle_idx = 0
        for idx, s in enumerate(toutes_sessions):
            if s['session_id'] == st.session_state.session_id:
                session_actuelle_idx = idx
                break

        if libelles:
            choix = st.selectbox("Reprendre une session existante", libelles, index=session_actuelle_idx)
            session_choisie = options[choix]
            if st.button("↪️ Ouvrir cette session", use_container_width=True):
                if session_choisie != st.session_state.session_id:
                    st.query_params["session"] = str(session_choisie)
                    for key in ['session_id', 'gls', 'releves', 'reconciliation_results']:
                        st.session_state.pop(key, None)
                    st.rerun()

        st.divider()
        nouveau_nom = st.text_input(
            "Nom de la nouvelle session", placeholder="Ex: Rapprochement Mars 2025"
        )
        if st.button("➕ Créer une nouvelle session", use_container_width=True):
            nouveau_id = create_session(nom=nouveau_nom.strip())
            st.query_params["session"] = str(nouveau_id)
            for key in ['session_id', 'gls', 'releves', 'reconciliation_results']:
                st.session_state.pop(key, None)
            st.rerun()

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
    st.caption("⚠️ Efface tous les fichiers chargés (GL + relevés), "
              "les appairages et les suspens de **cette session**. Irréversible. "
              "(Pour repartir de zéro sans toucher au travail existant, créez plutôt "
              "une nouvelle session ci-dessus.)")
    if st.button("🗑️ Vider cette session", use_container_width=True):
        # Effacer les fichiers persistés sur disque + en DB
        persistence.reinitialiser_session(st.session_state.session_id)
        for key in ['gls', 'releves', 'reconciliation_results']:
            if key in st.session_state:
                st.session_state[key] = {}
        # Forcer le remontage des widgets file_uploader (sinon Streamlit garde
        # le fichier précédemment sélectionné visible dans le widget)
        st.session_state.uploader_reset_counter += 1
        st.success("Session réinitialisée.")
        st.rerun()


# ===== TABS PRINCIPAUX =====
tabs = st.tabs([
    "📂 Upload & Configuration",
    "🔍 Rapprochement Global",
    "🔎 Rapprochement par Entité",
    "📊 Synthèse & Ventilation",
    "📤 Exports & Rapports"
])


# ============================================================
# TAB 1: UPLOAD & CONFIGURATION
# ============================================================
with tabs[0]:
    st.header("📂 Upload & Configuration")

    if st.session_state.gls or st.session_state.releves:
        st.caption("💾 Les fichiers chargés sont automatiquement sauvegardés — "
                  "pas de risque de perte en cas de rafraîchissement de page.")

    st.markdown("**Étape 1 : Charger les 4 Grands Livres Odoo**")

    def _gl_deja_a_jour(entite: str, uploaded_file) -> bool:
        """True si ce fichier (même nom) est déjà chargé pour cette entité."""
        df_existant = st.session_state.gls.get(entite)
        if df_existant is None:
            return False
        return df_existant.attrs.get('nom_fichier') == uploaded_file.name

    def _traiter_upload_gl(uploaded_file, entite: str):
        if uploaded_file is None or _gl_deja_a_jour(entite, uploaded_file):
            return
        df = charger_gl(uploaded_file, entite)
        if df is not None:
            st.session_state.gls[entite] = df
            persistence.sauvegarder_fichier(
                st.session_state.session_id, "gl", uploaded_file.name, df, entite=entite
            )
            st.success(f"✅ {entite}: {len(df)} écritures (sauvegardé)")
            add_history(st.session_state.session_id, "GL_CHARGÉ", entite, f"{len(df)} lignes")
            st.rerun()

    uc = st.session_state.uploader_reset_counter
    col_gl1, col_gl2 = st.columns(2)

    with col_gl1:
        gl_dist = st.file_uploader(
            "GL_DISTRIBUTION.xlsx", type=['xlsx'], key=f"gl_distribution_{uc}"
        )
        _traiter_upload_gl(gl_dist, "DISTRIBUTION")
        if "DISTRIBUTION" in st.session_state.gls:
            st.caption(f"✅ Chargé: {st.session_state.gls['DISTRIBUTION'].attrs.get('nom_fichier', '')} "
                      f"({len(st.session_state.gls['DISTRIBUTION'])} écritures)")

        gl_services = st.file_uploader(
            "GL_SERVICES.xlsx", type=['xlsx'], key=f"gl_services_{uc}"
        )
        _traiter_upload_gl(gl_services, "SERVICES")
        if "SERVICES" in st.session_state.gls:
            st.caption(f"✅ Chargé: {st.session_state.gls['SERVICES'].attrs.get('nom_fichier', '')} "
                      f"({len(st.session_state.gls['SERVICES'])} écritures)")

    with col_gl2:
        gl_nutri = st.file_uploader(
            "GL_NUTRITION.xlsx", type=['xlsx'], key=f"gl_nutrition_{uc}"
        )
        _traiter_upload_gl(gl_nutri, "NUTRITION")
        if "NUTRITION" in st.session_state.gls:
            st.caption(f"✅ Chargé: {st.session_state.gls['NUTRITION'].attrs.get('nom_fichier', '')} "
                      f"({len(st.session_state.gls['NUTRITION'])} écritures)")

        gl_eleve = st.file_uploader(
            "GL_ÉLEVAGE.xlsx", type=['xlsx'], key=f"gl_eleve_{uc}"
        )
        _traiter_upload_gl(gl_eleve, "ÉLEVAGE")
        if "ÉLEVAGE" in st.session_state.gls:
            st.caption(f"✅ Chargé: {st.session_state.gls['ÉLEVAGE'].attrs.get('nom_fichier', '')} "
                      f"({len(st.session_state.gls['ÉLEVAGE'])} écritures)")

    st.divider()

    # Étape 2: Charger relevés bancaires
    st.markdown("**Étape 2 : Charger les relevés bancaires**")
    st.caption("Chargez les fichiers Excel de vos relevés bancaires (UNICS, FH, BGFI, CEPAC, etc.)")

    uploaded_releve = st.file_uploader(
        "Déposez ou sélectionnez un fichier de relevé bancaire",
        type=['xlsx'],
        key=f"releve_upload_{uc}",
        help="Formats supportés: UNICS, FH, BGFI, CEPAC, ADVANS, MUPECI, SCB, BICEC, etc."
    )

    if uploaded_releve and uploaded_releve.name not in st.session_state.releves:
        df = charger_releve(uploaded_releve)
        if df is not None:
            st.session_state.releves[uploaded_releve.name] = df
            banque = df.attrs.get('banque', '')
            periode = df.attrs.get('periode', '')
            persistence.sauvegarder_fichier(
                st.session_state.session_id, "releve", uploaded_releve.name, df,
                banque=banque, periode=periode
            )
            st.success(f"✅ {uploaded_releve.name} chargé ({len(df)} lignes, banque: {banque}) — sauvegardé")
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
                    persistence.supprimer_fichier(st.session_state.session_id, "releve", nom_fichier)
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
        st.success("✅ Prêt pour le rapprochement → Allez à l'onglet 2")
    else:
        if len(st.session_state.gls) < 4:
            st.warning(f"⚠️ {4 - len(st.session_state.gls)} GL(s) manquant(s). Chargez les 4 GLs.")
        if len(st.session_state.releves) == 0:
            st.warning("⚠️ Aucun relevé chargé. Chargez au moins un relevé bancaire.")


# ============================================================
# TAB 2: RAPPROCHEMENT GLOBAL (détection automatique de l'entité)
# ============================================================
with tabs[1]:
    st.header("🔍 Rapprochement Global")
    st.caption(
        "Les 4 entités du Groupe SKAB partagent les mêmes comptes bancaires: un "
        "relevé peut donc contenir des opérations de plusieurs entités mélangées. "
        "Pas besoin de les trier manuellement — chaque ligne de relevé est comparée "
        "directement aux 4 Grands Livres, et l'entité est déduite automatiquement "
        "de celui avec lequel elle correspond."
    )

    if len(st.session_state.releves) == 0:
        st.warning("⚠️ Veuillez d'abord charger des relevés bancaires dans l'onglet 1.")
    elif len(st.session_state.gls) == 0:
        st.warning("⚠️ Veuillez d'abord charger au moins un Grand Livre dans l'onglet 1.")
    else:
        col_go1, col_go2 = st.columns([3, 1])
        with col_go2:
            lancer = st.button("🚀 Lancer le rapprochement", type="primary", use_container_width=True)

        if lancer:
            with st.spinner("🔍 Comparaison de tous les relevés aux 4 Grands Livres..."):
                resultats = run_global_reconciliation(
                    st.session_state.gls,
                    st.session_state.releves,
                    st.session_state.session_id,
                    st.session_state.tolerance_jours,
                    st.session_state.seuil_levenshtein / 100.0
                )
                st.session_state.reconciliation_results = resultats
                st.success("✅ Rapprochement terminé ! Consultez le détail par entité dans l'onglet 3.")

        stats = get_stats(st.session_state.session_id)
        if stats.get('total_matches', 0) > 0 or stats.get('total_suspens', 0) > 0:
            st.divider()
            st.subheader("📊 Résultat du dernier rapprochement")

            total_releve_lignes = sum(len(df) for df in st.session_state.releves.values() if df is not None)
            nb_non_determinees = stats.get('suspens_par_entite', {}).get(NON_DETERMINEE, 0)

            col_r1, col_r2, col_r3, col_r4 = st.columns(4)
            with col_r1:
                st.metric("📋 Lignes de relevé", total_releve_lignes)
            with col_r2:
                st.metric("✅ Appairées (toutes entités)", stats.get('total_matches', 0))
            with col_r3:
                st.metric("⚠️ Suspens (toutes entités)", stats.get('total_suspens', 0))
            with col_r4:
                st.metric("❓ Entité non déterminée", nb_non_determinees)

            # Répartition par entité
            recap = []
            for entite in ENTITES_GL:
                nb_m = stats.get('matches_par_entite', {}).get(entite, 0)
                nb_s = stats.get('suspens_par_entite', {}).get(entite, 0)
                recap.append({'Entité': entite, 'Opérations attribuées': nb_m, 'Suspens (GL orphelin)': nb_s})
            recap.append({
                'Entité': '❓ Non déterminée',
                'Opérations attribuées': 0,
                'Suspens (GL orphelin)': nb_non_determinees
            })
            st.dataframe(pd.DataFrame(recap), use_container_width=True, hide_index=True)

            if nb_non_determinees > 0:
                st.info(
                    f"ℹ️ {nb_non_determinees} opération(s) de relevé n'ont correspondu à aucun des 4 GL. "
                    f"Ouvrez l'onglet 3, sélectionnez « ❓ Non déterminée », et assignez-les manuellement "
                    f"à la bonne entité si vous la connaissez."
                )
        else:
            st.info("Cliquez sur « 🚀 Lancer le rapprochement » pour démarrer.")


# ============================================================
# TAB 3: RAPPROCHEMENT PAR ENTITÉ
# ============================================================
with tabs[2]:
    st.header("🔎 Rapprochement par Entité")

    if not st.session_state.gls:
        st.warning("⚠️ Veuillez d'abord charger les GLs dans l'onglet 1.")
    elif not st.session_state.releves:
        st.warning("⚠️ Veuillez d'abord charger les relevés dans l'onglet 1.")
    else:
        # Sélecteur d'entité (+ panier "non déterminée" pour les opérations
        # qu'aucun GL n'a permis d'attribuer automatiquement)
        entites_disponibles = list(st.session_state.gls.keys()) + [NON_DETERMINEE]

        entite_selectionnee = st.selectbox(
            "Sélectionnez une entité",
            options=entites_disponibles,
            format_func=lambda e: f"❓ {e}" if e == NON_DETERMINEE else e,
            key="entite_select"
        )

        col_match1, col_match2 = st.columns([3, 1])
        with col_match1:
            st.caption(
                "L'entité est déterminée automatiquement lors du rapprochement global "
                "(onglet 2). Relancez-le depuis ce bouton si vous venez de charger de "
                "nouveaux fichiers."
            )
        with col_match2:
            if st.button("🔄 Relancer le rapprochement global", use_container_width=True):
                with st.spinner("🔍 Comparaison de tous les relevés aux 4 Grands Livres..."):
                    resultats = run_global_reconciliation(
                        st.session_state.gls,
                        st.session_state.releves,
                        st.session_state.session_id,
                        st.session_state.tolerance_jours,
                        st.session_state.seuil_levenshtein / 100.0
                    )
                    st.session_state.reconciliation_results = resultats
                    st.success("✅ Rapprochement terminé !")
                    st.rerun()

        is_non_determinee = (entite_selectionnee == NON_DETERMINEE)
        gl_df = st.session_state.gls.get(entite_selectionnee)

        if not is_non_determinee and (gl_df is None or gl_df.empty):
            st.warning(f"Aucun GL chargé pour {entite_selectionnee}.")
        else:
            # Récupérer les résultats depuis la DB
            matches = [] if is_non_determinee else get_matches(st.session_state.session_id, entite_selectionnee)
            suspens = get_suspens(st.session_state.session_id, entite_selectionnee)

            # Statistiques
            if is_non_determinee:
                nb_matches = 0
                nb_suspens = len(suspens)
            else:
                stats_entite = get_stats_for_entite(st.session_state.session_id, entite_selectionnee)
                nb_matches = stats_entite.get('nb_matches', 0)
                nb_suspens = stats_entite.get('nb_suspens', 0)
            total = nb_matches + nb_suspens
            taux = round(nb_matches / max(total, 1) * 100, 1)

            # SECTION A: STATISTIQUES
            st.subheader("📈 Statistiques")
            if is_non_determinee:
                col_s1, col_s2 = st.columns(2)
                with col_s1:
                    st.metric("❓ Opérations non déterminées", nb_suspens)
                with col_s2:
                    st.caption(
                        "Ces opérations de relevé n'ont correspondu à aucun des 4 GL. "
                        "Assignez-les manuellement à la bonne entité ci-dessous si vous "
                        "la connaissez (l'écriture correspondante devra ensuite être "
                        "recherchée dans le GL de cette entité)."
                    )
            else:
                col_s1, col_s2, col_s3, col_s4 = st.columns(4)
                with col_s1:
                    st.metric("📝 Écritures GL", len(gl_df))
                with col_s2:
                    st.metric("✅ Appairés", nb_matches)
                with col_s3:
                    st.metric("⚠️ Suspens", nb_suspens)
                with col_s4:
                    st.metric("🎯 Taux", f"{taux}%")

                if not is_non_determinee:
                    stats_entite = get_stats_for_entite(st.session_state.session_id, entite_selectionnee)
                    if stats_entite.get('matches_par_type'):
                        st.caption("Répartition par type de match: " +
                                  " | ".join([f"{k}: {v}" for k, v in stats_entite['matches_par_type'].items()]))

            st.divider()

            # SECTION B: APPAIRAGES VALIDÉS
            if not is_non_determinee:
                st.subheader("✅ Appairages Validés")
                if matches:
                    df_matches = pd.DataFrame(matches)
                    display_cols = ['date_operation', 'banque', 'libelle_releve', 'montant', 'type_match', 'confiance']
                    display_cols = [c for c in display_cols if c in df_matches.columns]

                    if not df_matches.empty:
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
                    st.info("Aucun appairage pour le moment. Lancez le rapprochement (onglet 2).")

                st.divider()

            # SECTION C: SUSPENS À INVESTIGUER
            titre_suspens = "❓ Opérations non attribuées à investiguer" if is_non_determinee else "⚠️ Suspens à Investiguer"
            st.subheader(titre_suspens)
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

                        # Réattribution manuelle d'entité — uniquement pertinent pour les
                        # opérations de relevé (une écriture GL appartient déjà à une
                        # entité fixe, celle du fichier GL dont elle provient)
                        nouvelle_entite = entite_selectionnee
                        if s.get('type_suspens') == 'RELEVE_SEUL':
                            options_entite = ENTITES_GL + [NON_DETERMINEE]
                            idx_entite = options_entite.index(entite_selectionnee) if entite_selectionnee in options_entite else len(options_entite) - 1
                            nouvelle_entite = st.selectbox(
                                "Entité (réattribuer si vous la connaissez)",
                                options=options_entite,
                                format_func=lambda e: f"❓ {e}" if e == NON_DETERMINEE else e,
                                index=idx_entite,
                                key=f"entite_{s['suspens_id']}"
                            )

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
                                    statut=nouveau_statut,
                                    entite=nouvelle_entite if nouvelle_entite != entite_selectionnee else None
                                )
                                add_history(st.session_state.session_id, "SUSPENS_MODIFIÉ",
                                          nouvelle_entite,
                                          f"Suspens #{s['suspens_id']}: {nouveau_motif}"
                                          + (f" (réattribué à {nouvelle_entite})" if nouvelle_entite != entite_selectionnee else ""))
                                st.success("✅ Sauvegardé!")
                                st.rerun()
                        with col_btn2:
                            if st.button("❌ Supprimer", key=f"del_{s['suspens_id']}"):
                                delete_suspens(s['suspens_id'])
                                add_history(st.session_state.session_id, "SUSPENS_SUPPRIMÉ",
                                          entite_selectionnee, f"Suspens #{s['suspens_id']}")
                                st.rerun()
            else:
                if matches or is_non_determinee:
                    st.success("🎉 Aucun suspens! Toutes les opérations sont appairées.")
                else:
                    st.info("Aucune donnée. Lancez le rapprochement (onglet 2) pour voir les résultats.")


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
        st.caption(
            "L'entité de chaque opération est déterminée automatiquement lors du "
            "rapprochement (onglet 2) — un même relevé peut contribuer à plusieurs "
            "entités à la fois."
        )

        total_lignes_relevé = sum(len(df) for df in st.session_state.releves.values() if df is not None)
        st.metric("📋 Total lignes de relevé chargées (toutes banques confondues)", total_lignes_relevé)

        entites = ENTITES_GL
        synth_data = []

        for entite in entites:
            nb_matches = stats.get('matches_par_entite', {}).get(entite, 0)
            nb_suspens = stats.get('suspens_par_entite', {}).get(entite, 0)
            total = nb_matches + nb_suspens
            taux = round(nb_matches / max(total, 1) * 100, 1) if total > 0 else 0

            synth_data.append({
                'Entité': entite,
                'Appairés': nb_matches,
                'Suspens (GL orphelin)': nb_suspens,
                'Total': total,
                '% OK': f"{taux}%"
            })

        nb_non_determinees = stats.get('suspens_par_entite', {}).get(NON_DETERMINEE, 0)
        synth_data.append({
            'Entité': '❓ Non déterminée',
            'Appairés': 0,
            'Suspens (GL orphelin)': nb_non_determinees,
            'Total': nb_non_determinees,
            '% OK': '0%'
        })

        # Total
        total_matches = sum(row['Appairés'] for row in synth_data)
        total_suspens = sum(row['Suspens (GL orphelin)'] for row in synth_data)
        total_global = total_matches + total_suspens
        taux_global = round(total_matches / max(total_global, 1) * 100, 1)

        synth_data.append({
            'Entité': '**TOTAL GROUPE**',
            'Appairés': total_matches,
            'Suspens (GL orphelin)': total_suspens,
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
        entites_detail = entites + [NON_DETERMINEE]
        tab_entites = st.tabs([f"❓ {e}" if e == NON_DETERMINEE else e for e in entites_detail])

        for i, entite in enumerate(entites_detail):
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
                      "Rendez-vous à l'onglet 2 pour lancer le rapprochement.")
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
nom_session_footer = (get_session(st.session_state.session_id) or {}).get('nom', '')
st.caption(f"🏦 Application de Rapprochement Bancaire SKAB Cameroun | "
          f"{nom_session_footer or ('Session #' + str(st.session_state.session_id))} | "
          f"Dernière actualisation: {datetime.now().strftime('%H:%M:%S')}")
