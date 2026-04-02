"""
pricing.py — Moteur de pricing des futures sur MASI / MASI20
Formule : F0 = S0 * exp((r - q) * T)
"""

import math
import pandas as pd
import numpy as np
from scipy.interpolate import interp1d
from datetime import datetime, date
import io


# ── Constantes ─────────────────────────────────────────────────────────────
CONTRACT_MULTIPLIER = 10          # MAD par point d'indice (spec MASI20)
STANDARD_MATURITIES = {           # Libellé → fraction d'année
    "3 Mois": 3 / 12,
    "6 Mois": 6 / 12,
    "9 Mois": 9 / 12,
    "1 An":   1.0,
}

# Échéances trimestrielles MASI20 (Mars, Juin, Septembre, Décembre)
QUARTERLY_MONTHS = [3, 6, 9, 12]


# ── Chargement des taux ZC depuis Excel ────────────────────────────────────
def load_zc_rates(file) -> pd.DataFrame:
    """
    Charge le fichier Excel ZC_Rate et retourne un DataFrame propre.
    Colonnes attendues : date_spot | date_maturity | zc (en %)
    """
    df = pd.read_excel(file, sheet_name="ZC_Rate")
    df.columns = [c.strip().lower() for c in df.columns]

    # Normaliser les noms de colonnes
    rename = {}
    for col in df.columns:
        if "spot" in col or col == "date_spot":
            rename[col] = "date_spot"
        elif "maturity" in col or col == "date_maturity":
            rename[col] = "date_maturity"
        elif "zc" in col or "taux" in col or "rate" in col:
            rename[col] = "zc"
    df = df.rename(columns=rename)

    # Convertir en datetime
    df["date_spot"] = pd.to_datetime(df["date_spot"])
    df["date_maturity"] = pd.to_datetime(df["date_maturity"])

    # Calculer T en années à partir de la date spot de référence
    df = df.sort_values("date_maturity").dropna(subset=["zc"])
    df["T"] = (df["date_maturity"] - df["date_spot"]).dt.days / 365.25

    # Garder uniquement les maturités positives
    df = df[df["T"] > 0].copy()

    return df


def interpolate_rate(zc_df: pd.DataFrame, T: float) -> float:
    """
    Interpolation linéaire du taux ZC pour une maturité T (en années).
    Si T est hors bornes, on extrapole avec les valeurs extrêmes.
    """
    T_values = zc_df["T"].values
    r_values = zc_df["zc"].values / 100  # Convertir % → décimal

    if T <= T_values.min():
        return float(r_values[np.argmin(T_values)])
    if T >= T_values.max():
        return float(r_values[np.argmax(T_values)])

    f = interp1d(T_values, r_values, kind="linear")
    return float(f(T))


# ── Calcul du prix future ───────────────────────────────────────────────────
def price_future(S0: float, r: float, q: float, T: float) -> float:
    """
    Prix théorique du future : F0 = S0 * exp((r - q) * T)

    Paramètres
    ----------
    S0 : float  — Niveau spot de l'indice
    r  : float  — Taux sans risque (décimal, ex. 0.0226)
    q  : float  — Taux de dividende (décimal, ex. 0.035)
    T  : float  — Maturité en années

    Retourne
    --------
    float — Prix du contrat future (en points d'indice)
    """
    return S0 * math.exp((r - q) * T)


def notional_value(F0: float, multiplier: float = CONTRACT_MULTIPLIER) -> float:
    """Valeur notionnelle d'un contrat = F0 × multiplicateur."""
    return F0 * multiplier


def basis(S0: float, F0: float) -> float:
    """Base = Spot − Future (converge vers 0 à l'échéance)."""
    return S0 - F0


# ── Pricing complet sur toutes les maturités ───────────────────────────────
def price_all_maturities(
    S0: float,
    q: float,
    zc_df: pd.DataFrame,
    maturities: dict = None,
    pricing_date: date = None
) -> pd.DataFrame:
    """
    Calcule F0, la valeur notionnelle et la base pour chaque maturité.

    Retourne un DataFrame avec les colonnes :
    Maturité | T (années) | r (%) | F0 | Notionnel (MAD) | Base | Date Échéance
    """
    if maturities is None:
        maturities = STANDARD_MATURITIES
    if pricing_date is None:
        pricing_date = date.today()

    rows = []
    for label, T in maturities.items():
        r = interpolate_rate(zc_df, T)
        F0 = price_future(S0, r, q, T)
        notional = notional_value(F0)
        b = basis(S0, F0)

        # Date d'échéance estimée
        days = int(T * 365.25)
        maturity_date = pd.Timestamp(pricing_date) + pd.Timedelta(days=days)

        rows.append({
            "Maturite":          label,
            "T (annees)":        round(T, 4),
            "r (%)":             round(r * 100, 4),
            "F0 (points)":       round(F0, 2),
            "Notionnel (MAD)":   round(notional, 2),
            "Base (S0-F0)":      round(b, 2),
            "Date Echeance":     maturity_date.strftime("%d/%m/%Y"),
        })

    return pd.DataFrame(rows)


# ── Prochaines échéances trimestrielles MASI20 ─────────────────────────────
def get_next_quarterly_expirations(n: int = 4, from_date: date = None) -> list:
    """
    Retourne les n prochaines échéances trimestrielles du MASI20
    (dernier vendredi de Mars, Juin, Septembre, Décembre).
    """
    if from_date is None:
        from_date = date.today()

    expirations = []
    year = from_date.year

    for _ in range(n * 2):  # chercher sur 2 ans max
        for month in QUARTERLY_MONTHS:
            exp = _last_friday_of_month(year, month)
            if exp > from_date:
                expirations.append(exp)
                if len(expirations) == n:
                    return expirations
        year += 1

    return expirations


def _last_friday_of_month(year: int, month: int) -> date:
    """Retourne le dernier vendredi du mois donné."""
    import calendar
    last_day = calendar.monthrange(year, month)[1]
    d = date(year, month, last_day)
    # Vendredi = weekday 4
    while d.weekday() != 4:
        d = date(year, month, d.day - 1)
    return d


# ── Pricing sur les échéances trimestrielles réelles ──────────────────────
def price_quarterly_expirations(
    S0: float,
    q: float,
    zc_df: pd.DataFrame,
    pricing_date: date = None
) -> pd.DataFrame:
    """
    Calcule le prix des futures sur les prochaines échéances trimestrielles MASI20.
    """
    if pricing_date is None:
        pricing_date = date.today()

    expirations = get_next_quarterly_expirations(n=4, from_date=pricing_date)
    rows = []

    for exp in expirations:
        T = (exp - pricing_date).days / 365.25
        if T <= 0:
            continue
        r = interpolate_rate(zc_df, T)
        F0 = price_future(S0, r, q, T)
        notional = notional_value(F0)
        b = basis(S0, F0)

        # Libellé du mois
        month_label = exp.strftime("%b %Y")

        rows.append({
            "Echeance":          month_label,
            "Date Expiration":   exp.strftime("%d/%m/%Y"),
            "T (annees)":        round(T, 4),
            "r (%)":             round(r * 100, 4),
            "F0":                round(F0, 2),
            "Notionnel":         round(notional, 2),
            "Base":              round(b, 2),
        })

    return pd.DataFrame(rows)
