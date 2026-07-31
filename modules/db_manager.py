"""
Gestionnaire de base de données SQLite
CRUD pour les tables de l'application de rapprochement
"""

import sqlite3
import os
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "app.db"
SCHEMA_PATH = Path(__file__).parent.parent / "database" / "schema.sql"


def get_connection():
    """Retourne une connexion à la base SQLite."""
    os.makedirs(DB_PATH.parent, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """Initialise la base de données avec le schéma (et migre les DB existantes)."""
    conn = get_connection()
    try:
        with open(str(SCHEMA_PATH), 'r', encoding='utf-8') as f:
            schema = f.read()
        conn.executescript(schema)
        conn.commit()
    except Exception as e:
        print(f"Erreur init DB: {e}")
        raise
    finally:
        conn.close()
    _migrer_si_necessaire()


def _migrer_si_necessaire():
    """Ajoute les colonnes manquantes sur une base créée avec un schéma antérieur."""
    conn = get_connection()
    try:
        colonnes = {row['name'] for row in conn.execute("PRAGMA table_info(sessions)").fetchall()}
        if 'nom' not in colonnes:
            conn.execute("ALTER TABLE sessions ADD COLUMN nom TEXT DEFAULT ''")
            conn.commit()
    except Exception as e:
        print(f"Migration ignorée: {e}")
    finally:
        conn.close()


def create_session(user="SKAB", periode_debut="", periode_fin="", nom=""):
    """Crée une nouvelle session de travail (nommée si possible)."""
    conn = get_connection()
    try:
        if not nom:
            nom = f"Session du {datetime.now().strftime('%d/%m/%Y %H:%M')}"
        cursor = conn.execute(
            "INSERT INTO sessions (nom, user, periode_debut, periode_fin) VALUES (?, ?, ?, ?)",
            (nom, user, periode_debut, periode_fin)
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def get_active_session():
    """
    Récupère la session la plus récente, ou en crée une nouvelle s'il n'en existe aucune.
    NB: utilisé uniquement comme session par défaut au tout premier lancement — l'app
    privilégie ensuite la session choisie/mémorisée dans l'URL (voir app.py) pour éviter
    que plusieurs utilisateurs ne partagent involontairement la même session.
    """
    conn = get_connection()
    try:
        cursor = conn.execute(
            "SELECT session_id FROM sessions ORDER BY session_id DESC LIMIT 1"
        )
        row = cursor.fetchone()
        if row:
            return row['session_id']
        return create_session()
    finally:
        conn.close()


def get_session(session_id):
    """Récupère les infos d'une session par son id, ou None si elle n'existe pas."""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM sessions WHERE session_id=?", (session_id,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_all_sessions():
    """Liste toutes les sessions existantes, la plus récente en premier."""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM sessions ORDER BY session_id DESC"
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def close_session(session_id):
    """Ferme une session."""
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE sessions SET status='closed' WHERE session_id=?",
            (session_id,)
        )
        conn.commit()
    finally:
        conn.close()


# --- MAPPAGE RELEVÉ → ENTITÉ ---

def save_mappage(session_id, releve_name, banque, periode, nb_lignes, entite):
    """Sauvegarde ou met à jour un mappage relevé → entité."""
    conn = get_connection()
    try:
        existing = conn.execute(
            "SELECT mappage_id FROM mappage_releve_entite WHERE session_id=? AND releve_name=?",
            (session_id, releve_name)
        ).fetchone()

        if existing:
            conn.execute(
                """UPDATE mappage_releve_entite
                   SET entite_assignee=?, banque=?, periode=?, nb_lignes=?, timestamp=CURRENT_TIMESTAMP
                   WHERE mappage_id=?""",
                (entite, banque, periode, nb_lignes, existing['mappage_id'])
            )
        else:
            conn.execute(
                """INSERT INTO mappage_releve_entite
                   (session_id, releve_name, banque, periode, nb_lignes, entite_assignee)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (session_id, releve_name, banque, periode, nb_lignes, entite)
            )
        conn.commit()
    finally:
        conn.close()


def delete_mappage(session_id, releve_name):
    """Supprime un mappage."""
    conn = get_connection()
    try:
        conn.execute(
            "DELETE FROM mappage_releve_entite WHERE session_id=? AND releve_name=?",
            (session_id, releve_name)
        )
        conn.commit()
    finally:
        conn.close()


def get_all_mappages(session_id):
    """Récupère tous les mappages d'une session."""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM mappage_releve_entite WHERE session_id=? ORDER BY releve_name",
            (session_id,)
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def get_mappages_by_entite(session_id, entite):
    """Récupère les mappages pour une entité spécifique."""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM mappage_releve_entite WHERE session_id=? AND entite_assignee=? ORDER BY releve_name",
            (session_id, entite)
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


# --- MATCHES ---

def save_match(session_id, entite, banque, date_operation, libelle_releve, libelle_gl,
               montant, type_match, confiance, gl_piece="", gl_compte=""):
    """Sauvegarde un appairage validé."""
    conn = get_connection()
    try:
        conn.execute(
            """INSERT INTO matches
               (session_id, entite, banque, date_operation, libelle_releve, libelle_gl,
                montant, type_match, confiance, gl_piece, gl_compte)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (session_id, entite, banque, date_operation, libelle_releve, libelle_gl,
             montant, type_match, confiance, gl_piece, gl_compte)
        )
        conn.commit()
    finally:
        conn.close()


def clear_matches_for_entite(session_id, entite):
    """Supprime tous les matches d'une entité pour re-matching."""
    conn = get_connection()
    try:
        conn.execute(
            "DELETE FROM matches WHERE session_id=? AND entite=?",
            (session_id, entite)
        )
        conn.commit()
    finally:
        conn.close()


def get_matches(session_id, entite=None):
    """Récupère les matches, filtrés par entité si spécifié."""
    conn = get_connection()
    try:
        if entite:
            rows = conn.execute(
                "SELECT * FROM matches WHERE session_id=? AND entite=? ORDER BY date_operation",
                (session_id, entite)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM matches WHERE session_id=? ORDER BY entite, date_operation",
                (session_id,)
            ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


# --- SUSPENS ---

def save_suspens(session_id, entite, type_suspens, source, date_operation, libelle,
                 montant, banque="", motif="À éclaircir", observations="", statut="Ouvert"):
    """Sauvegarde un suspens."""
    conn = get_connection()
    try:
        conn.execute(
            """INSERT INTO suspens
               (session_id, entite, type_suspens, source, date_operation, libelle,
                montant, banque, motif, observations, statut)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (session_id, entite, type_suspens, source, date_operation, libelle,
             montant, banque, motif, observations, statut)
        )
        conn.commit()
    finally:
        conn.close()


def update_suspens(suspens_id, motif=None, observations=None, statut=None, entite=None):
    """Met à jour un suspens (motif, observations, statut, et/ou réattribution d'entité)."""
    conn = get_connection()
    try:
        updates = []
        params = []
        if motif is not None:
            updates.append("motif=?")
            params.append(motif)
        if observations is not None:
            updates.append("observations=?")
            params.append(observations)
        if statut is not None:
            updates.append("statut=?")
            params.append(statut)
        if entite is not None:
            updates.append("entite=?")
            params.append(entite)
        if updates:
            params.append(suspens_id)
            conn.execute(
                f"UPDATE suspens SET {', '.join(updates)} WHERE suspens_id=?",
                params
            )
            conn.commit()
    finally:
        conn.close()


def delete_suspens(suspens_id):
    """Supprime un suspens."""
    conn = get_connection()
    try:
        conn.execute("DELETE FROM suspens WHERE suspens_id=?", (suspens_id,))
        conn.commit()
    finally:
        conn.close()


def clear_suspens_for_entite(session_id, entite):
    """Supprime tous les suspens d'une entité."""
    conn = get_connection()
    try:
        conn.execute(
            "DELETE FROM suspens WHERE session_id=? AND entite=?",
            (session_id, entite)
        )
        conn.commit()
    finally:
        conn.close()


def get_suspens(session_id, entite=None, statut=None):
    """Récupère les suspens, filtrés par entité et/ou statut."""
    conn = get_connection()
    try:
        query = "SELECT * FROM suspens WHERE session_id=?"
        params = [session_id]
        if entite:
            query += " AND entite=?"
            params.append(entite)
        if statut:
            query += " AND statut=?"
            params.append(statut)
        query += " ORDER BY date_operation"
        rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


# --- POINTAGE HISTORY ---

def add_history(session_id, action, entite="", details=""):
    """Ajoute une entrée dans l'historique."""
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO pointage_history (session_id, action, entite, details) VALUES (?, ?, ?, ?)",
            (session_id, action, entite, details)
        )
        conn.commit()
    finally:
        conn.close()


def get_history(session_id, limit=100):
    """Récupère l'historique des actions."""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM pointage_history WHERE session_id=? ORDER BY timestamp DESC LIMIT ?",
            (session_id, limit)
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


# --- FICHIERS CHARGÉS (persistance des uploads GL / relevés) ---

def save_fichier_charge(session_id, type_fichier, nom_fichier, chemin_donnees,
                        entite="", banque="", periode="", nb_lignes=0):
    """Enregistre (ou met à jour) la référence d'un fichier GL/relevé persisté sur disque."""
    conn = get_connection()
    try:
        existing = conn.execute(
            "SELECT fichier_id FROM fichiers_charges WHERE session_id=? AND type_fichier=? AND nom_fichier=?",
            (session_id, type_fichier, nom_fichier)
        ).fetchone()

        if existing:
            conn.execute(
                """UPDATE fichiers_charges
                   SET entite=?, banque=?, periode=?, nb_lignes=?, chemin_donnees=?, timestamp=CURRENT_TIMESTAMP
                   WHERE fichier_id=?""",
                (entite, banque, periode, nb_lignes, chemin_donnees, existing['fichier_id'])
            )
        else:
            conn.execute(
                """INSERT INTO fichiers_charges
                   (session_id, type_fichier, nom_fichier, entite, banque, periode, nb_lignes, chemin_donnees)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (session_id, type_fichier, nom_fichier, entite, banque, periode, nb_lignes, chemin_donnees)
            )
        conn.commit()
    finally:
        conn.close()


def get_fichiers_charges(session_id, type_fichier=None):
    """Liste les fichiers persistés pour une session (tous, ou filtrés gl/releve)."""
    conn = get_connection()
    try:
        if type_fichier:
            rows = conn.execute(
                "SELECT * FROM fichiers_charges WHERE session_id=? AND type_fichier=? ORDER BY nom_fichier",
                (session_id, type_fichier)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM fichiers_charges WHERE session_id=? ORDER BY type_fichier, nom_fichier",
                (session_id,)
            ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def delete_fichier_charge(session_id, type_fichier, nom_fichier):
    """Supprime la référence d'un fichier persisté (le fichier disque est supprimé par l'appelant)."""
    conn = get_connection()
    try:
        conn.execute(
            "DELETE FROM fichiers_charges WHERE session_id=? AND type_fichier=? AND nom_fichier=?",
            (session_id, type_fichier, nom_fichier)
        )
        conn.commit()
    finally:
        conn.close()


def delete_all_fichiers_charges(session_id):
    """Supprime toutes les références de fichiers persistés pour une session (réinitialisation)."""
    conn = get_connection()
    try:
        conn.execute("DELETE FROM fichiers_charges WHERE session_id=?", (session_id,))
        conn.commit()
    finally:
        conn.close()


# --- STATISTIQUES ---

def get_stats(session_id):
    """Retourne les statistiques globales de la session."""
    conn = get_connection()
    try:
        stats = {}

        stats['total_releves'] = conn.execute(
            "SELECT COUNT(*) as c FROM mappage_releve_entite WHERE session_id=?",
            (session_id,)
        ).fetchone()['c']

        rows = conn.execute(
            "SELECT entite, COUNT(*) as c FROM matches WHERE session_id=? GROUP BY entite",
            (session_id,)
        ).fetchall()
        stats['matches_par_entite'] = {row['entite']: row['c'] for row in rows}
        stats['total_matches'] = sum(stats['matches_par_entite'].values())

        rows = conn.execute(
            "SELECT entite, COUNT(*) as c FROM suspens WHERE session_id=? GROUP BY entite",
            (session_id,)
        ).fetchall()
        stats['suspens_par_entite'] = {row['entite']: row['c'] for row in rows}
        stats['total_suspens'] = sum(stats['suspens_par_entite'].values())

        rows = conn.execute(
            "SELECT motif, COUNT(*) as c FROM suspens WHERE session_id=? GROUP BY motif",
            (session_id,)
        ).fetchall()
        stats['suspens_par_motif'] = {row['motif']: row['c'] for row in rows}

        return stats
    finally:
        conn.close()


def get_stats_for_entite(session_id, entite):
    """Statistiques pour une entité spécifique."""
    conn = get_connection()
    try:
        stats = {}
        stats['nb_matches'] = conn.execute(
            "SELECT COUNT(*) as c FROM matches WHERE session_id=? AND entite=?",
            (session_id, entite)
        ).fetchone()['c']

        stats['nb_suspens'] = conn.execute(
            "SELECT COUNT(*) as c FROM suspens WHERE session_id=? AND entite=?",
            (session_id, entite)
        ).fetchone()['c']

        rows = conn.execute(
            "SELECT type_match, COUNT(*) as c FROM matches WHERE session_id=? AND entite=? GROUP BY type_match",
            (session_id, entite)
        ).fetchall()
        stats['matches_par_type'] = {row['type_match']: row['c'] for row in rows}

        return stats
    finally:
        conn.close()
