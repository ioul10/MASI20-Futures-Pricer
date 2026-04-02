"""
scraper.py — Récupération du niveau spot du MASI20
Stratégie : Yahoo Finance (^MASI ou approximation) + fallback manuel
"""

import requests
import datetime
import json


def get_masi20_spot() -> dict:
    """
    Tente de scraper le niveau du MASI20 depuis plusieurs sources.
    Retourne un dict : {value, source, timestamp, success}
    """

    # --- Source 1 : Casablanca Bourse (API publique undocumentée) ---
    try:
        result = _scrape_casablanca_bourse()
        if result["success"]:
            return result
    except Exception:
        pass

    # --- Source 2 : Yahoo Finance ---
    try:
        result = _scrape_yahoo()
        if result["success"]:
            return result
    except Exception:
        pass

    # --- Fallback : dernière valeur connue + avertissement ---
    return {
        "value": None,
        "source": "unavailable",
        "timestamp": datetime.datetime.now().isoformat(),
        "success": False,
        "error": "Impossible de récupérer le MASI20 automatiquement. Veuillez saisir la valeur manuellement."
    }


def _scrape_casablanca_bourse() -> dict:
    """
    Scrape le MASI20 depuis l'API de la Bourse de Casablanca.
    """
    url = "https://www.casablanca-bourse.com/bourseweb/srv-indice.asmx/GetAllIndex"
    headers = {
        "Content-Type": "application/json; charset=UTF-8",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://www.casablanca-bourse.com",
    }
    resp = requests.post(url, json={}, headers=headers, timeout=8)
    resp.raise_for_status()
    data = resp.json()

    # Chercher MASI20 dans la réponse
    if isinstance(data, dict) and "d" in data:
        indices = data["d"]
        if isinstance(indices, str):
            indices = json.loads(indices)
        for idx in indices:
            name = str(idx.get("Indice", "") or idx.get("indice", "") or "")
            if "MASI20" in name.upper() or "MASI 20" in name.upper():
                val = float(idx.get("Cours", idx.get("cours", 0)))
                return {
                    "value": val,
                    "source": "Bourse de Casablanca",
                    "timestamp": datetime.datetime.now().isoformat(),
                    "success": True
                }

    return {"success": False}


def _scrape_yahoo() -> dict:
    """
    Tente de récupérer via Yahoo Finance.
    Le MASI20 n'a pas de ticker Yahoo officiel — on tente '^MASI' comme proxy.
    """
    # Yahoo Finance v8 API (non-officielle mais fonctionnelle)
    ticker = "^MASI"
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Accept": "application/json",
    }
    params = {"interval": "1d", "range": "5d"}
    resp = requests.get(url, headers=headers, params=params, timeout=8)
    resp.raise_for_status()
    data = resp.json()

    result = data["chart"]["result"][0]
    closes = result["indicators"]["quote"][0]["close"]
    last_close = [c for c in closes if c is not None][-1]

    return {
        "value": round(last_close, 2),
        "source": "Yahoo Finance (^MASI — proxy MASI)",
        "timestamp": datetime.datetime.now().isoformat(),
        "success": True,
        "warning": "Ticker ^MASI utilisé comme approximation. Vérifier avec MASI20 si disponible."
    }
