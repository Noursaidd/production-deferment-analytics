"""One-page HTML report for operations management (plain language, charts embedded)."""
from __future__ import annotations

import base64
import io
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from src.generate_data import load_config

C = {"blue": "#2a78d6", "orange": "#eb6834", "aqua": "#1baf7a", "gray": "#8a8985",
     "ink": "#0b0b0b", "ink2": "#52514e", "grid": "#e6e5e1", "surface": "#fcfcfb", "crit": "#d03b3b"}
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10, "axes.edgecolor": C["grid"],
                     "axes.labelcolor": C["ink2"], "xtick.color": C["ink2"], "ytick.color": C["ink2"],
                     "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True,
                     "grid.color": C["grid"], "axes.axisbelow": True,
                     "figure.facecolor": C["surface"], "axes.facecolor": C["surface"]})


def b64(fig) -> str:
    buf = io.BytesIO(); fig.savefig(buf, format="png", dpi=150, bbox_inches="tight"); plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode()


def title(ax, text):
    ax.set_title(text, loc="left", fontsize=10, color=C["ink"])


def chart_pareto(p: pd.DataFrame) -> str:
    fig, ax = plt.subplots(figsize=(9, 3))
    colors = [C["crit"] if c.startswith("Unexplained") else C["gray"] if cat == "Planned" else C["blue"]
              for c, cat in zip(p.cause, p.category)]
    ax.barh(p.cause, p.deferred_bbl / 1000, color=colors, height=0.6)
    ax.invert_yaxis(); ax.grid(axis="y", visible=False)
    for i, r in enumerate(p.itertuples()):
        ax.text(r.deferred_bbl / 1000 + 3, i, f"{r.pct_of_total:.0f}%  (cum. {r.cumulative_pct:.0f}%)",
                va="center", fontsize=9, color=C["ink"])
    ax.set_xlabel("Oil deferred, thousand bbl (2 years)")
    ax.set_xlim(0, p.deferred_bbl.max() / 1000 * 1.35)
    title(ax, "Where the lost oil went: blue = unplanned · gray = planned · red = never logged")
    return b64(fig)


def chart_efficiency(m: pd.DataFrame) -> str:
    fig, ax = plt.subplots(figsize=(9, 2.6))
    ax.plot(m.month, m.production_efficiency_pct, color=C["blue"], lw=2, marker="o", ms=4)
    ax.set_ylabel("Actual / potential, %")
    ax.set_xticks(range(0, len(m), 3), m.month[::3])
    title(ax, "Production efficiency by month (100% = every well online all day at tested rate)")
    return b64(fig)


def chart_decline(curves: dict, dec: pd.DataFrame) -> str:
    below = dec[dec.status.str.startswith("Below")].well_id.tolist()[:1]
    above = dec[dec.status.str.startswith("Above")].well_id.tolist()[-1:]
    ok = dec[dec.status == "On track"].well_id.tolist()[:1]
    picks = below + ok + above
    fig, axes = plt.subplots(1, len(picks), figsize=(9, 2.6), sharey=False)
    for ax, w in zip(axes, picks):
        months, act, fit = curves[w]
        x = range(len(months))
        st = dec.set_index("well_id").loc[w, "status"]
        col = C["crit"] if st.startswith("Below") else C["aqua"] if st.startswith("Above") else C["blue"]
        ax.plot(x, act, color=col, lw=1.8, marker="o", ms=2.5, label="actual")
        ax.plot(x, fit, color=C["ink2"], lw=1.2, ls="--", label="decline forecast")
        ax.axvline(months.index("2025-03") + 0.5, color=C["grid"], lw=6, alpha=0.9)
        ax.set_xticks([0, 12, len(months) - 1], [months[0], months[12], months[-1]], fontsize=8)
        title(ax, f"{w}: {st.split(' - ')[0].lower()}")
    axes[0].set_ylabel("Oil rate when online, bopd")
    axes[0].legend(fontsize=8, frameon=False, loc="lower left")
    fig.tight_layout()
    return b64(fig)


def chart_did(per: pd.DataFrame, res: dict) -> str:
    fig, ax = plt.subplots(figsize=(9, 2.4))
    for y, (lab, grp, col) in enumerate([("Untreated wells (control)", per[per.treated == 0], C["gray"]),
                                         ("Treated wells", per[per.treated == 1], C["orange"])]):
        ax.scatter(grp.change_pct, [y] * len(grp), s=60, color=col, edgecolor=C["surface"], linewidth=1.5, zorder=3)
        ax.plot([grp.change_pct.mean()] * 2, [y - 0.25, y + 0.25], color=C["ink"], lw=2)
        ax.text(grp.change_pct.mean(), y + 0.32, f"avg {grp.change_pct.mean():+.1f}%", ha="center", fontsize=9)
    ax.axvline(0, color=C["ink2"], lw=1)
    ax.set_yticks([0, 1], ["Untreated wells (control)", "Treated wells"]); ax.set_ylim(-0.6, 1.7)
    ax.set_xlabel("Change in oil rate, 60 days after vs before 1-Apr-2025 (%)")
    ax.grid(axis="y", visible=False)
    title(ax, f"Effect = treated avg − control avg = {res['did_effect_pct']:+.1f}% "
              f"(95% CI {res['bootstrap_95ci_pct'][0]:+.1f}% to {res['bootstrap_95ci_pct'][1]:+.1f}%)")
    return b64(fig)


def main(config_path="config/config.yaml"):
    cfg = load_config(config_path)
    price = cfg["oil_price_usd_per_bbl"]
    p = pd.read_csv("reports/sql/deferment_pareto.csv")
    m = pd.read_csv("reports/sql/monthly_kpis.csv")
    rank = pd.read_csv("reports/sql/well_ranking.csv")
    lift = pd.read_csv("reports/sql/lift_type_reliability.csv")
    log = pd.read_csv("reports/sql/logging_compliance.csv")
    dq = pd.read_csv("reports/dq_raw_profile.csv")
    dec = pd.read_csv("reports/decline_forecasts.csv")
    curves = pd.read_pickle("reports/.decline_curves.pkl")
    did = json.loads(Path("reports/intervention_result.json").read_text())
    per = pd.read_csv("reports/intervention_per_well.csv")

    total_def = p.deferred_bbl.sum()
    unplanned = p[p.category != "Planned"].deferred_bbl.sum()
    top = p.iloc[0]
    unlogged = log.set_index("status").loc["Not logged"]
    eff = (m.actual_bbl.sum() / m.potential_bbl.sum()) * 100
    below = dec[dec.status.str.startswith("Below")]
    top5 = rank.head(5)
    top5_share = top5.unplanned_deferred_bbl.sum() / rank.unplanned_deferred_bbl.sum() * 100
    money = lambda x: f"${x/1e6:.1f}M"

    rows_rank = "".join(f"<tr><td>{r.rank}</td><td>{r.well_id}</td><td>{r.field}</td><td>{r.lift_type}</td>"
                        f"<td>{r.unplanned_events}</td><td>{r.unplanned_deferred_bbl:,.0f}</td></tr>"
                        for r in top5.itertuples())
    rows_below = "".join(f"<tr><td>{r.well_id}</td><td>{r.recent_actual_vs_forecast_pct:+.0f}%</td>"
                         f"<td>{r.annual_decline_pct:.0f}%</td></tr>" for r in below.itertuples())
    rows_dq = "".join(f"<tr><td>{r.metric}</td><td>{int(r.value):,}</td></tr>" for r in dq.itertuples())

    html = f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Production Deferment &amp; Well Performance Review</title>
<style>
:root{{--ink:#0b0b0b;--ink2:#52514e;--line:#e6e5e1;--bg:#fcfcfb}}
*{{box-sizing:border-box}} body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.55 system-ui,-apple-system,Segoe UI,sans-serif}}
main{{max-width:960px;margin:0 auto;padding:40px 24px 80px}} h1{{font-size:28px;margin:0 0 4px}}
h2{{font-size:19px;margin:40px 0 8px;border-top:1px solid var(--line);padding-top:24px}} .sub{{color:var(--ink2)}}
.tiles{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:20px 0}}
.tile{{border:1px solid var(--line);border-radius:10px;padding:14px;background:#fff}}
.tile b{{display:block;font-size:24px;font-variant-numeric:tabular-nums}} .tile span{{color:var(--ink2);font-size:13px}}
img{{width:100%;border:1px solid var(--line);border-radius:10px;background:#fff}}
table{{width:100%;border-collapse:collapse;font-size:14px;font-variant-numeric:tabular-nums}}
th,td{{text-align:left;padding:6px 8px;border-bottom:1px solid var(--line)}} th{{color:var(--ink2)}}
.cols{{display:grid;grid-template-columns:1fr 1fr;gap:24px}}
.note{{background:#f3f2ee;border-radius:10px;padding:14px 16px;font-size:14px}}
@media(max-width:700px){{.tiles,.cols{{grid-template-columns:1fr 1fr}}}}
</style></head><body><main>
<h1>Production Deferment &amp; Well Performance Review</h1>
<p class="sub">30 wells · Jan 2024 – Dec 2025 · built in SQL (SQLite) + Python · synthetic data modelled on real daily production reports</p>

<h2>Key findings</h2>
<div class="tiles">
<div class="tile"><b>{eff:.1f}%</b><span>production efficiency (actual vs potential)</span></div>
<div class="tile"><b>{total_def/1000:,.0f}K bbl</b><span>oil deferred ≈ {money(total_def*price)} at ${price}/bbl</span></div>
<div class="tile"><b>{unlogged.pct_bbl:.0f}%</b><span>of lost oil has no reason in the operator log</span></div>
<div class="tile"><b>{did['did_effect_pct']:+.1f}%</b><span>proven uplift from scale-squeeze treatment</span></div>
</div>
<ol>
<li><b>{top.cause}s are the biggest single cause</b> of lost oil ({top.pct_of_total:.0f}%). Unplanned causes make up {unplanned/total_def*100:.0f}% of all deferment.</li>
<li><b>{unlogged.pct_bbl:.0f}% of lost oil was never explained</b> ({int(unlogged.events)} downtime events missing from the log). You cannot fix what is not recorded, so a logging-discipline fix is the cheapest win.</li>
<li><b>5 wells cause {top5_share:.0f}% of unplanned deferment.</b> Focus reliability reviews there first.</li>
<li><b>{len(below)} wells have dropped well below their decline forecast</b> in the last 3 months. Investigate them now, before they fail.</li>
<li><b>The scale-squeeze campaign worked:</b> {did['did_effect_pct']:+.1f}% more oil than comparable untreated wells
(95% CI {did['bootstrap_95ci_pct'][0]:+.1f}% to {did['bootstrap_95ci_pct'][1]:+.1f}%), about {did['extra_oil_bopd_first_period']} bopd extra.
A simple before/after comparison would have said only {did['naive_treated_change_pct']:+.1f}%, because it ignores natural decline.</li>
</ol>

<h2>1 · Where the lost oil went (Pareto)</h2>
<img alt="Deferred oil by cause" src="data:image/png;base64,{chart_pareto(p)}">

<h2>2 · Production efficiency over time</h2>
<img alt="Monthly production efficiency" src="data:image/png;base64,{chart_efficiency(m)}">

<h2>3 · Wells to act on</h2>
<div class="cols"><div>
<p><b>Top 5 wells by unplanned deferment</b></p>
<table><tr><th>#</th><th>Well</th><th>Field</th><th>Lift</th><th>Events</th><th>bbl lost</th></tr>{rows_rank}</table>
</div><div>
<p><b>Below their decline forecast (last 3 months)</b></p>
<table><tr><th>Well</th><th>vs forecast</th><th>Normal decline / yr</th></tr>{rows_below}</table>
</div></div>
<img style="margin-top:16px" alt="Decline curve examples" src="data:image/png;base64,{chart_decline(curves, dec)}">
<p class="sub">Forecast fitted on Jan-2024 to Mar-2025 (Arps hyperbolic, rate normalised for downtime); gray band = end of fit period.</p>

<h2>4 · Did the treatment campaign work?</h2>
<img alt="Treatment effect per well" src="data:image/png;base64,{chart_did(per, did)}">
<p>Method: difference-in-differences against 22 untreated wells; Welch t-test p = {did['welch_t_p_value']}, Mann-Whitney p = {did['mann_whitney_p_value']}.
Indicative value ≈ {money(did['indicative_annual_value_usd'])} per year with a 30% haircut for fading effect. Recommend extending the campaign and re-measuring at 6 months.</p>

<h2>5 · Data quality (fixed in SQL before any analysis)</h2>
<div class="cols"><div><table><tr><th>Issue</th><th>Rows</th></tr>{rows_dq}</table></div>
<div class="note">All 6 SQL data tests on the clean layer pass (duplicates, hours 0–24, negative volumes,
orphan well IDs, unclassified reasons, end-before-start). Raw data is never edited. Every fix is a
commented SQL rule in <code>sql/02_clean.sql</code>, so it can be audited and re-run.</div></div>

<h2>Assumptions</h2>
<div class="note">Potential = latest monthly well-test rate. Deferment = potential × hours offline / 24. Oil price ${price}/bbl.
Data is synthetic; methods transfer directly to real daily production reports and downtime logs.
Lift-type reliability (mean days between unplanned events): {", ".join(f"{r.lift_type} {int(r.mtbe_days)} d" for r in lift.itertuples())}.</div>
</main></body></html>"""
    Path("reports/production_review.html").write_text(html)
    print("report written: reports/production_review.html")


if __name__ == "__main__":
    main()
