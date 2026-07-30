-- ============================================================
-- SCHÉMA SQLite — Application Rapprochement Bancaire SKAB
-- Groupe SKAB Cameroun | Multi-Banques | Multi-Entités
-- ============================================================

-- 1. SESSIONS
CREATE TABLE IF NOT EXISTS sessions (
    session_id INTEGER PRIMARY KEY AUTOINCREMENT,
    nom TEXT DEFAULT '',
    user TEXT DEFAULT 'SKAB',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    periode_debut TEXT,
    periode_fin TEXT,
    status TEXT DEFAULT 'active'
);

-- 2. MAPPAGE RELEVÉ → ENTITÉ
CREATE TABLE IF NOT EXISTS mappage_releve_entite (
    mappage_id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    releve_name TEXT NOT NULL,
    banque TEXT,
    periode TEXT,
    nb_lignes INTEGER DEFAULT 0,
    entite_assignee TEXT,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (session_id) REFERENCES sessions(session_id)
);

-- 3. MATCHES (appairages validés)
CREATE TABLE IF NOT EXISTS matches (
    match_id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    entite TEXT NOT NULL,
    banque TEXT,
    date_operation TEXT,
    libelle_releve TEXT,
    libelle_gl TEXT,
    montant REAL,
    type_match TEXT,  -- 'exact', 'montant_date', 'levenshtein'
    confiance REAL,
    gl_piece TEXT,
    gl_compte TEXT,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (session_id) REFERENCES sessions(session_id)
);

-- 4. SUSPENS (anomalies)
CREATE TABLE IF NOT EXISTS suspens (
    suspens_id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    entite TEXT NOT NULL,
    type_suspens TEXT,  -- 'RELEVE_SEUL', 'GL_SEUL', 'MONTANT_DIFF', 'DOUBLON'
    source TEXT,        -- 'releve' ou 'gl'
    date_operation TEXT,
    libelle TEXT,
    montant REAL,
    banque TEXT,
    motif TEXT DEFAULT 'À éclaircir',
    observations TEXT DEFAULT '',
    statut TEXT DEFAULT 'Ouvert',
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (session_id) REFERENCES sessions(session_id)
);

-- 5. POINTAGE HISTORY (audit trail)
CREATE TABLE IF NOT EXISTS pointage_history (
    history_id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    action TEXT NOT NULL,
    entite TEXT,
    details TEXT,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (session_id) REFERENCES sessions(session_id)
);

-- 6. FICHIERS CHARGÉS (persistance des relevés/GL uploadés — évite les re-uploads)
CREATE TABLE IF NOT EXISTS fichiers_charges (
    fichier_id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    type_fichier TEXT NOT NULL,   -- 'gl' ou 'releve'
    nom_fichier TEXT NOT NULL,
    entite TEXT,                  -- pour un GL
    banque TEXT,                  -- pour un relevé
    periode TEXT,
    nb_lignes INTEGER DEFAULT 0,
    chemin_donnees TEXT NOT NULL, -- chemin vers le fichier sérialisé sur disque
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(session_id, type_fichier, nom_fichier),
    FOREIGN KEY (session_id) REFERENCES sessions(session_id)
);

-- Index pour performances
CREATE INDEX IF NOT EXISTS idx_mappage_session ON mappage_releve_entite(session_id);
CREATE INDEX IF NOT EXISTS idx_matches_session ON matches(session_id);
CREATE INDEX IF NOT EXISTS idx_matches_entite ON matches(entite);
CREATE INDEX IF NOT EXISTS idx_suspens_session ON suspens(session_id);
CREATE INDEX IF NOT EXISTS idx_suspens_entite ON suspens(entite);
CREATE INDEX IF NOT EXISTS idx_fichiers_session ON fichiers_charges(session_id);
