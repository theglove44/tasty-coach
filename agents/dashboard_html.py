"""
HTML renderer for the Market Quality Dashboard.

Produces a self-contained HTML file matching the dark terminal aesthetic
from the Perplexity market-scoring screenshot.
"""

import html
import os
import tempfile
import webbrowser
from datetime import datetime
from typing import Dict, List, Optional, Tuple

# Reuse constants from the main dashboard module
from agents.dashboard import (
    DashboardAgent, SECTOR_ETFS, SECTOR_NAMES, WEIGHTS,
    CYCLICAL_SECTORS, DEFENSIVE_SECTORS,
)


def _score_color_hex(score: float) -> str:
    if score >= 75:
        return "#22c55e"
    elif score >= 50:
        return "#eab308"
    return "#ef4444"


def _decision_color(label: str) -> str:
    return {"YES": "#22c55e", "CAUTION": "#eab308", "NO": "#ef4444"}.get(label, "#ef4444")


def _fmt(val, fmt_str: str = ".1f", fallback: str = "N/A") -> str:
    if val is None:
        return fallback
    return f"{val:{fmt_str}}"


def _pct(val, fallback="N/A") -> str:
    if val is None:
        return fallback
    return f"{val:+.1f}%"


def _check(b) -> str:
    if b:
        return '<span class="check-yes">&#10003;</span>'
    return '<span class="check-no">&#10007;</span>'


def _label_tag(text: str, color: str) -> str:
    return f'<span class="label" style="background:{color}33;color:{color};border:1px solid {color}55">{html.escape(text)}</span>'


def _bar_html(value: float, max_abs: float = 5.0) -> str:
    """Horizontal bar for sector returns."""
    pct = min(abs(value) / max_abs * 100, 100)
    color = "#22c55e" if value >= 0 else "#ef4444"
    return f'<div class="bar-track"><div class="bar-fill" style="width:{pct}%;background:{color}"></div></div>'


def render_html(agent: DashboardAgent) -> str:
    """Generate a full self-contained HTML dashboard string."""
    label, _ = agent.decision()
    color = _decision_color(label)
    composite = agent.composite
    now_str = datetime.now().strftime("%b %d, %Y  %I:%M %p ET")

    # Gather data from pillar details
    vol = agent.pillar_details.get('volatility', {})
    trend = agent.pillar_details.get('trend', {})
    breadth = agent.pillar_details.get('breadth', {})
    momentum = agent.pillar_details.get('momentum', {})
    macro = agent.pillar_details.get('macro', {})

    # Ticker bar data
    ticker_items = []
    for sym in ['SPY', 'QQQ'] + SECTOR_ETFS:
        d = agent.equity_data.get(sym)
        if d and d.last and d.prev_close:
            last = float(d.last)
            prev = float(d.prev_close)
            chg = last - prev
            pct_chg = (chg / prev) * 100 if prev else 0
            c = "#22c55e" if chg >= 0 else "#ef4444"
            ticker_items.append(
                f'<span class="ticker-item"><span class="ticker-sym">{sym}</span> '
                f'<span style="color:{c}">{last:,.2f} {pct_chg:+.2f}%</span></span>'
            )
    # VIX
    vix_price = vol.get('vix_level')
    if vix_price:
        ticker_items.append(
            f'<span class="ticker-item"><span class="ticker-sym">VIX</span> '
            f'<span style="color:#eab308">{vix_price:.2f}</span></span>'
        )

    ticker_html = " ".join(ticker_items)

    # Sector returns for bar chart
    sector_returns = momentum.get('sector_returns', {})
    valid_returns = {k: v for k, v in sector_returns.items() if v is not None}
    sorted_sectors = sorted(valid_returns.items(), key=lambda x: x[1], reverse=True)
    max_abs_ret = max((abs(v) for v in valid_returns.values()), default=1)

    sector_rows = ""
    for etf, ret in sorted_sectors:
        name = SECTOR_NAMES.get(etf, etf)
        c = "#22c55e" if ret >= 0 else "#ef4444"
        sector_rows += f'''
        <div class="sector-row">
            <span class="sector-name">{name}</span>
            <span class="sector-val" style="color:{c}">{ret:+.1f}%</span>
            {_bar_html(ret, max_abs_ret)}
        </div>'''

    # Score gauge pillars
    def pillar_gauge(name: str, score: float, weight: float) -> str:
        sc = _score_color_hex(score)
        pct = score / 100 * 251.2  # circumference of r=40 circle
        return f'''
        <div class="pillar-gauge">
            <svg viewBox="0 0 100 100" class="gauge-svg">
                <circle cx="50" cy="50" r="40" fill="none" stroke="#1e293b" stroke-width="8"/>
                <circle cx="50" cy="50" r="40" fill="none" stroke="{sc}" stroke-width="8"
                    stroke-dasharray="{pct} 251.2" stroke-linecap="round"
                    transform="rotate(-90 50 50)"/>
                <text x="50" y="48" text-anchor="middle" fill="{sc}" font-size="22" font-weight="700">{score:.0f}</text>
                <text x="50" y="64" text-anchor="middle" fill="#94a3b8" font-size="9">{name.upper()}</text>
            </svg>
            <div class="gauge-weight">{weight:.0%}</div>
        </div>'''

    gauges_html = ""
    for pname in WEIGHTS:
        s = agent.pillar_scores.get(pname, 0)
        gauges_html += pillar_gauge(pname, s, WEIGHTS[pname])

    # Volatility card
    vix_level = vol.get('vix_level')
    vix_trend_val = vol.get('vix_trend')
    vix_ivp = vol.get('vix_ivp')
    pcr = vol.get('pcr')
    vix_trend_label = "Falling" if (vix_trend_val and vix_trend_val < -2) else ("Rising" if (vix_trend_val and vix_trend_val > 2) else "Flat")
    vix_trend_color = "#22c55e" if vix_trend_label == "Falling" else ("#ef4444" if vix_trend_label == "Rising" else "#eab308")

    vol_score = agent.pillar_scores.get('volatility', 0)
    vol_color = _score_color_hex(vol_score)

    # Trend card
    regime = trend.get('regime', '?')
    spy_price = trend.get('spy_price')
    rsi = trend.get('rsi')
    trend_score = agent.pillar_scores.get('trend', 0)
    trend_color = _score_color_hex(trend_score)

    # Regime color
    regime_colors = {
        'Strong Uptrend': '#22c55e', 'Uptrend': '#22c55e',
        'Choppy': '#eab308', 'Downtrend': '#ef4444',
    }
    regime_color = regime_colors.get(regime, '#94a3b8')

    # Breadth card
    sectors_above = breadth.get('sectors_above_50ma', 0)
    breadth_score = agent.pillar_scores.get('breadth', 0)
    breadth_color = _score_color_hex(breadth_score)
    sector_status = breadth.get('sector_status', {})

    # Momentum card
    sectors_pos = momentum.get('sectors_positive', 0)
    spread = momentum.get('spread')
    top3 = momentum.get('top3', [])
    cyclical_leading = momentum.get('cyclical_leading', 0)
    rotation = "Risk-On" if cyclical_leading >= 2 else ("Defensive" if cyclical_leading == 0 else "Mixed")
    rotation_color = "#22c55e" if rotation == "Risk-On" else ("#ef4444" if rotation == "Defensive" else "#eab308")
    mom_score = agent.pillar_scores.get('momentum', 0)
    mom_color = _score_color_hex(mom_score)

    # Macro card
    tlt_price = macro.get('tlt_price')
    tlt_slope = macro.get('tlt_slope')
    dollar_slope = macro.get('dollar_slope')
    macro_score = agent.pillar_scores.get('macro', 0)
    macro_color = _score_color_hex(macro_score)
    bond_label = "Rising" if (tlt_slope and tlt_slope > 1) else ("Falling" if (tlt_slope and tlt_slope < -1) else "Flat")
    bond_label_color = "#22c55e" if bond_label == "Rising" else ("#ef4444" if bond_label == "Falling" else "#eab308")
    dollar_label = "Strengthening" if (dollar_slope and dollar_slope > 0.5) else ("Weakening" if (dollar_slope and dollar_slope < -0.5) else "Flat")
    dollar_label_color = "#ef4444" if dollar_label == "Strengthening" else ("#22c55e" if dollar_label == "Weakening" else "#eab308")

    # Scoring weights table
    weight_rows = ""
    for pname in WEIGHTS:
        s = agent.pillar_scores.get(pname, 0)
        w = WEIGHTS[pname]
        ws = s * w
        sc = _score_color_hex(s)
        weight_rows += f'''
        <tr>
            <td>{pname.capitalize()}</td>
            <td style="color:{sc}">{s:.0f}</td>
            <td class="dim">{w:.0%}</td>
            <td style="color:{sc}">{ws:.1f}</td>
        </tr>'''

    # Guidance text
    if label == 'YES':
        guidance = "Full size, press risk. Conditions favor premium selling."
        guidance_icon = "rocket"
    elif label == 'CAUTION':
        guidance = "Half size, A+ setups only. Mixed signals — be selective."
        guidance_icon = "warning"
    else:
        guidance = "Sit on hands. Preserve capital. Wait for conditions to improve."
        guidance_icon = "stop"

    # Position sizing label
    if composite >= 80:
        sizing = "FULL SIZE"
        sizing_desc = "Press risk"
    elif composite >= 60:
        sizing = "HALF SIZE"
        sizing_desc = "A+ setups only"
    else:
        sizing = "MINIMAL"
        sizing_desc = "Preserve capital"

    # Terminal analysis
    analysis_parts = []
    analysis_parts.append(f"The current environment scores {composite:.0f}/100")
    if composite < 60:
        analysis_parts.append(f"— well below the 60-point threshold for active sizing.")
    elif composite < 80:
        analysis_parts.append(f"— in the cautious zone, requiring high-conviction setups only.")
    else:
        analysis_parts.append(f"— above the 80-point threshold, favoring full engagement.")

    if vix_level:
        analysis_parts.append(f" VIX at {vix_level:.1f}")
        if vix_ivp:
            analysis_parts.append(f" ({vix_ivp:.0f}th percentile)")
        if vix_trend_val and vix_trend_val < -3:
            analysis_parts.append(" is falling sharply, which is constructive.")
        elif vix_trend_val and vix_trend_val > 3:
            analysis_parts.append(" is rising fast — elevated fear.")
        else:
            analysis_parts.append(".")

    analysis_parts.append(f" Market breadth is {'strong' if sectors_above >= 8 else 'weak' if sectors_above < 5 else 'mixed'}")
    analysis_parts.append(f" with {sectors_above}/11 sectors above their 50d MA.")

    if regime:
        analysis_parts.append(f" Regime: {regime}.")
    if rsi:
        if rsi < 30:
            analysis_parts.append(f" RSI at {rsi:.0f} signals oversold conditions — watch for reversal.")
        elif rsi > 70:
            analysis_parts.append(f" RSI at {rsi:.0f} signals overbought — risk of pullback.")

    analysis_parts.append(f" Sector rotation is {rotation.lower()}")
    if top3:
        analysis_parts.append(f" with {', '.join(SECTOR_NAMES.get(t, t) for t in top3)} leading.")
    else:
        analysis_parts.append(".")

    terminal_analysis = "".join(analysis_parts)

    # Warnings
    warnings_html = ""
    if agent.warnings:
        items = "".join(f"<li>{html.escape(w)}</li>" for w in agent.warnings)
        warnings_html = f'<div class="warnings-box"><div class="warnings-title">Data Warnings</div><ul>{items}</ul></div>'

    return f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Should I Be Trading? — Market Quality Terminal</title>
<style>
  :root {{
    --bg: #0a0e1a;
    --surface: #111827;
    --surface2: #1a2036;
    --border: #1e293b;
    --text: #e2e8f0;
    --dim: #64748b;
    --green: #22c55e;
    --yellow: #eab308;
    --red: #ef4444;
    --blue: #3b82f6;
    --cyan: #06b6d4;
  }}
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{
    font-family: 'SF Mono', 'Fira Code', 'Cascadia Code', 'JetBrains Mono', monospace;
    background: var(--bg);
    color: var(--text);
    font-size: 13px;
    line-height: 1.5;
    min-height: 100vh;
  }}

  /* ── Ticker Bar ──────────────────────────────────────── */
  .ticker-bar {{
    background: var(--surface);
    border-bottom: 1px solid var(--border);
    padding: 8px 20px;
    display: flex;
    align-items: center;
    gap: 20px;
    overflow-x: auto;
    white-space: nowrap;
    font-size: 12px;
  }}
  .ticker-item {{ display: inline-flex; gap: 6px; align-items: center; }}
  .ticker-sym {{ color: var(--dim); font-weight: 600; }}

  /* ── Header ──────────────────────────────────────────── */
  .header {{
    background: var(--surface);
    border-bottom: 1px solid var(--border);
    padding: 12px 20px;
    display: flex;
    justify-content: space-between;
    align-items: center;
  }}
  .header-title {{
    font-size: 15px;
    font-weight: 700;
    letter-spacing: 1px;
    color: var(--text);
  }}
  .header-subtitle {{
    color: var(--dim);
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 2px;
  }}
  .header-right {{ display: flex; gap: 16px; align-items: center; }}
  .header-badge {{
    padding: 4px 12px;
    border-radius: 4px;
    font-weight: 700;
    font-size: 11px;
    letter-spacing: 1px;
  }}

  /* ── Main Layout ─────────────────────────────────────── */
  .container {{ max-width: 1400px; margin: 0 auto; padding: 16px 20px; }}

  /* ── Hero Section ────────────────────────────────────── */
  .hero {{
    display: grid;
    grid-template-columns: auto 1fr auto;
    gap: 24px;
    align-items: center;
    margin-bottom: 16px;
    padding: 20px;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 8px;
  }}
  .hero-decision {{
    text-align: center;
    min-width: 120px;
  }}
  .decision-label {{
    font-size: 28px;
    font-weight: 900;
    letter-spacing: 2px;
    padding: 8px 20px;
    border-radius: 6px;
    display: inline-block;
  }}
  .decision-sub {{
    font-size: 11px;
    color: var(--dim);
    margin-top: 6px;
  }}

  .hero-score {{
    text-align: center;
  }}
  .score-big {{
    font-size: 64px;
    font-weight: 900;
    line-height: 1;
  }}
  .score-max {{
    font-size: 20px;
    color: var(--dim);
    font-weight: 400;
  }}

  .hero-gauges {{
    display: flex;
    gap: 8px;
    align-items: center;
  }}
  .pillar-gauge {{ text-align: center; width: 80px; }}
  .gauge-svg {{ width: 70px; height: 70px; }}
  .gauge-weight {{ font-size: 10px; color: var(--dim); margin-top: 2px; }}

  .hero-sizing {{
    text-align: center;
    padding: 12px 20px;
    background: var(--surface2);
    border-radius: 6px;
    border: 1px solid var(--border);
  }}
  .sizing-label {{
    font-size: 16px;
    font-weight: 700;
    letter-spacing: 1px;
  }}
  .sizing-desc {{
    font-size: 11px;
    color: var(--dim);
    margin-top: 2px;
  }}

  /* ── Guidance Banner ─────────────────────────────────── */
  .guidance {{
    padding: 12px 16px;
    border-radius: 6px;
    margin-bottom: 16px;
    font-size: 13px;
    border: 1px solid;
  }}

  /* ── Cards Grid ──────────────────────────────────────── */
  .cards {{
    display: grid;
    grid-template-columns: repeat(5, 1fr);
    gap: 12px;
    margin-bottom: 16px;
  }}
  .card {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 14px;
    border-top: 3px solid;
  }}
  .card-header {{
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 10px;
  }}
  .card-title {{
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 1px;
    text-transform: uppercase;
    color: var(--dim);
  }}
  .card-score {{
    font-size: 22px;
    font-weight: 800;
  }}
  .card-row {{
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 3px 0;
    font-size: 12px;
  }}
  .card-row .lbl {{ color: var(--dim); }}
  .card-row .val {{ font-weight: 600; }}

  .label {{
    display: inline-block;
    padding: 1px 8px;
    border-radius: 3px;
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.5px;
  }}

  .check-yes {{ color: var(--green); font-weight: bold; }}
  .check-no {{ color: var(--red); font-weight: bold; opacity: 0.5; }}

  /* ── Bottom Grid ─────────────────────────────────────── */
  .bottom {{
    display: grid;
    grid-template-columns: 1fr 1fr 1fr;
    gap: 12px;
    margin-bottom: 16px;
  }}
  .panel {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 14px;
  }}
  .panel-title {{
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 1px;
    text-transform: uppercase;
    color: var(--dim);
    margin-bottom: 10px;
    display: flex;
    align-items: center;
    gap: 6px;
  }}
  .panel-title::before {{
    content: '';
    width: 8px;
    height: 8px;
    border-radius: 50%;
  }}

  /* Sector bars */
  .sector-row {{
    display: grid;
    grid-template-columns: 100px 50px 1fr;
    align-items: center;
    gap: 8px;
    padding: 2px 0;
    font-size: 12px;
  }}
  .sector-name {{ color: var(--dim); }}
  .sector-val {{ text-align: right; font-weight: 600; }}
  .bar-track {{
    height: 8px;
    background: var(--surface2);
    border-radius: 4px;
    overflow: hidden;
  }}
  .bar-fill {{
    height: 100%;
    border-radius: 4px;
    transition: width 0.3s;
  }}

  /* Scoring weights */
  .weights-table {{
    width: 100%;
    border-collapse: collapse;
    font-size: 12px;
  }}
  .weights-table th {{
    color: var(--dim);
    text-align: left;
    font-weight: 600;
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 1px;
    padding: 4px 0;
    border-bottom: 1px solid var(--border);
  }}
  .weights-table td {{
    padding: 5px 0;
    border-bottom: 1px solid #111;
  }}
  .weights-table tr:last-child td {{
    border-top: 1px solid var(--border);
    font-weight: 700;
    font-size: 14px;
    padding-top: 8px;
  }}
  .dim {{ color: var(--dim); }}

  /* ── Terminal Analysis ───────────────────────────────── */
  .terminal {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 14px;
    margin-bottom: 16px;
  }}
  .terminal-header {{
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 1px;
    text-transform: uppercase;
    color: var(--cyan);
    margin-bottom: 8px;
  }}
  .terminal-body {{
    color: var(--dim);
    font-size: 12px;
    line-height: 1.7;
  }}
  .terminal-body strong {{ color: var(--text); }}

  /* ── Warnings ────────────────────────────────────────── */
  .warnings-box {{
    background: #1a1500;
    border: 1px solid #eab30833;
    border-radius: 6px;
    padding: 10px 14px;
    margin-bottom: 16px;
    font-size: 11px;
  }}
  .warnings-title {{
    color: var(--yellow);
    font-weight: 600;
    margin-bottom: 4px;
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 1px;
  }}
  .warnings-box ul {{
    list-style: none;
    color: #ca8a04;
  }}
  .warnings-box li::before {{
    content: '\\26A0  ';
  }}

  /* ── Footer ──────────────────────────────────────────── */
  .footer {{
    text-align: center;
    color: var(--dim);
    font-size: 10px;
    padding: 12px;
    border-top: 1px solid var(--border);
  }}

  /* ── Responsive ──────────────────────────────────────── */
  @media (max-width: 1200px) {{
    .cards {{ grid-template-columns: repeat(3, 1fr); }}
    .hero {{ grid-template-columns: auto 1fr; }}
  }}
  @media (max-width: 800px) {{
    .cards {{ grid-template-columns: 1fr 1fr; }}
    .bottom {{ grid-template-columns: 1fr; }}
    .hero-gauges {{ flex-wrap: wrap; }}
  }}
</style>
</head>
<body>

<!-- Ticker Bar -->
<div class="ticker-bar">{ticker_html}</div>

<!-- Header -->
<div class="header">
    <div>
        <div class="header-title">SHOULD I BE TRADING?</div>
        <div class="header-subtitle">Market Quality Terminal</div>
    </div>
    <div class="header-right">
        <span style="color:var(--dim)">{now_str}</span>
    </div>
</div>

<div class="container">

<!-- Hero -->
<div class="hero">
    <div class="hero-decision">
        <div class="decision-label" style="background:{color}22;color:{color};border:2px solid {color}">{label}</div>
        <div class="decision-sub">{"Going Trading" if label == "YES" else ("Use Caution" if label == "CAUTION" else "Stay Out")}</div>
    </div>
    <div style="display:flex;align-items:center;gap:32px;">
        <div class="hero-score">
            <div class="score-big" style="color:{color}">{composite:.0f}<span class="score-max"> / 100</span></div>
        </div>
        <div class="hero-gauges">
            {gauges_html}
        </div>
    </div>
    <div class="hero-sizing">
        <div class="sizing-label" style="color:{color}">{sizing}</div>
        <div class="sizing-desc">{sizing_desc}</div>
    </div>
</div>

<!-- Guidance -->
<div class="guidance" style="background:{color}0a;border-color:{color}33;color:{color}">
    {html.escape(guidance)}
</div>

<!-- 5 Pillar Cards -->
<div class="cards">

    <!-- Volatility -->
    <div class="card" style="border-top-color:{vol_color}">
        <div class="card-header">
            <span class="card-title">Volatility</span>
            <span class="card-score" style="color:{vol_color}">{vol_score:.0f}</span>
        </div>
        <div class="card-row"><span class="lbl">VIX Level</span><span class="val">{_fmt(vix_level, '.1f')}</span></div>
        <div class="card-row"><span class="lbl">VIX Trend</span>{_label_tag(vix_trend_label, vix_trend_color)}</div>
        <div class="card-row"><span class="lbl">VIX IV %ile</span><span class="val">{_fmt(vix_ivp, '.0f')}%</span></div>
        <div class="card-row"><span class="lbl">Put/Call</span><span class="val">{_fmt(pcr, '.2f')}</span></div>
    </div>

    <!-- Trend -->
    <div class="card" style="border-top-color:{trend_color}">
        <div class="card-header">
            <span class="card-title">Trend</span>
            <span class="card-score" style="color:{trend_color}">{trend_score:.0f}</span>
        </div>
        <div class="card-row"><span class="lbl">Regime</span>{_label_tag(regime, regime_color)}</div>
        <div class="card-row"><span class="lbl">SPY vs 20d</span><span class="val">{_check(trend.get('spy_above_20'))}</span></div>
        <div class="card-row"><span class="lbl">SPY vs 50d</span><span class="val">{_check(trend.get('spy_above_50'))}</span></div>
        <div class="card-row"><span class="lbl">SPY vs 200d</span><span class="val">{_check(trend.get('spy_above_200'))}</span></div>
        <div class="card-row"><span class="lbl">QQQ vs 50d</span><span class="val">{_check(trend.get('qqq_above_50'))}</span></div>
        <div class="card-row"><span class="lbl">RSI-14</span><span class="val">{_fmt(rsi, '.1f')}</span></div>
    </div>

    <!-- Breadth -->
    <div class="card" style="border-top-color:{breadth_color}">
        <div class="card-header">
            <span class="card-title">Breadth</span>
            <span class="card-score" style="color:{breadth_color}">{breadth_score:.0f}</span>
        </div>
        <div class="card-row"><span class="lbl">Sectors &gt; 50d</span><span class="val">{sectors_above}/11</span></div>
        <div class="card-row"><span class="lbl">Participation</span><span class="val">{"Wide" if sectors_above >= 8 else ("Narrow" if sectors_above < 5 else "Mixed")}</span></div>
        <div style="margin-top:6px;font-size:11px;">
            {''.join(
                f'<div class="card-row"><span class="lbl">{SECTOR_NAMES.get(etf, etf)}</span>'
                f'<span class="val">{"<span style=color:#22c55e>&#9650;</span>" if sector_status.get(etf) else "<span style=color:#ef4444;opacity:0.5>&#9660;</span>"}</span></div>'
                for etf in SECTOR_ETFS
            )}
        </div>
    </div>

    <!-- Momentum -->
    <div class="card" style="border-top-color:{mom_color}">
        <div class="card-header">
            <span class="card-title">Momentum</span>
            <span class="card-score" style="color:{mom_color}">{mom_score:.0f}</span>
        </div>
        <div class="card-row"><span class="lbl">Positive (5d)</span><span class="val">{sectors_pos}/11</span></div>
        <div class="card-row"><span class="lbl">Spread</span><span class="val">{_fmt(spread, '.1f')}%</span></div>
        <div class="card-row"><span class="lbl">Leader</span><span class="val">{SECTOR_NAMES.get(top3[0], 'N/A') if top3 else 'N/A'}</span></div>
        <div class="card-row"><span class="lbl">Laggard</span><span class="val">{SECTOR_NAMES.get(sorted_sectors[-1][0], 'N/A') if sorted_sectors else 'N/A'}</span></div>
        <div class="card-row"><span class="lbl">Rotation</span>{_label_tag(rotation, rotation_color)}</div>
    </div>

    <!-- Macro -->
    <div class="card" style="border-top-color:{macro_color}">
        <div class="card-header">
            <span class="card-title">Macro</span>
            <span class="card-score" style="color:{macro_color}">{macro_score:.0f}</span>
        </div>
        <div class="card-row"><span class="lbl">TLT (Bonds)</span><span class="val">${_fmt(tlt_price, '.2f')}</span></div>
        <div class="card-row"><span class="lbl">Bond 20d</span>{_label_tag(bond_label, bond_label_color)}</div>
        <div class="card-row"><span class="lbl">Dollar 20d</span>{_label_tag(dollar_label, dollar_label_color)}</div>
        <div class="card-row"><span class="lbl">UUP Chg</span><span class="val">{_pct(dollar_slope)}</span></div>
    </div>

</div>

<!-- Bottom Row -->
<div class="bottom">

    <!-- Sector Performance -->
    <div class="panel" style="grid-column: span 2;">
        <div class="panel-title" style="--dot-color:var(--blue)"><span style="color:var(--blue)">&#9679;</span> Sector Performance (5-Day)</div>
        {sector_rows}
    </div>

    <!-- Scoring Weights -->
    <div class="panel">
        <div class="panel-title"><span style="color:var(--cyan)">&#9679;</span> Scoring Weights</div>
        <table class="weights-table">
            <tr><th>Pillar</th><th>Score</th><th>Weight</th><th>Wtd</th></tr>
            {weight_rows}
            <tr>
                <td>TOTAL</td>
                <td style="color:{color}">{composite:.0f}</td>
                <td class="dim">100%</td>
                <td style="color:{color}">{composite:.1f}</td>
            </tr>
        </table>
    </div>

</div>

<!-- Terminal Analysis -->
<div class="terminal">
    <div class="terminal-header">&gt; Terminal Analysis &nbsp;<span style="color:var(--dim);font-size:10px">AI-generated market assessment</span></div>
    <div class="terminal-body">{html.escape(terminal_analysis)}</div>
</div>

{warnings_html}

<!-- Footer -->
<div class="footer">
    Tasty-Coach Market Quality Terminal &nbsp;|&nbsp; Data via tastytrade API &nbsp;|&nbsp; {now_str}
</div>

</div>
</body>
</html>'''


def open_dashboard_html(agent: DashboardAgent) -> str:
    """Render HTML and open in default browser. Returns the file path."""
    html_content = render_html(agent)
    fd, path = tempfile.mkstemp(suffix='.html', prefix='tasty-dashboard-')
    with os.fdopen(fd, 'w') as f:
        f.write(html_content)
    webbrowser.open(f'file://{path}')
    return path
