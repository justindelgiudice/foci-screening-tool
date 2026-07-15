"""
app.py

Flask web UI for the Defense Contractor Foreign-Exposure Dashboard.
Runs the same screening pipeline as main.py (fetch awards + sanctions
data, aggregate into contractor profiles, score) and renders the
results as an HTML page instead of a terminal report.

Usage:
    python3 app.py
    # then open http://127.0.0.1:5000/          (demo mode)
    #        or http://127.0.0.1:5000/?mode=live (real USAspending.gov + OFAC data)
"""

import logging
import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask, render_template_string, request

from sources.usaspending_source import get_awards
from sources.sanctions_source import get_sanctions_list, get_address_countries
from aggregator import build_contractor_profiles
from risk_engine import score_all

app = Flask(__name__)
app.logger.setLevel(logging.INFO)

# Same three tiers risk_engine.py assigns, mapped to a color and short badge label.
_TIER_STYLE = {
    "PASS": {"border": "#1a7f37", "bg": "#eaf7ee", "text": "#1a7f37", "label": "PASS"},
    "REVIEW RECOMMENDED": {"border": "#9a6700", "bg": "#fff8e1", "text": "#9a6700", "label": "REVIEW"},
    "INVESTIGATE FURTHER": {"border": "#b91c1c", "bg": "#fdecec", "text": "#b91c1c", "label": "INVESTIGATE"},
}


@app.template_filter("usd")
def format_usd(value):
    return f"${value:,.0f}"


@app.template_filter("pct")
def format_pct(value):
    return f"{value * 100:.1f}%"


class PipelineStageError(Exception):
    """Raised with the human-readable name of the stage that failed."""

    def __init__(self, stage: str, original: Exception):
        self.stage = stage
        self.original = original
        super().__init__(f"{stage}: {original}")


def run_pipeline(mode: str) -> list:
    """Same pipeline as main.run(), minus the terminal-report printing."""
    try:
        awards = get_awards(mode=mode)
    except Exception as exc:
        raise PipelineStageError("Fetching DoD award data from USAspending.gov", exc) from exc

    try:
        sanctions_entries = get_sanctions_list(mode=mode)
    except Exception as exc:
        raise PipelineStageError("Fetching the OFAC sanctions/entity list", exc) from exc

    try:
        address_countries_by_ent = get_address_countries(mode=mode)
    except Exception as exc:
        raise PipelineStageError("Fetching the OFAC address file (ADD.CSV) for country attribution", exc) from exc

    contractors = build_contractor_profiles(awards)
    scored = score_all(contractors, sanctions_entries, address_countries_by_ent)
    scored.sort(key=lambda sc: sc.risk_score, reverse=True)
    return scored


# Tiny page shown immediately on click, before the (possibly multi-second)
# live fetch runs. Redirects itself to the real slow URL via JS; the
# browser keeps this spinner on screen for the whole duration of that
# request, so "Live" visibly does something even though the request
# itself is a normal synchronous page load underneath.
_LOADING_TEMPLATE = """
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Loading live data&hellip;</title>
<style>
  body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
    background: #f5f6f8; color: #1f2328;
    display: flex; align-items: center; justify-content: center;
    height: 100vh; margin: 0; text-align: center;
  }
  .box { max-width: 420px; }
  .spinner {
    width: 34px; height: 34px; margin: 0 auto 1.1rem;
    border: 4px solid #d0d7de; border-top-color: #1f2328;
    border-radius: 50%; animation: spin 0.8s linear infinite;
  }
  @keyframes spin { to { transform: rotate(360deg); } }
  h2 { font-size: 1.05rem; margin: 0 0 0.4rem; }
  p { font-size: 0.85rem; color: #57606a; margin: 0; }
</style>
</head>
<body>
  <div class="box">
    <div class="spinner"></div>
    <h2>Fetching live data&hellip;</h2>
    <p>Pulling current DoD awards from USAspending.gov, plus OFAC's full
       sanctions list and address file (for country attribution). This
       can take several seconds &mdash; the sanctions list alone is tens
       of thousands of records.</p>
  </div>
  <script>window.location.replace("/run?mode=live");</script>
</body>
</html>
"""

_PAGE_TEMPLATE = """
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Defense Contractor Foreign-Exposure Dashboard</title>
<style>
  * { box-sizing: border-box; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
    background: #f5f6f8;
    color: #1f2328;
    margin: 0;
    padding: 1.75rem 2rem 3rem;
    line-height: 1.45;
  }
  .wrap { max-width: 1180px; margin: 0 auto; }

  header h1 { font-size: 1.35rem; margin: 0 0 0.3rem; }
  header p.lede { color: #444c56; margin: 0 0 0.9rem; font-size: 0.92rem; max-width: 800px; }

  .mode-toggle a {
    display: inline-block;
    padding: 0.35rem 0.9rem;
    margin-right: 0.5rem;
    border-radius: 6px;
    text-decoration: none;
    font-size: 0.85rem;
    border: 1px solid #d0d7de;
    color: #1f2328;
  }
  .mode-toggle a.active { background: #1f2328; color: #fff; border-color: #1f2328; }

  .explainer {
    background: #fff;
    border: 1px solid #d0d7de;
    border-radius: 8px;
    padding: 0.9rem 1.1rem;
    margin: 1rem 0;
    font-size: 0.83rem;
    color: #333a42;
  }
  .explainer h3 { font-size: 0.8rem; text-transform: uppercase; letter-spacing: 0.04em; color: #57606a; margin: 0 0 0.5rem; }
  .tier-legend { display: flex; gap: 1.5rem; flex-wrap: wrap; margin-top: 0.5rem; }
  .tier-legend .item { display: flex; align-items: center; gap: 0.4rem; }
  .tier-dot { width: 10px; height: 10px; border-radius: 50%; display: inline-block; }

  .caveat {
    background: #fff8e1;
    border: 1px solid #f0d98c;
    border-radius: 8px;
    padding: 0.7rem 1rem;
    margin: 1rem 0 1.25rem;
    font-size: 0.82rem;
    color: #5c4a00;
  }

  .banner { padding: 0.75rem 1rem; border-radius: 6px; margin-bottom: 1.25rem; font-size: 0.85rem; }
  .banner.error { background: #fdecec; color: #82181a; }
  .banner.error .stage { font-weight: 700; }
  .banner.error pre { white-space: pre-wrap; margin: 0.4rem 0 0; font-size: 0.78rem; opacity: 0.85; }

  .summary { font-size: 0.85rem; color: #57606a; margin: 0 0 1rem; }

  .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(380px, 1fr)); gap: 1rem; }
  .card { background: #fff; border-radius: 8px; border: 1px solid #d0d7de; border-left-width: 6px; padding: 1rem 1.1rem; }
  .card-header { display: flex; justify-content: space-between; align-items: flex-start; gap: 0.5rem; }
  .card h3 { margin: 0; font-size: 1rem; }
  .badge { font-size: 0.7rem; font-weight: 700; letter-spacing: 0.03em; padding: 0.2rem 0.55rem; border-radius: 999px; white-space: nowrap; }

  .stats { display: flex; flex-wrap: wrap; gap: 0.35rem 1rem; margin: 0.55rem 0 0.5rem; font-size: 0.8rem; color: #57606a; }

  .score-row { display: flex; align-items: center; gap: 0.6rem; margin: 0.55rem 0; }
  .score-num { font-weight: 700; font-size: 0.95rem; min-width: 3.2rem; }
  .score-bar { flex: 1; height: 7px; border-radius: 4px; background: #eee; overflow: hidden; }
  .score-fill { height: 100%; }

  .sanctions-field {
    margin: 0.6rem 0; padding: 0.55rem 0.7rem; border-radius: 6px;
    background: #f6f8fa; border: 1px solid #e4e7eb; font-size: 0.79rem;
  }
  .sanctions-field.concern { background: #fdecec; border-color: #f3c6c6; }
  .sanctions-field .label { text-transform: uppercase; letter-spacing: 0.03em; font-size: 0.68rem; color: #57606a; margin-bottom: 0.2rem; }
  .sanctions-field .country-row { display: flex; align-items: center; gap: 0.5rem; margin-bottom: 0.15rem; }
  .sanctions-field .country-name { font-weight: 700; font-size: 1rem; }
  .sanctions-field .concern-badge {
    font-size: 0.62rem; font-weight: 700; letter-spacing: 0.03em;
    background: #b91c1c; color: #fff; padding: 0.1rem 0.45rem; border-radius: 999px;
  }
  .sanctions-field .entity-name { font-size: 0.83rem; color: #333a42; }
  .sanctions-field .meta { color: #57606a; margin-top: 0.1rem; }

  .headline-reason {
    font-size: 0.8rem; font-style: italic; color: #333a42;
    margin: 0.5rem 0; padding-left: 0.6rem; border-left: 3px solid #d0d7de;
  }

  .findings { margin-top: 0.55rem; border-top: 1px solid #eee; padding-top: 0.5rem; }
  .finding { font-size: 0.8rem; margin-bottom: 0.4rem; }
  .finding .points { font-weight: 700; }
  .finding .desc { color: #57606a; }
  .no-findings { font-size: 0.8rem; color: #57606a; font-style: italic; }

  details.debug { margin-top: 0.7rem; border-top: 1px dashed #d0d7de; padding-top: 0.5rem; }
  details.debug summary { cursor: pointer; font-size: 0.78rem; color: #0969da; font-weight: 600; }
  .debug-section { margin-top: 0.6rem; font-size: 0.76rem; }
  .debug-section h4 { margin: 0 0 0.3rem; font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.03em; color: #57606a; }
  .debug-table { width: 100%; border-collapse: collapse; margin-bottom: 0.6rem; }
  .debug-table th, .debug-table td { text-align: left; padding: 0.25rem 0.4rem; border-bottom: 1px solid #eee; }
  .debug-table th { color: #57606a; font-weight: 600; }
  .debug-math { background: #f6f8fa; border-radius: 4px; padding: 0.4rem 0.6rem; margin-bottom: 0.6rem; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
  .debug-rule { background: #f6f8fa; border-radius: 4px; padding: 0.4rem 0.6rem; margin-bottom: 0.4rem; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 0.73rem; }
  .debug-normalized { display: flex; gap: 1rem; flex-wrap: wrap; margin-bottom: 0.6rem; }
  .debug-normalized .col { flex: 1; min-width: 150px; }
  .debug-normalized .orig { color: #57606a; }
  .debug-normalized .norm { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; background: #f6f8fa; padding: 0.15rem 0.35rem; border-radius: 4px; display: inline-block; margin-top: 0.15rem; }
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>Defense Contractor Foreign-Exposure Dashboard</h1>
    <p class="lede">
      Screens Department of Defense prime contract awards
      (<strong>USAspending.gov</strong>) against the Treasury
      <strong>OFAC sanctions/entity (SDN) list</strong> to flag
      contractors whose name resembles a sanctioned entity, who hold
      awards in sensitive defense-tech categories, or who depend
      heavily on a single award.
    </p>
  </header>

  <div class="mode-toggle">
    <a href="/?mode=demo" class="{{ 'active' if mode == 'demo' else '' }}">Demo</a>
    <a href="/loading?mode=live" class="{{ 'active' if mode == 'live' else '' }}">Live</a>
  </div>

  <div class="explainer">
    <h3>How to read this</h3>
    <strong>Foreign nexus drives the score.</strong> With no sanctions/entity-list match, a
    contractor scores <strong>0</strong> no matter what it makes or how concentrated its awards
    are &mdash; NAICS mix and award concentration are not independent risk signals here. When
    there <em>is</em> a match, the score is built as: match confidence (up to 50 pts) +
    <strong>the matched entity's real country</strong> (up to +30 pts for a country of concern
    &mdash; China, Russia, Iran, North Korea &mdash; +5 for another confirmed foreign country, +0
    if the country can't be determined from real data). Sensitive-NAICS exposure and single-award
    concentration only ever add a few points <em>on top of</em> an existing match &mdash; they
    modify a foreign-nexus finding, they don't create one. The score is a
    <strong>triage signal</strong>, not a verdict.
    <div class="tier-legend">
      <div class="item"><span class="tier-dot" style="background:#1a7f37;"></span><strong>PASS</strong> (&lt;30) &mdash; no match, or a weak one that stays below review.</div>
      <div class="item"><span class="tier-dot" style="background:#9a6700;"></span><strong>REVIEW</strong> (30&ndash;59) &mdash; worth a human look.</div>
      <div class="item"><span class="tier-dot" style="background:#b91c1c;"></span><strong>INVESTIGATE</strong> (&ge;60) &mdash; flagged for closer scrutiny.</div>
    </div>
  </div>

  <div class="caveat">
    <strong>Caveat:</strong> sanctions-list hits are fuzzy name matches, not confirmed identity
    matches, and country data comes only from OFAC's own address file (ADD.CSV) and remarks field
    &mdash; when neither names a country, this tool says so ("country unknown") rather than
    guessing. Short or generic company names can also score high against unrelated entities purely
    on shared boilerplate or generic industry words. <strong>Every match must be manually reviewed
    against the matched entity name, program, and country before being acted on.</strong>
  </div>

  {% if mode == "demo" %}
  <div class="banner" style="background:#ddf4ff; color:#0a3069;">
    Running in DEMO mode &mdash; contractor and sanctions data below is fictional/illustrative,
    bundled for offline testing. Switch to Live to screen real USAspending.gov contract data
    against the real OFAC sanctions list.
  </div>
  {% endif %}

  {% if error %}
  <div class="banner error">
    <div><span class="stage">{{ error.stage }}</span> failed.</div>
    <div>{{ error.message }}</div>
    <pre>{{ error.traceback }}</pre>
  </div>
  {% endif %}

  {% if scored %}
  <p class="summary">{{ scored|length }} contractors screened, {{ flagged_count }} flagged for review or investigation.</p>
  <div class="grid">
    {% for sc in scored %}
    {% set style = tier_style.get(sc.recommendation, tier_style["PASS"]) %}
    <div class="card" style="border-left-color: {{ style.border }};">
      <div class="card-header">
        <h3>{{ sc.contractor.recipient_name }}</h3>
        <span class="badge" style="background: {{ style.bg }}; color: {{ style.text }};">{{ style.label }}</span>
      </div>
      <div class="stats">
        <span>Total value: {{ sc.contractor.total_award_value | usd }}</span>
        <span>Awards: {{ sc.contractor.award_count }}</span>
        <span>Concentration: {{ sc.contractor.concentration_ratio | pct }}</span>
      </div>
      <div class="score-row">
        <span class="score-num">{{ sc.risk_score }}/100</span>
        <div class="score-bar">
          <div class="score-fill" style="width: {{ sc.risk_score }}%; background: {{ style.border }};"></div>
        </div>
      </div>

      {% if sc.sanctions_match %}
      <div class="sanctions-field {{ 'concern' if sc.sanctions_match.country.is_country_of_concern else '' }}">
        <div class="label">Matched entity &middot; country (headline reason for this score)</div>
        <div class="country-row">
          <span class="country-name">{{ sc.sanctions_match.country.display }}</span>
          {% if sc.sanctions_match.country.is_country_of_concern %}
          <span class="concern-badge">COUNTRY OF CONCERN</span>
          {% endif %}
        </div>
        <div class="entity-name">{{ sc.sanctions_match.matched_entity_name }}</div>
        <div class="meta">
          List/program: {{ sc.sanctions_match.matched_entity_program }} &middot;
          Similarity: {{ sc.sanctions_match.similarity_score }}% &middot;
          Tier: {{ sc.sanctions_match.confidence }}
        </div>
      </div>
      {% endif %}

      {% if sc.headline_reason %}
      <div class="headline-reason">{{ sc.headline_reason }}</div>
      {% endif %}

      {% if sc.findings %}
      <div class="findings">
        {% for f in sc.findings %}
        <div class="finding">
          <span class="points">+{{ f.points }}</span> {{ f.category }}<br>
          <span class="desc">{{ f.description }}</span>
        </div>
        {% endfor %}
      </div>
      {% else %}
      <div class="findings"><span class="no-findings">No findings.</span></div>
      {% endif %}

      <details class="debug">
        <summary>Show underlying data &amp; scoring math</summary>

        <div class="debug-section">
          <h4>Source award records ({{ sc.contractor.awards|length }})</h4>
          <table class="debug-table">
            <tr><th>Award ID</th><th>Amount</th><th>NAICS</th><th>Sub-Agency</th></tr>
            {% for a in sc.contractor.awards %}
            <tr>
              <td>{{ a.award_id }}</td>
              <td>{{ a.award_amount | usd }}</td>
              <td>{{ a.naics_code or '&mdash;' }}</td>
              <td>{{ a.awarding_sub_agency or '&mdash;' }}</td>
            </tr>
            {% endfor %}
            <tr><td><strong>Total</strong></td><td><strong>{{ sc.contractor.total_award_value | usd }}</strong></td><td colspan="2"></td></tr>
          </table>
        </div>

        <div class="debug-section">
          <h4>Concentration arithmetic</h4>
          <div class="debug-math">
            largest_award ({{ sc.contractor.largest_award_value | usd }}) / total_value ({{ sc.contractor.total_award_value | usd }})
            = {{ sc.contractor.concentration_ratio | pct }}
          </div>
        </div>

        {% if sc.sanctions_match %}
        <div class="debug-section">
          <h4>Sanctions match: IDF-weighted token breakdown (what the score was computed on)</h4>
          <div class="debug-normalized">
            <div class="col">
              <div class="orig">Contractor name tokens: {{ sc.sanctions_match.normalized_contractor_name }}</div>
            </div>
            <div class="col">
              <div class="orig">Matched entity tokens: {{ sc.sanctions_match.normalized_entity_name }}</div>
            </div>
          </div>
          <table class="debug-table">
            <tr><th>Contractor token</th><th>IDF weight</th><th>Best match in entity name</th><th>Char ratio</th><th>Weighted contribution</th></tr>
            {% for c in sc.sanctions_match.scoring_detail %}
            <tr>
              <td>{{ c.token }}</td>
              <td>{{ c.idf }}</td>
              <td>{{ c.matched_to }}</td>
              <td>{{ c.char_ratio }}%</td>
              <td>{{ c.contribution }}</td>
            </tr>
            {% endfor %}
          </table>
          <div class="debug-math">
            Higher IDF = rarer across the ~19,000-entry SDN list = more distinctive = weighted more heavily.
            A token near every SDN name (SERVICES, LLC, ENTERPRISE, ...) has IDF near the floor and barely
            moves the score even on an exact character match.<br>
            Symmetric IDF-weighted similarity(contractor, matched entity) = {{ sc.sanctions_match.similarity_score }}%<br>
            {% if sc.sanctions_match.top_contributing_tokens %}
            Score driven mainly by: {{ sc.sanctions_match.top_contributing_tokens }}
            {% else %}
            No single token contributed meaningfully -- this match is weak/diffuse.
            {% endif %}
          </div>
        </div>

        <div class="debug-section">
          <h4>Country attribution: where it came from</h4>
          <div class="debug-math">
            countries = [{{ sc.sanctions_match.country.countries | join(', ') }}]<br>
            source = {{ sc.sanctions_match.country.source or '(none -- no ADD.CSV address record or remarks phrasing found for this entity)' }}<br>
            countries of concern present = {{ sc.sanctions_match.country.is_country_of_concern }}
          </div>
        </div>
        {% endif %}

        <div class="debug-section">
          <h4>Scoring rules that fired</h4>
          {% if sc.findings %}
            {% for f in sc.findings %}
            <div class="debug-rule">{{ f.category }}: {{ f.rule }}</div>
            {% endfor %}
            <div class="debug-math">sum of points above = {{ sc.findings | sum(attribute="points") }}, clamped to [0, 100] = {{ sc.risk_score }}</div>
          {% else %}
            <div class="debug-rule">No rules fired -- risk_score = 0</div>
          {% endif %}
        </div>
      </details>
    </div>
    {% endfor %}
  </div>
  {% elif not error %}
  <p class="summary">No contractors to display.</p>
  {% endif %}
</div>
</body>
</html>
"""


@app.route("/loading")
def loading():
    return render_template_string(_LOADING_TEMPLATE)


@app.route("/")
@app.route("/run")
def dashboard():
    mode = request.args.get("mode", "demo")
    if mode not in ("demo", "live"):
        mode = "demo"

    scored = []
    error = None
    try:
        scored = run_pipeline(mode)
    except PipelineStageError as exc:
        tb = traceback.format_exc()
        app.logger.error("Pipeline stage failed: %s\n%s", exc, tb)
        error = {"stage": exc.stage, "message": str(exc.original), "traceback": tb}
    except Exception as exc:
        tb = traceback.format_exc()
        app.logger.error("Unexpected pipeline failure: %s\n%s", exc, tb)
        error = {"stage": "Screening pipeline", "message": str(exc), "traceback": tb}

    flagged_count = sum(1 for sc in scored if sc.recommendation != "PASS")
    return render_template_string(
        _PAGE_TEMPLATE,
        scored=scored,
        mode=mode,
        error=error,
        tier_style=_TIER_STYLE,
        flagged_count=flagged_count,
    )


if __name__ == "__main__":
    app.run(debug=True)
