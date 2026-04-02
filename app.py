"""
app.py — MASI20 Futures Pricer
F0 = S0 * exp((r - q) * T)
"""

import streamlit as st
import pandas as pd
import numpy as np
import math
import datetime
import plotly.graph_objects as go
import requests

from pricing import (
    load_zc_rates,
    price_quarterly_expirations,
    price_future,
    notional_value,
    interpolate_rate,
    CONTRACT_MULTIPLIER,
    STANDARD_MATURITIES,
)
from scraper import get_masi20_spot

# ── Config ─────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="MASI20 Futures Pricer",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
    .main-header {
        background: linear-gradient(135deg, #1B4F2D 0%, #2E7D4F 50%, #1B4F2D 100%);
        padding: 1.8rem 2.5rem; border-radius: 12px; margin-bottom: 1.5rem; color: white;
    }
    .main-header h1 { margin: 0; font-size: 1.9rem; font-weight: 700; color: white; }
    .main-header p  { margin: 0.3rem 0 0; opacity: 0.85; font-size: 0.95rem; }
    .metric-card {
        background: white; border: 1px solid #e5e7eb; border-radius: 10px;
        padding: 1.1rem 1rem; text-align: center;
        box-shadow: 0 1px 4px rgba(0,0,0,0.06);
    }
    .metric-card .label { font-size: 0.75rem; color: #6b7280; text-transform: uppercase; letter-spacing: 0.05em; }
    .metric-card .value { font-size: 1.65rem; font-weight: 700; color: #1B4F2D; margin: 0.2rem 0; }
    .metric-card .sub   { font-size: 0.78rem; color: #9ca3af; }
    .section-title {
        font-size: 1.05rem; font-weight: 600; color: #1B4F2D;
        border-left: 4px solid #2E7D4F; padding-left: 0.75rem; margin: 1.4rem 0 0.8rem;
    }
    .formula-box {
        background: #f0fdf4; border: 1px solid #86efac; border-radius: 8px;
        padding: 1rem 1.5rem; font-family: 'Courier New', monospace;
        font-size: 1.05rem; color: #166534; margin: 0.8rem 0;
    }
    .info-banner {
        background: #eff6ff; border: 1px solid #93c5fd; border-radius: 8px;
        padding: 0.65rem 1rem; font-size: 0.86rem; color: #1e40af; margin: 0.4rem 0;
    }
    .warn-banner {
        background: #fffbeb; border: 1px solid #fcd34d; border-radius: 8px;
        padding: 0.65rem 1rem; font-size: 0.86rem; color: #92400e; margin: 0.4rem 0;
    }
    .sidebar-brand {
        background: #1B4F2D; color: white; border-radius: 8px; padding: 0.8rem 1rem;
        text-align: center; margin-bottom: 1rem; font-weight: 600; font-size: 0.9rem;
    }
    .spot-badge {
        background: #dcfce7; border: 1px solid #4ade80; border-radius: 8px;
        padding: 0.5rem 0.8rem; font-size: 0.85rem; color: #166534;
    }
    .footer {
        text-align: center; color: #9ca3af; font-size: 0.76rem;
        margin-top: 2rem; padding-top: 1rem; border-top: 1px solid #e5e7eb;
    }
</style>
""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════
# SIDEBAR
# ══════════════════════════════════════════════════════════════════════════
with st.sidebar:
    st.markdown('<div class="sidebar-brand">📊 MASI20 Futures Pricer<br><small>CDG Capital — Marché à Terme</small></div>', unsafe_allow_html=True)

    # 1. Fichier ZC
    st.markdown("### 📂 Courbe des Taux ZC")
    uploaded_zc = st.file_uploader(
        "Importer ZC_Rate.xlsx",
        type=["xlsx", "xls"],
        help="Colonnes attendues : date_spot | date_maturity | zc (%)"
    )

    zc_df = None
    pricing_date = datetime.date.today()

    if uploaded_zc is not None:
        try:
            zc_df = load_zc_rates(uploaded_zc)
            # Date spot depuis l'Excel
            pricing_date = zc_df["date_spot"].iloc[0].date()
            st.success(f"✅ {len(zc_df)} points chargés")
            st.markdown(f'<div class="spot-badge">📅 Date spot Excel : <b>{pricing_date.strftime("%d/%m/%Y")}</b></div>', unsafe_allow_html=True)
        except Exception as e:
            st.error(f"❌ Erreur : {e}")

    # 2. Prix Spot MASI20
    st.markdown("### 🔴 Niveau Spot MASI20")

    if "spot_result" not in st.session_state:
        st.session_state.spot_result = None

    if st.button("🔄 Scraper cours live", use_container_width=True):
        with st.spinner("Récupération en cours..."):
            result = get_masi20_spot()
            st.session_state.spot_result = result

    default_spot = 15500.0
    if st.session_state.spot_result:
        if st.session_state.spot_result["success"]:
            auto_val = st.session_state.spot_result["value"]
            src  = st.session_state.spot_result.get("source", "")
            warn = st.session_state.spot_result.get("warning", "")
            st.markdown(f'<div class="info-banner">📡 <b>{src}</b><br>{auto_val:,.2f} pts</div>', unsafe_allow_html=True)
            if warn:
                st.markdown(f'<div class="warn-banner">⚠️ {warn}</div>', unsafe_allow_html=True)
            default_spot = auto_val
        else:
            err = st.session_state.spot_result.get("error", "Erreur inconnue")
            st.markdown(f'<div class="warn-banner">❌ {err}</div>', unsafe_allow_html=True)

    S0 = st.number_input(
        "S0 — Niveau de l'indice (points)",
        min_value=100.0, max_value=999999.0,
        value=default_spot, step=10.0, format="%.2f"
    )

    # 3. Taux de dividende q
    st.markdown("### 🍃 Taux de Dividende (q)")
    q_mode = st.radio("Mode", ["Valeur fixe", "Par maturite"], horizontal=True)

    if q_mode == "Valeur fixe":
        q_pct = st.slider("q (%)", 0.0, 10.0, 3.5, 0.1,
            help="Rendement dividende annualise ~3-4% pour le MASI20")
        q = q_pct / 100
        q_map = {k: q for k in STANDARD_MATURITIES}
        st.markdown('<div class="info-banner">ℹ️ Dividendes marocains concentres sur <b>mars-juin</b>. q varie selon la maturite.</div>', unsafe_allow_html=True)
    else:
        q_3m = st.number_input("q — 3 Mois (%)", value=2.5, step=0.1) / 100
        q_6m = st.number_input("q — 6 Mois (%)", value=3.5, step=0.1) / 100
        q_9m = st.number_input("q — 9 Mois (%)", value=4.0, step=0.1) / 100
        q_1y = st.number_input("q — 1 An (%)",    value=3.8, step=0.1) / 100
        q_map = {"3 Mois": q_3m, "6 Mois": q_6m, "9 Mois": q_9m, "1 An": q_1y}
        q = q_3m

    # 4. Contrat
    st.markdown("### ⚙️ Contrat")
    multiplier = st.number_input("Multiplicateur (MAD/point)", 1, 1000, CONTRACT_MULTIPLIER, 1)

    st.markdown("---")
    st.markdown('<div class="footer">F0 = S0 x e^((r-q)xT)<br>Hull (2022) — Absence d\'arbitrage</div>', unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════
st.markdown(f"""
<div class="main-header">
    <h1>📈 MASI20 Futures Pricer</h1>
    <p>Pricing theorique des contrats futures sur l'indice MASI20 — Bourse de Casablanca &nbsp;|&nbsp; Date spot : <b>{pricing_date.strftime("%d/%m/%Y")}</b></p>
</div>
""", unsafe_allow_html=True)

if zc_df is None:
    st.markdown('<div class="warn-banner">⚠️ <b>Aucun fichier ZC importe.</b> Veuillez charger votre fichier <code>ZC_Rate.xlsx</code> dans la barre laterale.</div>', unsafe_allow_html=True)
    st.stop()

# ONGLETS
tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "📊 Pricing Standard",
    "🗓️ Echeances Trimestrielles",
    "📉 Graphe MASI20",
    "📈 Courbe ZC",
    "ℹ️ Methodologie",
])


# ════════════════════════════════════════════════════════
# TAB 1 — PRICING STANDARD
# ════════════════════════════════════════════════════════
with tab1:
    st.markdown('<div class="section-title">Formule d\'Absence d\'Arbitrage</div>', unsafe_allow_html=True)
    st.markdown('<div class="formula-box">F0 = S0 x exp( (r - q) x T )<br><br>S0 : Spot indice &nbsp;|&nbsp; r : Taux ZC interpole &nbsp;|&nbsp; q : Rendement dividende &nbsp;|&nbsp; T : Maturite (annees)</div>', unsafe_allow_html=True)

    # Calcul
    rows = []
    for label, T in STANDARD_MATURITIES.items():
        q_used = q_map.get(label, q)
        r = interpolate_rate(zc_df, T)
        F0 = price_future(S0, r, q_used, T)
        notional = notional_value(F0, multiplier)
        base = S0 - F0
        rows.append({
            "Maturite":   label,
            "T_ans":      T,
            "r_pct":      round(r * 100, 4),
            "q_pct":      round(q_used * 100, 2),
            "rq_pct":     round((r - q_used) * 100, 4),
            "F0":         round(F0, 2),
            "Notionnel":  round(notional, 2),
            "Base":       round(base, 2),
            "Carry_pct":  round((r - q_used) * T * 100, 4),
        })

    # Metrics
    st.markdown('<div class="section-title">Resultats</div>', unsafe_allow_html=True)
    cols = st.columns(4)
    for i, row in enumerate(rows):
        with cols[i]:
            delta_pct = ((row["F0"] / S0) - 1) * 100
            direction = "▲" if delta_pct >= 0 else "▼"
            st.markdown(f"""
            <div class="metric-card">
                <div class="label">{row['Maturite']}</div>
                <div class="value">{row['F0']:,.2f}</div>
                <div class="sub">{direction} {abs(delta_pct):.2f}% vs Spot</div>
                <div class="sub">Notionnel : {row['Notionnel']:,.0f} MAD</div>
            </div>
            """, unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    # Tableau — noms de colonnes 100% ASCII
    df_table = pd.DataFrame([{
        "Maturite":         r["Maturite"],
        "T (annees)":       r["T_ans"],
        "r (%)":            r["r_pct"],
        "q (%)":            r["q_pct"],
        "r-q (%)":          r["rq_pct"],
        "F0 (points)":      r["F0"],
        "Notionnel (MAD)":  f"{r['Notionnel']:,.2f}",
        "Base (S0-F0)":     f"{r['Base']:+,.2f}",
        "Carry (%)":        r["Carry_pct"],
    } for r in rows])

    st.markdown('<div class="section-title">Tableau Detaille</div>', unsafe_allow_html=True)
    st.dataframe(df_table, use_container_width=True, hide_index=True)

    # Graphe structure par terme
    st.markdown('<div class="section-title">Structure par Terme des Futures</div>', unsafe_allow_html=True)
    T_range = np.linspace(0.05, 1.2, 300)
    q_avg = sum(q_map.values()) / len(q_map)
    F_curve = [price_future(S0, interpolate_rate(zc_df, T), q_avg, T) for T in T_range]

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=T_range * 12, y=F_curve,
        mode="lines", name="Courbe F0(T)",
        line=dict(color="#2E7D4F", width=2.5),
        hovertemplate="T = %{x:.1f} mois<br>F0 = %{y:,.2f} pts<extra></extra>"
    ))
    fig.add_trace(go.Scatter(
        x=[r["T_ans"] * 12 for r in rows],
        y=[r["F0"] for r in rows],
        mode="markers+text",
        marker=dict(size=12, color="#1B4F2D", symbol="diamond"),
        text=[r["Maturite"] for r in rows],
        textposition="top center", name="Echeances standard",
        hovertemplate="<b>%{text}</b><br>F0 = %{y:,.2f} pts<extra></extra>"
    ))
    fig.add_hline(y=S0, line_dash="dot", line_color="#ef4444",
        annotation_text=f"Spot S0 = {S0:,.2f}", annotation_position="bottom right")
    fig.update_layout(
        xaxis_title="Maturite (mois)", yaxis_title="Prix Future (points)",
        plot_bgcolor="white", paper_bgcolor="white", height=400,
        margin=dict(l=20, r=20, t=30, b=20),
        legend=dict(orientation="h", y=1.05, x=0),
        xaxis=dict(showgrid=True, gridcolor="#f3f4f6"),
        yaxis=dict(showgrid=True, gridcolor="#f3f4f6"),
    )
    st.plotly_chart(fig, use_container_width=True)

    # Note q
    st.markdown('<div class="section-title">Note sur le Taux de Dividende q</div>', unsafe_allow_html=True)
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("""
        **Calcul de q :**
        $$q = \\frac{\\sum_{i=1}^{20} w_i \\cdot D_i}{S_0}$$
        $w_i$ = poids composante $i$, $D_i$ = dividende annuel attendu.
        """)
    with c2:
        st.markdown("""
        **q n'est pas constant :**
        - Dividendes marocains concentres **mars-juin**
        - Si S0 monte, q baisse mecaniquement
        - Decisions de distribution variables

        Valeur typique MASI20 : **3 – 4%**
        """)


# ════════════════════════════════════════════════════════
# TAB 2 — ECHEANCES TRIMESTRIELLES
# ════════════════════════════════════════════════════════
with tab2:
    st.markdown('<div class="section-title">Prochaines Echeances Trimestrielles</div>', unsafe_allow_html=True)
    st.markdown('<div class="info-banner">Contrats MASI20 : expiration le <b>dernier vendredi de Mars, Juin, Septembre, Decembre</b>.</div>', unsafe_allow_html=True)

    df_quarterly = price_quarterly_expirations(S0, q, zc_df, pricing_date)

    if not df_quarterly.empty:
        cols_q = st.columns(len(df_quarterly))
        for i, (_, row) in enumerate(df_quarterly.iterrows()):
            with cols_q[i]:
                delta = ((row["F0"] / S0) - 1) * 100
                st.markdown(f"""
                <div class="metric-card">
                    <div class="label">{row['Echeance']}</div>
                    <div class="value">{row['F0']:,.2f}</div>
                    <div class="sub">Exp. {row['Date Expiration']}</div>
                    <div class="sub">{'▲' if delta >= 0 else '▼'} {abs(delta):.2f}% vs Spot</div>
                </div>
                """, unsafe_allow_html=True)

        st.markdown("<br>", unsafe_allow_html=True)

        # Tableau ASCII strict
        df_q_disp = pd.DataFrame([{
            "Echeance":        r["Echeance"],
            "Date Expiration": r["Date Expiration"],
            "T (annees)":      r["T (annees)"],
            "r (%)":           r["r (%)"],
            "F0 (points)":     f"{r['F0']:,.2f}",
            "Notionnel (MAD)": f"{r['Notionnel']:,.2f}",
            "Base (S0-F0)":    f"{r['Base']:+,.2f}",
        } for _, r in df_quarterly.iterrows()])
        st.dataframe(df_q_disp, use_container_width=True, hide_index=True)

        # Graphe base
        st.markdown('<div class="section-title">Convergence de la Base vers Zero</div>', unsafe_allow_html=True)
        fig2 = go.Figure()
        fig2.add_trace(go.Bar(
            x=df_quarterly["Echeance"],
            y=df_quarterly["Base"],
            marker_color=["#2E7D4F" if v > 0 else "#ef4444" for v in df_quarterly["Base"]],
            hovertemplate="<b>%{x}</b><br>Base = %{y:+,.2f} pts<extra></extra>"
        ))
        fig2.add_hline(y=0, line_dash="dash", line_color="gray")
        fig2.update_layout(
            yaxis_title="Base S0 - F0 (points)",
            plot_bgcolor="white", paper_bgcolor="white",
            height=300, margin=dict(l=20, r=20, t=20, b=20),
        )
        st.plotly_chart(fig2, use_container_width=True)
        st.markdown("> **Base positive (F0 < S0)** : q > r → backwardation. Les dividendes attendus depassent le cout de financement.")


# ════════════════════════════════════════════════════════
# TAB 3 — GRAPHE MASI20
# ════════════════════════════════════════════════════════
with tab3:
    st.markdown('<div class="section-title">Historique du MASI20 — Bourse de Casablanca</div>', unsafe_allow_html=True)

    period_options = {"1 Mois": "1mo", "3 Mois": "3mo", "6 Mois": "6mo", "1 An": "1y", "2 Ans": "2y", "5 Ans": "5y"}
    _, col_p2 = st.columns([3, 1])
    with col_p2:
        selected_period = st.selectbox("Periode", list(period_options.keys()), index=3)
    period_code = period_options[selected_period]

    @st.cache_data(ttl=3600)
    def fetch_masi20_history(period: str):
        tickers = ["^MASI20", "^MASI", "MASI.MA"]
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        for ticker in tickers:
            try:
                url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
                params = {"interval": "1d", "range": period}
                resp = requests.get(url, headers=headers, params=params, timeout=8)
                if resp.status_code != 200:
                    continue
                data = resp.json()
                result = data["chart"]["result"][0]
                timestamps = result["timestamp"]
                closes = result["indicators"]["quote"][0]["close"]
                dates = pd.to_datetime(timestamps, unit="s")
                df_h = pd.DataFrame({"date": dates, "close": closes}).dropna()
                if len(df_h) > 5:
                    meta = result.get("meta", {})
                    name = meta.get("shortName", ticker)
                    return df_h, ticker, name, None
            except Exception:
                continue
        return None, None, None, "Impossible de recuperer l'historique depuis Yahoo Finance."

    df_hist, ticker_used, idx_name, err_msg = fetch_masi20_history(period_code)

    if err_msg:
        st.markdown(f'<div class="warn-banner">⚠️ {err_msg}<br>Le scraping Yahoo Finance peut etre limite depuis Streamlit Cloud. Entrez le cours manuellement dans la sidebar.</div>', unsafe_allow_html=True)
    else:
        last_val  = df_hist["close"].iloc[-1]
        prev_val  = df_hist["close"].iloc[-2] if len(df_hist) > 1 else last_val
        chg       = last_val - prev_val
        chg_pct   = chg / prev_val * 100

        c1, c2, c3, c4 = st.columns(4)
        with c1:
            st.markdown(f'<div class="metric-card"><div class="label">Dernier cours</div><div class="value">{last_val:,.2f}</div><div class="sub">{ticker_used}</div></div>', unsafe_allow_html=True)
        with c2:
            col_chg = "#16a34a" if chg >= 0 else "#dc2626"
            st.markdown(f'<div class="metric-card"><div class="label">Variation J-1</div><div class="value" style="color:{col_chg}">{"▲" if chg>=0 else "▼"} {abs(chg_pct):.2f}%</div><div class="sub">{chg:+,.2f} pts</div></div>', unsafe_allow_html=True)
        with c3:
            hi = df_hist["close"].max()
            st.markdown(f'<div class="metric-card"><div class="label">Plus haut ({selected_period})</div><div class="value">{hi:,.2f}</div></div>', unsafe_allow_html=True)
        with c4:
            lo = df_hist["close"].min()
            st.markdown(f'<div class="metric-card"><div class="label">Plus bas ({selected_period})</div><div class="value">{lo:,.2f}</div></div>', unsafe_allow_html=True)

        st.markdown("<br>", unsafe_allow_html=True)

        fig_h = go.Figure()
        fig_h.add_trace(go.Scatter(
            x=df_hist["date"], y=df_hist["close"],
            mode="lines",
            line=dict(color="#2E7D4F", width=2),
            name=idx_name or ticker_used,
            fill="tozeroy", fillcolor="rgba(46,125,79,0.08)",
            hovertemplate="%{x|%d/%m/%Y}<br><b>%{y:,.2f} pts</b><extra></extra>"
        ))

        # Ligne S0
        fig_h.add_hline(
            y=S0, line_dash="dot", line_color="#f59e0b",
            annotation_text=f"S0 saisi = {S0:,.2f}",
            annotation_position="bottom right",
            annotation_font_color="#f59e0b"
        )

        # Ligne date spot Excel
        try:
            fig_h.add_vline(
                x=str(pricing_date), line_dash="dash", line_color="#6366f1",
                annotation_text=f"Date spot Excel ({pricing_date.strftime('%d/%m/%Y')})",
                annotation_position="top right",
                annotation_font_color="#6366f1"
            )
        except Exception:
            pass

        # MM20
        if len(df_hist) >= 20:
            df_hist = df_hist.copy()
            df_hist["ma20"] = df_hist["close"].rolling(20).mean()
            fig_h.add_trace(go.Scatter(
                x=df_hist["date"], y=df_hist["ma20"],
                mode="lines", line=dict(color="#f97316", width=1.4, dash="dot"),
                name="MM 20j",
                hovertemplate="%{x|%d/%m/%Y}<br>MM20 = %{y:,.2f}<extra></extra>"
            ))

        fig_h.update_layout(
            title=dict(text=f"{idx_name or ticker_used} — {selected_period}", font=dict(size=14, color="#1B4F2D")),
            xaxis_title="Date", yaxis_title="Niveau (points)",
            plot_bgcolor="white", paper_bgcolor="white",
            height=480, margin=dict(l=20, r=20, t=50, b=20),
            legend=dict(orientation="h", y=1.08, x=0),
            xaxis=dict(showgrid=True, gridcolor="#f3f4f6", rangeslider=dict(visible=True)),
            yaxis=dict(showgrid=True, gridcolor="#f3f4f6"),
            hovermode="x unified",
        )
        st.plotly_chart(fig_h, use_container_width=True)

        st.markdown(f'<div class="info-banner">📡 Source : Yahoo Finance — ticker <b>{ticker_used}</b>. Ligne jaune : S0 saisi. Ligne violette : date spot de la courbe ZC.</div>', unsafe_allow_html=True)

        with st.expander("📊 Statistiques descriptives"):
            ret = df_hist["close"].pct_change().dropna()
            s1, s2, s3, s4, s5 = st.columns(5)
            s1.metric("Rendement total",   f"{(last_val/df_hist['close'].iloc[0]-1)*100:.2f}%")
            s2.metric("Vol. annualisee",   f"{ret.std()*math.sqrt(252)*100:.2f}%")
            s3.metric("Sharpe (approx.)",  f"{ret.mean()/ret.std()*math.sqrt(252):.2f}")
            s4.metric("Max Drawdown",      f"{((df_hist['close']/df_hist['close'].cummax())-1).min()*100:.2f}%")
            s5.metric("Nb seances",        len(df_hist))


# ════════════════════════════════════════════════════════
# TAB 4 — COURBE ZC
# ════════════════════════════════════════════════════════
with tab4:
    st.markdown('<div class="section-title">Courbe des Taux Zero-Coupon</div>', unsafe_allow_html=True)

    c1, c2, c3 = st.columns(3)
    with c1:
        ds = zc_df["date_spot"].iloc[0].strftime("%d/%m/%Y") if "date_spot" in zc_df.columns else "N/A"
        st.metric("Date Spot (Excel)", ds)
    with c2:
        st.metric("Points de courbe", len(zc_df))
    with c3:
        st.metric("Plage", f"{zc_df['T'].min():.2f} – {zc_df['T'].max():.1f} ans")

    fig3 = go.Figure()
    fig3.add_trace(go.Scatter(
        x=zc_df["T"] * 12, y=zc_df["zc"],
        mode="markers+lines",
        marker=dict(size=6, color="#2E7D4F"),
        line=dict(color="#2E7D4F", width=1.5),
        name="Taux ZC (%)",
        hovertemplate="T = %{x:.1f} mois<br>ZC = %{y:.4f}%<extra></extra>"
    ))
    for label, T in STANDARD_MATURITIES.items():
        r_m = interpolate_rate(zc_df, T)
        fig3.add_trace(go.Scatter(
            x=[T * 12], y=[r_m * 100],
            mode="markers",
            marker=dict(size=12, color="#ef4444", symbol="x"),
            name=f"r({label})={r_m*100:.4f}%",
            hovertemplate=f"<b>{label}</b><br>r = {r_m*100:.4f}%<extra></extra>"
        ))
    fig3.update_layout(
        xaxis_title="Maturite (mois)", yaxis_title="Taux ZC (%)",
        plot_bgcolor="white", paper_bgcolor="white", height=420,
        margin=dict(l=20, r=20, t=20, b=20),
        legend=dict(orientation="h", y=1.05, x=0),
    )
    st.plotly_chart(fig3, use_container_width=True)

    rows_zc = [{"Maturite": lbl, "T (annees)": T, "r interpole (%)": round(interpolate_rate(zc_df, T)*100, 5)} for lbl, T in STANDARD_MATURITIES.items()]
    st.dataframe(pd.DataFrame(rows_zc), use_container_width=True, hide_index=True)

    with st.expander("📋 Donnees brutes ZC"):
        st.dataframe(zc_df[["date_maturity", "T", "zc"]].rename(columns={
            "date_maturity": "Date Maturite", "T": "T (annees)", "zc": "ZC (%)"}),
            use_container_width=True, hide_index=True)


# ════════════════════════════════════════════════════════
# TAB 5 — METHODOLOGIE
# ════════════════════════════════════════════════════════
with tab5:
    st.markdown('<div class="section-title">Modele de Pricing</div>', unsafe_allow_html=True)
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("""
        #### Formule Theorique
        $$F_0 = S_0 \\cdot e^{(r - q) \\cdot T}$$

        | Symbole | Description | Source |
        |---------|-------------|--------|
        | S0 | Niveau spot MASI20 | Scraping / saisie |
        | r | Taux sans risque | Courbe ZC (interpolation) |
        | q | Rendement dividende | Saisie utilisateur |
        | T | Maturite (annees) | Date spot Excel |

        #### Valeur Notionnelle
        $$\\text{Notionnel} = F_0 \\times 10 \\text{ MAD/point}$$
        """)
    with c2:
        st.markdown("""
        #### Specifications MASI20

        | Caracteristique | Valeur |
        |-----------------|--------|
        | Multiplicateur | 10 MAD/point |
        | Pas de cotation | 0.1 pt = 1 MAD |
        | Echeances | Mar, Juin, Sep, Dec |
        | Expiration | Dernier vendredi |
        | Denouement | Cash |
        | Depot de garantie | 1 000 MAD |

        #### Roadmap V2
        - Couverture N* = beta x P/A
        - Calcul beta par regression
        - Simulation P&L couverture
        - Export PDF rapport
        """)
    st.markdown('<div class="footer">MASI20 Futures Pricer — CDG Capital | Hull (2022) — Options, Futures and Other Derivatives</div>', unsafe_allow_html=True)
