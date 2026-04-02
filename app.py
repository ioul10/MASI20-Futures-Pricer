"""
app.py — MASI20 Futures Pricer
Application Streamlit de pricing des contrats futures sur l'indice MASI20
Basée sur le modèle d'absence d'arbitrage : F₀ = S₀ × exp((r − q) × T)

CDG Capital — Marché à Terme
"""

import streamlit as st
import pandas as pd
import numpy as np
import math
import datetime
import plotly.graph_objects as go
import plotly.express as px
from io import BytesIO

from pricing import (
    load_zc_rates,
    price_all_maturities,
    price_quarterly_expirations,
    price_future,
    notional_value,
    interpolate_rate,
    CONTRACT_MULTIPLIER,
    STANDARD_MATURITIES,
)
from scraper import get_masi20_spot

# ── Configuration Streamlit ────────────────────────────────────────────────
st.set_page_config(
    page_title="MASI20 Futures Pricer",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── CSS personnalisé ───────────────────────────────────────────────────────
st.markdown("""
<style>
    /* Header principal */
    .main-header {
        background: linear-gradient(135deg, #1B4F2D 0%, #2E7D4F 50%, #1B4F2D 100%);
        padding: 2rem 2.5rem;
        border-radius: 12px;
        margin-bottom: 1.5rem;
        color: white;
    }
    .main-header h1 { margin: 0; font-size: 2rem; font-weight: 700; color: white; }
    .main-header p  { margin: 0.3rem 0 0; opacity: 0.85; font-size: 1rem; }

    /* Metric cards */
    .metric-card {
        background: white;
        border: 1px solid #e5e7eb;
        border-radius: 10px;
        padding: 1.1rem 1.3rem;
        text-align: center;
        box-shadow: 0 1px 4px rgba(0,0,0,0.06);
    }
    .metric-card .label { font-size: 0.78rem; color: #6b7280; text-transform: uppercase; letter-spacing: 0.05em; }
    .metric-card .value { font-size: 1.75rem; font-weight: 700; color: #1B4F2D; margin: 0.2rem 0; }
    .metric-card .sub   { font-size: 0.8rem; color: #9ca3af; }

    /* Section titles */
    .section-title {
        font-size: 1.1rem; font-weight: 600; color: #1B4F2D;
        border-left: 4px solid #2E7D4F; padding-left: 0.75rem;
        margin: 1.5rem 0 0.8rem;
    }

    /* Formula box */
    .formula-box {
        background: #f0fdf4;
        border: 1px solid #86efac;
        border-radius: 8px;
        padding: 1rem 1.5rem;
        font-family: 'Courier New', monospace;
        font-size: 1.05rem;
        color: #166534;
        margin: 0.8rem 0;
    }

    /* Warning / info banners */
    .info-banner {
        background: #eff6ff; border: 1px solid #93c5fd;
        border-radius: 8px; padding: 0.7rem 1rem;
        font-size: 0.88rem; color: #1e40af;
        margin: 0.5rem 0;
    }
    .warn-banner {
        background: #fffbeb; border: 1px solid #fcd34d;
        border-radius: 8px; padding: 0.7rem 1rem;
        font-size: 0.88rem; color: #92400e;
        margin: 0.5rem 0;
    }

    /* Table styling */
    .dataframe { font-size: 0.88rem !important; }

    /* Sidebar branding */
    .sidebar-brand {
        background: #1B4F2D; color: white;
        border-radius: 8px; padding: 0.8rem 1rem;
        text-align: center; margin-bottom: 1rem;
        font-weight: 600; font-size: 0.95rem;
    }

    /* Footer */
    .footer {
        text-align: center; color: #9ca3af;
        font-size: 0.78rem; margin-top: 2rem;
        padding-top: 1rem; border-top: 1px solid #e5e7eb;
    }
</style>
""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════
# ── SIDEBAR ───────────────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════
with st.sidebar:
    st.markdown('<div class="sidebar-brand">📊 MASI20 Futures Pricer<br><small>CDG Capital — Marché à Terme</small></div>', unsafe_allow_html=True)

    # ── 1. Fichier ZC Rates ──────────────────────────────────────────────
    st.markdown("### 📂 Courbe des Taux ZC")
    uploaded_zc = st.file_uploader(
        "Importer le fichier Excel ZC_Rate",
        type=["xlsx", "xls"],
        help="Format attendu : colonnes date_spot | date_maturity | zc (%)"
    )

    zc_df = None
    if uploaded_zc is not None:
        try:
            zc_df = load_zc_rates(uploaded_zc)
            st.success(f"✅ {len(zc_df)} points de taux chargés")
        except Exception as e:
            st.error(f"❌ Erreur lecture Excel : {e}")

    # ── 2. Prix Spot MASI20 ──────────────────────────────────────────────
    st.markdown("### 🔴 Niveau Spot MASI20")

    col_live, col_manual = st.columns(2)
    with col_live:
        fetch_live = st.button("🔄 Live", use_container_width=True, help="Scraper le cours en temps réel")
    with col_manual:
        use_manual = st.checkbox("Manuel", value=True)

    if "spot_result" not in st.session_state:
        st.session_state.spot_result = None

    if fetch_live:
        with st.spinner("Récupération..."):
            result = get_masi20_spot()
            st.session_state.spot_result = result

    if st.session_state.spot_result and st.session_state.spot_result["success"]:
        auto_val = st.session_state.spot_result["value"]
        src = st.session_state.spot_result["source"]
        st.markdown(f'<div class="info-banner">📡 {src}<br><b>{auto_val:,.2f} pts</b></div>', unsafe_allow_html=True)
        default_spot = auto_val
    else:
        default_spot = 15500.0  # valeur indicative MASI20 ~2025

    S0 = st.number_input(
        "S₀ — Niveau de l'indice (points)",
        min_value=100.0, max_value=100000.0,
        value=default_spot, step=10.0, format="%.2f"
    )

    # ── 3. Paramètre q ───────────────────────────────────────────────────
    st.markdown("### 🍃 Taux de Dividende (q)")
    q_mode = st.radio(
        "Mode de saisie",
        ["Valeur fixe", "Par maturité (avancé)"],
        horizontal=True,
    )

    if q_mode == "Valeur fixe":
        q_pct = st.slider(
            "q — Rendement dividende (%)",
            min_value=0.0, max_value=10.0, value=3.5, step=0.1,
            help="Taux de dividende annualisé moyen du MASI20 (~3–4% historiquement)"
        )
        q = q_pct / 100
        st.markdown(f'<div class="info-banner">ℹ️ Au Maroc, les dividendes sont concentrés sur <b>mars–juin</b>. q varie selon la maturité du contrat.</div>', unsafe_allow_html=True)
    else:
        st.markdown("*Saisir q pour chaque maturité standard :*")
        q_3m  = st.number_input("q — 3 Mois (%)", value=2.5, step=0.1) / 100
        q_6m  = st.number_input("q — 6 Mois (%)", value=3.5, step=0.1) / 100
        q_9m  = st.number_input("q — 9 Mois (%)", value=4.0, step=0.1) / 100
        q_1y  = st.number_input("q — 1 An (%)",    value=3.8, step=0.1) / 100
        q_map = {"3 Mois": q_3m, "6 Mois": q_6m, "9 Mois": q_9m, "1 An": q_1y}
        q = q_3m  # default pour les calculs uniques

    # ── 4. Date de pricing ───────────────────────────────────────────────
    st.markdown("### 📅 Date de Pricing")
    pricing_date = st.date_input("Date spot", value=datetime.date.today())

    # ── 5. Paramètres du contrat ─────────────────────────────────────────
    st.markdown("### ⚙️ Contrat")
    multiplier = st.number_input(
        "Multiplicateur (MAD/point)",
        min_value=1, max_value=1000, value=CONTRACT_MULTIPLIER, step=1,
        help="Taille du contrat MASI20 : 10 MAD par point d'indice"
    )

    st.markdown("---")
    st.markdown('<div class="footer">Formule : F₀ = S₀ · e^((r−q)·T)<br>Hull (2022) — Modèle d\'absence d\'arbitrage</div>', unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════
# ── MAIN PAGE ─────────────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════

# Header
st.markdown("""
<div class="main-header">
    <h1>📈 MASI20 Futures Pricer</h1>
    <p>Pricing théorique des contrats futures sur l'indice MASI20 — Bourse de Casablanca</p>
</div>
""", unsafe_allow_html=True)

# Vérification ZC
if zc_df is None:
    st.markdown("""
    <div class="warn-banner">
    ⚠️ <b>Aucun fichier ZC importé.</b> Veuillez charger votre fichier <code>ZC_Rate.xlsx</code> 
    dans la barre latérale pour activer le pricing. Le fichier doit contenir les colonnes : 
    <code>date_spot</code> | <code>date_maturity</code> | <code>zc</code>
    </div>
    """, unsafe_allow_html=True)
    st.stop()

# ── ONGLETS ────────────────────────────────────────────────────────────────
tab1, tab2, tab3, tab4 = st.tabs([
    "📊 Pricing Standard",
    "🗓️ Échéances Trimestrielles",
    "📉 Courbe des Taux ZC",
    "ℹ️ Méthodologie"
])


# ════════════════════════════════════════════════════════
# TAB 1 — PRICING STANDARD
# ════════════════════════════════════════════════════════
with tab1:

    # Formule
    st.markdown('<div class="section-title">Formule d\'Absence d\'Arbitrage</div>', unsafe_allow_html=True)
    st.markdown("""
    <div class="formula-box">
    F₀ = S₀ × exp( (r − q) × T )
    <br><br>
    S₀ : Niveau spot de l'indice &nbsp;|&nbsp; r : Taux sans risque (ZC interpolé) &nbsp;|&nbsp; q : Rendement dividende &nbsp;|&nbsp; T : Maturité (années)
    </div>
    """, unsafe_allow_html=True)

    # Construire la map q selon le mode
    if q_mode == "Par maturité (avancé)":
        maturities_with_q = q_map
    else:
        maturities_with_q = {k: q for k in STANDARD_MATURITIES}

    # Pricing
    rows = []
    for label, T in STANDARD_MATURITIES.items():
        q_used = maturities_with_q.get(label, q)
        r = interpolate_rate(zc_df, T)
        F0 = price_future(S0, r, q_used, T)
        notional = notional_value(F0, multiplier)
        base = S0 - F0
        carry = (r - q_used) * T * 100

        rows.append({
            "Maturité": label,
            "T (ans)": T,
            "r (%)": round(r * 100, 4),
            "q (%)": round(q_used * 100, 2),
            "r − q (%)": round((r - q_used) * 100, 4),
            "F₀ (points)": round(F0, 2),
            "Notionnel (MAD)": round(notional, 2),
            "Base (S₀ − F₀)": round(base, 2),
            "Carry (%)": round(carry, 4),
        })

    df_pricing = pd.DataFrame(rows)

    # ── Metrics clés ──────────────────────────────────────────────────────
    st.markdown('<div class="section-title">Résultats du Pricing</div>', unsafe_allow_html=True)

    cols = st.columns(4)
    for i, row in enumerate(rows):
        with cols[i]:
            delta_pct = ((row["F₀ (points)"] / S0) - 1) * 100
            delta_str = f"{'▲' if delta_pct >= 0 else '▼'} {abs(delta_pct):.2f}% vs Spot"
            st.markdown(f"""
            <div class="metric-card">
                <div class="label">{row['Maturité']}</div>
                <div class="value">{row['F₀ (points)']:,.2f}</div>
                <div class="sub">{delta_str}</div>
                <div class="sub">Notionnel : {row['Notionnel (MAD)']:,.0f} MAD</div>
            </div>
            """, unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    # ── Tableau détaillé ──────────────────────────────────────────────────
    st.markdown('<div class="section-title">Tableau Détaillé</div>', unsafe_allow_html=True)

    df_display = df_pricing.copy()
    df_display["Notionnel (MAD)"] = df_display["Notionnel (MAD)"].apply(lambda x: f"{x:,.2f}")
    df_display["F₀ (points)"] = df_display["F₀ (points)"].apply(lambda x: f"{x:,.2f}")
    df_display["Base (S₀ − F₀)"] = df_display["Base (S₀ − F₀)"].apply(lambda x: f"{x:+,.2f}")

    st.dataframe(df_display, use_container_width=True, hide_index=True)

    # ── Graphique : Structure par terme ───────────────────────────────────
    st.markdown('<div class="section-title">Structure par Terme des Futures</div>', unsafe_allow_html=True)

    T_range = np.linspace(0.05, 1.2, 200)
    q_plot = q if q_mode == "Valeur fixe" else sum(maturities_with_q.values()) / len(maturities_with_q)

    F_curve = []
    for T in T_range:
        r_t = interpolate_rate(zc_df, T)
        F_curve.append(price_future(S0, r_t, q_plot, T))

    fig = go.Figure()

    # Courbe continue
    fig.add_trace(go.Scatter(
        x=T_range * 12, y=F_curve,
        mode="lines", name="Prix Future F₀(T)",
        line=dict(color="#2E7D4F", width=2.5),
        hovertemplate="T = %{x:.1f} mois<br>F₀ = %{y:,.2f} pts<extra></extra>"
    ))

    # Points discrets
    fig.add_trace(go.Scatter(
        x=[r["T (ans)"] * 12 for r in rows],
        y=[r["F₀ (points)"] for r in rows],
        mode="markers+text",
        marker=dict(size=12, color="#1B4F2D", symbol="diamond"),
        text=[r["Maturité"] for r in rows],
        textposition="top center",
        name="Échéances standard",
        hovertemplate="<b>%{text}</b><br>F₀ = %{y:,.2f} pts<extra></extra>"
    ))

    # Niveau spot
    fig.add_hline(
        y=S0, line_dash="dot", line_color="#ef4444",
        annotation_text=f"Spot S₀ = {S0:,.2f}",
        annotation_position="bottom right"
    )

    fig.update_layout(
        xaxis_title="Maturité (mois)",
        yaxis_title="Prix du Future (points)",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        plot_bgcolor="white",
        paper_bgcolor="white",
        height=420,
        margin=dict(l=20, r=20, t=40, b=20),
        xaxis=dict(showgrid=True, gridcolor="#f3f4f6"),
        yaxis=dict(showgrid=True, gridcolor="#f3f4f6"),
    )
    st.plotly_chart(fig, use_container_width=True)

    # ── Note pédagogique sur q ────────────────────────────────────────────
    st.markdown('<div class="section-title">💡 Note sur le Taux de Dividende q</div>', unsafe_allow_html=True)
    
    col_a, col_b = st.columns(2)
    with col_a:
        st.markdown("""
        **Comment est calculé q ?**
        
        Le taux de dividende de l'indice MASI20 représente la somme pondérée des dividendes versés par les 20 composantes, rapportée à la valeur de l'indice :
        
        $$q = \\frac{\\sum_{i=1}^{20} w_i \\cdot D_i}{S_0}$$
        
        où $w_i$ est le poids de la composante $i$ et $D_i$ son dividende annuel.
        """)
    with col_b:
        st.markdown("""
        **q est-il constant ?** Non. Il varie selon :
        
        - 📅 **La saisonnalité** : les dividendes marocains sont concentrés sur **mars–juin** (AG des sociétés)
        - 📈 **Le niveau de l'indice** : si S₀ monte, q baisse mécaniquement
        - 🏢 **Les décisions des sociétés** : payouts variables d'une année à l'autre
        
        **Valeur typique** : ~3–4% pour le MASI20 en condition normale de marché.
        """)


# ════════════════════════════════════════════════════════
# TAB 2 — ÉCHÉANCES TRIMESTRIELLES
# ════════════════════════════════════════════════════════
with tab2:
    st.markdown('<div class="section-title">Prochaines Échéances Trimestrielles MASI20</div>', unsafe_allow_html=True)
    st.markdown("""
    <div class="info-banner">
    Les contrats MASI20 expirent le <b>dernier vendredi de Mars, Juin, Septembre et Décembre</b> (échéances trimestrielles standardisées).
    </div>
    """, unsafe_allow_html=True)

    df_quarterly = price_quarterly_expirations(S0, q, zc_df, pricing_date)

    if not df_quarterly.empty:
        # Metrics
        cols_q = st.columns(len(df_quarterly))
        for i, row in df_quarterly.iterrows():
            with cols_q[i]:
                delta = ((row["F₀ (points)"] / S0) - 1) * 100
                st.markdown(f"""
                <div class="metric-card">
                    <div class="label">{row['Échéance']}</div>
                    <div class="value">{row['F₀ (points)']:,.2f}</div>
                    <div class="sub">Exp. {row['Date Expiration']}</div>
                    <div class="sub">{'▲' if delta >= 0 else '▼'} {abs(delta):.2f}% vs Spot</div>
                </div>
                """, unsafe_allow_html=True)

        st.markdown("<br>", unsafe_allow_html=True)

        # Tableau
        df_q_display = df_quarterly.copy()
        df_q_display["Notionnel (MAD)"] = df_q_display["Notionnel (MAD)"].apply(lambda x: f"{x:,.2f}")
        df_q_display["F₀ (points)"] = df_q_display["F₀ (points)"].apply(lambda x: f"{x:,.2f}")
        df_q_display["Base (S₀ − F₀)"] = df_q_display["Base (S₀ − F₀)"].apply(lambda x: f"{x:+,.2f}")
        st.dataframe(df_q_display, use_container_width=True, hide_index=True)

        # Graphe Base
        st.markdown('<div class="section-title">Convergence de la Base vers Zéro</div>', unsafe_allow_html=True)

        fig2 = go.Figure()
        fig2.add_trace(go.Bar(
            x=df_quarterly["Échéance"],
            y=df_quarterly["Base (S₀ − F₀)"],
            marker_color=["#2E7D4F" if v < 0 else "#ef4444" for v in df_quarterly["Base (S₀ − F₀)"]],
            name="Base = S₀ − F₀",
            hovertemplate="<b>%{x}</b><br>Base = %{y:+,.2f} pts<extra></extra>"
        ))
        fig2.add_hline(y=0, line_dash="dash", line_color="gray")
        fig2.update_layout(
            yaxis_title="Base (points)",
            plot_bgcolor="white", paper_bgcolor="white",
            height=320, margin=dict(l=20, r=20, t=20, b=20),
        )
        st.plotly_chart(fig2, use_container_width=True)

        st.markdown("""
        > **Lecture** : Une base négative (F₀ > S₀) indique que le *cost of carry* (r − q) est positif, 
        c'est-à-dire que le coût de financement dépasse le rendement en dividendes. 
        La base converge vers zéro à l'approche de l'échéance.
        """)


# ════════════════════════════════════════════════════════
# TAB 3 — COURBE DES TAUX ZC
# ════════════════════════════════════════════════════════
with tab3:
    st.markdown('<div class="section-title">Courbe des Taux Zéro-Coupon Importée</div>', unsafe_allow_html=True)

    if zc_df is not None:
        col_info1, col_info2, col_info3 = st.columns(3)
        with col_info1:
            st.metric("Date Spot", zc_df["date_spot"].iloc[0].strftime("%d/%m/%Y") if "date_spot" in zc_df.columns else "N/A")
        with col_info2:
            st.metric("Points de courbe", len(zc_df))
        with col_info3:
            st.metric("Plage de maturité", f"{zc_df['T'].min():.2f}–{zc_df['T'].max():.1f} ans")

        # Courbe ZC
        fig3 = go.Figure()
        fig3.add_trace(go.Scatter(
            x=zc_df["T"] * 12, y=zc_df["zc"],
            mode="markers+lines",
            marker=dict(size=6, color="#2E7D4F"),
            line=dict(color="#2E7D4F", width=1.5),
            name="Taux ZC",
            hovertemplate="T = %{x:.1f} mois<br>ZC = %{y:.4f}%<extra></extra>"
        ))

        # Marquer les maturités utilisées pour le pricing
        for label, T in STANDARD_MATURITIES.items():
            r_mark = interpolate_rate(zc_df, T)
            fig3.add_trace(go.Scatter(
                x=[T * 12], y=[r_mark * 100],
                mode="markers", marker=dict(size=12, color="#ef4444", symbol="x"),
                name=f"r({label}) = {r_mark*100:.4f}%",
                hovertemplate=f"<b>{label}</b><br>r = {r_mark*100:.4f}%<extra></extra>"
            ))

        fig3.update_layout(
            xaxis_title="Maturité (mois)",
            yaxis_title="Taux ZC (%)",
            plot_bgcolor="white", paper_bgcolor="white",
            height=420, margin=dict(l=20, r=20, t=20, b=20),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        )
        st.plotly_chart(fig3, use_container_width=True)

        # Tableau des taux interpolés aux maturités standard
        st.markdown('<div class="section-title">Taux r Interpolés aux Maturités Standard</div>', unsafe_allow_html=True)
        interp_rows = []
        for label, T in STANDARD_MATURITIES.items():
            r_val = interpolate_rate(zc_df, T)
            interp_rows.append({"Maturité": label, "T (années)": T, "r interpolé (%)": round(r_val * 100, 5)})
        st.dataframe(pd.DataFrame(interp_rows), use_container_width=True, hide_index=True)

        # Données brutes
        with st.expander("📋 Données brutes ZC"):
            st.dataframe(zc_df[["date_maturity", "T", "zc"]].rename(columns={
                "date_maturity": "Date Maturité", "T": "T (années)", "zc": "ZC (%)"
            }), use_container_width=True, hide_index=True)


# ════════════════════════════════════════════════════════
# TAB 4 — MÉTHODOLOGIE
# ════════════════════════════════════════════════════════
with tab4:
    st.markdown('<div class="section-title">Modèle de Pricing</div>', unsafe_allow_html=True)

    col_m1, col_m2 = st.columns(2)

    with col_m1:
        st.markdown("""
        #### Formule d'Absence d'Arbitrage
        
        Dans un cadre théorique avec dividendes continus au taux moyen *q* :
        
        $$F_0 = S_0 \\cdot e^{(r - q) \\cdot T}$$
        
        **Paramètres :**
        | Symbole | Description | Source |
        |---------|-------------|--------|
        | S₀ | Niveau spot MASI20 | Scraping Bourse de Casablanca |
        | r | Taux sans risque | Courbe ZC (interpolation linéaire) |
        | q | Rendement dividende | Saisie utilisateur (~3–4%) |
        | T | Maturité (années) | Calculée depuis la date spot |
        
        #### Valeur Notionnelle
        
        $$\\text{Notionnel} = F_0 \\times \\text{Multiplicateur}$$
        
        Multiplicateur MASI20 = **10 MAD / point d'indice**
        """)

    with col_m2:
        st.markdown("""
        #### Spécifications du Contrat MASI20
        
        | Caractéristique | Valeur |
        |-----------------|--------|
        | Sous-jacent | MASI20 |
        | Multiplicateur | 10 MAD/point |
        | Pas de cotation | 0.1 point (= 1 MAD) |
        | Échéances | Mars, Juin, Sep, Déc |
        | Dernier jour | Dernier vendredi du mois |
        | Dénouement | Cash settlement |
        | Dépôt de garantie | 1 000 MAD (révisable) |
        
        #### Limites du Modèle V1
        
        - q supposé constant sur la période (simplification)
        - Pas de prise en compte du *marking to market* quotidien
        - La courbe ZC est supposée être celle du jour de pricing
        - La maturité est alignée sur les dates standard et non les échéances exactes
        """)

    st.markdown('<div class="section-title">Roadmap des Fonctionnalités</div>', unsafe_allow_html=True)

    col_v1, col_v2 = st.columns(2)
    with col_v1:
        st.markdown("""
        #### ✅ Version 1 (actuelle)
        - Pricing F₀ = S₀·e^((r−q)·T)
        - Interpolation de r depuis courbe ZC importée
        - Scraping automatique du MASI20
        - Maturités standard (3M, 6M, 9M, 1Y)
        - Échéances trimestrielles réelles
        - Visualisation de la structure par terme
        - Gestion intelligente de q
        """)
    with col_v2:
        st.markdown("""
        #### 🚧 Version 2 (planifiée)
        - **Couverture par contrats futures** (N* = β × P/A)
        - Calcul automatique du **bêta** par régression
        - Upload historique de portefeuille
        - Simulation P&L de couverture
        - Export PDF du rapport de pricing
        - Alertes d'arbitrage (F₀ vs valeur théorique)
        """)

    st.markdown("""
    ---
    <div class="footer">
    MASI20 Futures Pricer — CDG Capital | 
    Basé sur : <i>Options, Futures and Other Derivatives</i>, J.C. Hull (2022) | 
    Marché à Terme — Bourse de Casablanca
    </div>
    """, unsafe_allow_html=True)
