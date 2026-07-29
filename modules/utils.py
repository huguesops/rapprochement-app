"""
Utilitaires pour l'application de rapprochement bancaire SKAB
Fonctions: Levenshtein, formatage monétaire, dates, etc.
"""

import re
from datetime import datetime, timedelta
from dateutil.parser import parse as parse_date


def levenshtein_similarite(s1: str, s2: str) -> float:
    """
    Calcule la similarité Levenshtein entre deux chaînes.
    Retourne un score entre 0.0 et 1.0 (1.0 = identique).
    """
    if not s1 and not s2:
        return 1.0
    if not s1 or not s2:
        return 0.0

    s1 = nettoyer_libelle(s1)
    s2 = nettoyer_libelle(s2)

    if s1 == s2:
        return 1.0

    len1, len2 = len(s1), len(s2)
    if max(len1, len2) == 0:
        return 1.0

    # Matrice Levenshtein optimisée (2 lignes)
    prev = list(range(len2 + 1))
    curr = [0] * (len2 + 1)

    for i in range(1, len1 + 1):
        curr[0] = i
        for j in range(1, len2 + 1):
            cost = 0 if s1[i - 1] == s2[j - 1] else 1
            curr[j] = min(
                prev[j] + 1,       # suppression
                curr[j - 1] + 1,   # insertion
                prev[j - 1] + cost # substitution
            )
        prev, curr = curr, prev

    distance = prev[len2]
    max_len = max(len1, len2)
    return 1.0 - (distance / max_len)


def nettoyer_libelle(libelle: str) -> str:
    """Nettoie un libellé pour la comparaison."""
    if not libelle:
        return ""
    libelle = str(libelle).lower().strip()
    # Supprimer caractères spéciaux mais garder lettres, chiffres, espaces
    libelle = re.sub(r'[^a-z0-9\s]', ' ', libelle)
    # Réduire espaces multiples
    libelle = re.sub(r'\s+', ' ', libelle).strip()
    return libelle


def formater_montant(montant: float) -> str:
    """Formate un montant en FCFA."""
    if montant is None:
        return "0 FCFA"
    return f"{montant:,.0f} FCFA".replace(",", " ")


def formater_date(date_val) -> str:
    """Formate une date en JJ/MM/AAAA."""
    if not date_val:
        return ""
    if isinstance(date_val, str):
        try:
            date_val = parse_date(date_val, dayfirst=True)
        except:
            return date_val
    if isinstance(date_val, datetime):
        return date_val.strftime("%d/%m/%Y")
    return str(date_val)


def parser_date_flexible(date_str: str):
    """
    Parse une date depuis divers formats.
    Retourne un objet datetime ou None.
    """
    if not date_str or not isinstance(date_str, str):
        return None
    date_str = str(date_str).strip()
    # Formats courants
    formats = [
        "%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d",
        "%d-%m-%Y", "%d-%m-%y", "%d %b %Y",
        "%d/%b/%Y", "%d-%b-%Y", "%d %B %Y",
        "%Y/%m/%d", "%d.%m.%Y", "%d.%m.%y",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue
    # Fallback: dateutil
    try:
        return parse_date(date_str, dayfirst=True)
    except:
        return None


def extraire_annee(date_val) -> int:
    """Extrait l'année d'une valeur date."""
    dt = None
    if isinstance(date_val, datetime):
        dt = date_val
    elif isinstance(date_val, str):
        dt = parser_date_flexible(date_val)
    if dt:
        return dt.year
    return 0


def normaliser_montant_str(montant_str: str) -> float:
    """
    Convertit une chaîne de montant en float.
    Gère: "1 234 567", "1,234,567.00", "1234567", etc.
    """
    if not montant_str:
        return 0.0
    if isinstance(montant_str, (int, float)):
        return float(montant_str)
    montant_str = str(montant_str).strip()
    # Remplacer espaces insécables et normaux
    montant_str = montant_str.replace('\xa0', ' ').replace(' ', '')
    # Gérer virgule décimale vs séparateur milliers
    if ',' in montant_str and '.' in montant_str:
        # Format européen: 1.234,56 ou américain: 1,234.56
        if montant_str.rfind(',') > montant_str.rfind('.'):
            # Européen: dernier ',' est décimal
            montant_str = montant_str.replace('.', '').replace(',', '.')
        else:
            # Américain: dernier '.' est décimal
            montant_str = montant_str.replace(',', '')
    elif ',' in montant_str:
        # Peut être décimal ou millier
        parts = montant_str.split(',')
        if len(parts) == 2 and len(parts[1]) <= 2:
            # Probablement décimal
            montant_str = montant_str.replace(',', '.')
        else:
            # Séparateur milliers
            montant_str = montant_str.replace(',', '')
    try:
        return float(montant_str)
    except ValueError:
        return 0.0


def detecter_banque(nom_fichier: str) -> str:
    """Détecte la banque depuis le nom du fichier."""
    nom = nom_fichier.upper()
    banques = {
        'UNICS': 'UNICS',
        'FH': 'FINANCIAL HOUSE',
        'FINANCIAL': 'FINANCIAL HOUSE',
        'BGFI': 'BGFI Bank',
        'CEPAC': 'CEPAC',
        'ADVANS': 'ADVANS',
        'MUPECI': 'MUPECI',
        'SCB': 'SCB Cameroun',
        'BICEC': 'BICEC',
        'UBA': 'UBA',
        'AFRILAND': 'Afriland',
        'SGC': 'SGC',
        'ECO': 'Ecobank',
    }
    for key, value in banques.items():
        if key in nom:
            return value
    return "Autre"


def detecter_periode(df) -> str:
    """Détecte la période depuis les dates d'un DataFrame."""
    if df is None or df.empty:
        return "Inconnue"
    # Chercher colonne date
    col_date = None
    for col in df.columns:
        if 'date' in str(col).lower():
            col_date = col
            break
    if not col_date:
        return "Inconnue"
    try:
        dates = df[col_date].dropna()
        if dates.empty:
            return "Inconnue"
        # Parser les dates
        dates_parsed = []
        for d in dates:
            dt = parser_date_flexible(str(d))
            if dt:
                dates_parsed.append(dt)
        if not dates_parsed:
            return "Inconnue"
        debut = min(dates_parsed)
        fin = max(dates_parsed)
        if debut.year == fin.year:
            return f"{debut.strftime('%d/%m/%Y')} - {fin.strftime('%d/%m/%Y')}"
        return f"{debut.strftime('%d/%m/%Y')} - {fin.strftime('%d/%m/%Y')}"
    except:
        return "Inconnue"
