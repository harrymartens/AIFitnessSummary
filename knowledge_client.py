"""
knowledge_client.py

Provides evidence-based fitness knowledge to inject into Claude prompts.
Stage 4A: Curated knowledge base selection and summarisation.
Stage 4B: PubMed + examine.com live search and SQLite caching.
"""

import hashlib
import sys
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from db_client import get_db

KNOWLEDGE_BASE_DIR = Path(__file__).parent / "knowledge_base"

TOPIC_FILES = {
    "strength_training": "strength_training.md",
    "sleep": "sleep_science.md",
    "hrv": "hrv_interpretation.md",
    "cardiovascular": "cardiovascular.md",
    "recovery": "recovery.md",
}

# Human-readable labels for each topic key (used in formatted output headers)
TOPIC_LABELS = {
    "strength_training": "STRENGTH TRAINING",
    "sleep": "SLEEP SCIENCE",
    "hrv": "HRV INTERPRETATION",
    "cardiovascular": "CARDIOVASCULAR FITNESS",
    "recovery": "RECOVERY",
}


def select_relevant_topics(metrics: dict) -> list[str]:
    """
    Given the current metrics dict, return up to 2 topic keys most relevant
    to surface in this review. Heuristic rules:

    - HRV below 50 or declining → "hrv", "recovery"
    - Sleep < 6.5 hrs avg OR deep sleep < 15% → "sleep"
    - workouts_count >= 3 → "strength_training"
    - VO2max present OR runs exist → "cardiovascular"
    - stress > 60 OR body_battery_avg < 40 → "recovery"
    - Default fallback: ["strength_training", "sleep"]

    Returns at most 2 topics.
    """
    selected: list[str] = []

    # Extract sub-dicts; metrics may be a combined dict (garmin + hevy keys)
    # or a garmin_data dict with nested structure.
    hrv_data = metrics.get("hrv", {})
    sleep_data = metrics.get("sleep", {})
    stress_data = metrics.get("stress", {})
    body_battery_data = metrics.get("body_battery", {})
    vo2_data = metrics.get("vo2max", {})
    runs_data = metrics.get("runs", {})

    # HRV signals — check period average and whether daily values show a
    # declining trend (last reading below 7-day average).
    hrv_avg = hrv_data.get("period_avg_ms")
    hrv_low = hrv_avg is not None and hrv_avg < 50

    hrv_declining = False
    daily_hrv = hrv_data.get("daily", [])
    if len(daily_hrv) >= 3:
        recent_values = [
            d.get("last_night_avg_ms")
            for d in daily_hrv[-3:]
            if d.get("last_night_avg_ms") is not None
        ]
        older_values = [
            d.get("last_night_avg_ms")
            for d in daily_hrv[:-3]
            if d.get("last_night_avg_ms") is not None
        ]
        if recent_values and older_values:
            hrv_declining = (
                sum(recent_values) / len(recent_values)
                < sum(older_values) / len(older_values)
            )

    if hrv_low or hrv_declining:
        _add_topics(selected, ["hrv", "recovery"])

    # Sleep signals — average total hours and deep-sleep percentage.
    if len(selected) < 2:
        avg_total_h = sleep_data.get("avg_total_h")
        avg_deep_h = sleep_data.get("avg_deep_h")

        sleep_short = avg_total_h is not None and avg_total_h < 6.5
        deep_pct_low = (
            avg_total_h is not None
            and avg_deep_h is not None
            and avg_total_h > 0
            and (avg_deep_h / avg_total_h) < 0.15
        )

        if sleep_short or deep_pct_low:
            _add_topics(selected, ["sleep"])

    # Stress / body battery signals — check for high chronic stress or low
    # body battery reserve.
    if len(selected) < 2:
        avg_stress = stress_data.get("avg_stress")
        body_battery_avg = body_battery_data.get("avg_max")  # daily max = charged level

        high_stress = avg_stress is not None and avg_stress > 60
        low_battery = body_battery_avg is not None and body_battery_avg < 40

        if high_stress or low_battery:
            _add_topics(selected, ["recovery"])

    # Cardiovascular signals — VO2 max recorded or running activity present.
    if len(selected) < 2:
        has_vo2 = vo2_data.get("vo2_max") is not None
        has_runs = runs_data.get("run_count", 0) > 0

        if has_vo2 or has_runs:
            _add_topics(selected, ["cardiovascular"])

    # Strength training signal — meaningful number of workout sessions.
    if len(selected) < 2:
        workout_count = metrics.get("workout_count", 0)
        # Hevy summary data is passed at the top level in some calling contexts
        if workout_count >= 3:
            _add_topics(selected, ["strength_training"])

    # Default fallback: if nothing triggered, surface the two most broadly
    # applicable topics.
    if not selected:
        selected = ["strength_training", "sleep"]

    return selected[:2]


def _add_topics(selected: list[str], candidates: list[str]) -> None:
    """Add candidates to selected list without duplicates, up to 2 total."""
    for topic in candidates:
        if topic not in selected and len(selected) < 2:
            selected.append(topic)


def load_topic(topic_key: str) -> str:
    """Load and return the full text of a knowledge base file."""
    filename = TOPIC_FILES.get(topic_key)
    if filename is None:
        raise KeyError(
            f"Unknown topic key {topic_key!r}. Valid keys: {list(TOPIC_FILES)}"
        )

    path = KNOWLEDGE_BASE_DIR / filename
    if not path.exists():
        raise FileNotFoundError(
            f"Knowledge base file not found: {path}. "
            "Ensure knowledge_base/ directory is present."
        )

    return path.read_text(encoding="utf-8")


def summarise_to_budget(text: str, max_chars: int = 1500) -> str:
    """
    Truncate text to max_chars at a paragraph boundary.
    Adds '...[truncated for brevity]' if truncated.
    """
    if len(text) <= max_chars:
        return text

    # Find the last paragraph break (double newline) within the budget.
    truncation_point = text.rfind("\n\n", 0, max_chars)

    if truncation_point == -1:
        # No paragraph boundary found; fall back to last newline.
        truncation_point = text.rfind("\n", 0, max_chars)

    if truncation_point == -1:
        # No newline at all; hard truncate at max_chars.
        truncation_point = max_chars

    return text[:truncation_point].rstrip() + "\n\n...[truncated for brevity]"


def get_knowledge_context(metrics: dict) -> str:
    """
    Select relevant topics, load and summarise them, return a formatted
    string block ready for injection into the Claude prompt.

    Returns a string like:

    [KNOWLEDGE BASE — STRENGTH TRAINING]
    <content>

    [KNOWLEDGE BASE — HRV INTERPRETATION]
    <content>

    Returns empty string if knowledge_base/ dir doesn't exist.
    """
    if not KNOWLEDGE_BASE_DIR.exists():
        return ""

    topics = select_relevant_topics(metrics)

    sections: list[str] = []
    for topic_key in topics:
        try:
            raw_text = load_topic(topic_key)
        except FileNotFoundError:
            # Gracefully skip missing files rather than crashing the review.
            continue

        summarised = summarise_to_budget(raw_text, max_chars=1500)
        label = TOPIC_LABELS.get(topic_key, topic_key.upper().replace("_", " "))
        sections.append(f"[KNOWLEDGE BASE — {label}]\n{summarised}")

    return "\n\n".join(sections)


# ---------------------------------------------------------------------------
# Stage 4B — Live research: PubMed + examine.com with SQLite caching
# ---------------------------------------------------------------------------

_USER_AGENT = "AIFitnessSummary/1.0 (personal fitness tracker)"

_ESEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
_EFETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"


def search_pubmed(query: str, max_results: int = 3) -> list[dict]:
    """Search PubMed for relevant abstracts.

    Returns list of dicts with keys:
        title, abstract, authors, year, pmid

    Returns an empty list on any error (network, parse, etc.).
    """
    headers = {"User-Agent": _USER_AGENT}

    # --- Step 1: esearch to obtain PMIDs ---
    try:
        search_resp = requests.post(
            _ESEARCH_URL,
            params={
                "db": "pubmed",
                "term": query,
                "retmax": max_results,
                "retmode": "json",
                "sort": "relevance",
            },
            headers=headers,
            timeout=10,
        )
        search_resp.raise_for_status()
        search_data = search_resp.json()
        pmids = search_data.get("esearchresult", {}).get("idlist", [])
    except Exception as exc:
        print(f"[knowledge_client] PubMed esearch failed: {exc}", file=sys.stderr)
        return []

    if not pmids:
        return []

    # Polite delay between requests to NCBI
    time.sleep(1)

    # --- Step 2: efetch to retrieve XML abstracts ---
    try:
        fetch_resp = requests.post(
            _EFETCH_URL,
            params={
                "db": "pubmed",
                "id": ",".join(pmids),
                "rettype": "abstract",
                "retmode": "xml",
            },
            headers=headers,
            timeout=10,
        )
        fetch_resp.raise_for_status()
        xml_content = fetch_resp.text
    except Exception as exc:
        print(f"[knowledge_client] PubMed efetch failed: {exc}", file=sys.stderr)
        return []

    # --- Step 3: Parse XML ---
    try:
        soup = BeautifulSoup(xml_content, "lxml-xml")
        articles = soup.find_all("PubmedArticle")
        results: list[dict] = []

        for article in articles:
            # Title
            title_tag = article.find("ArticleTitle")
            title = title_tag.get_text(separator=" ", strip=True) if title_tag else ""

            # Abstract — join multiple AbstractText blocks
            abstract_tags = article.find_all("AbstractText")
            abstract = " ".join(
                tag.get_text(separator=" ", strip=True) for tag in abstract_tags
            ).strip()

            # Authors — first 3 last names, "et al." if more
            last_name_tags = article.find_all("LastName")
            last_names = [t.get_text(strip=True) for t in last_name_tags]
            if len(last_names) > 3:
                authors = ", ".join(last_names[:3]) + " et al."
            else:
                authors = ", ".join(last_names)

            # Year
            year_tag = article.find("PubDate")
            year = ""
            if year_tag:
                y = year_tag.find("Year")
                year = y.get_text(strip=True) if y else ""

            # PMID
            pmid_tag = article.find("PMID")
            pmid = pmid_tag.get_text(strip=True) if pmid_tag else ""

            results.append(
                {
                    "title": title,
                    "abstract": abstract,
                    "authors": authors,
                    "year": year,
                    "pmid": pmid,
                }
            )

        return results
    except Exception as exc:
        print(f"[knowledge_client] PubMed XML parse failed: {exc}", file=sys.stderr)
        return []


def fetch_examine(topic: str) -> dict | None:
    """Fetch the summary for a topic from examine.com.

    Tries https://examine.com/topics/{slug}/ first.
    Returns {"topic": topic, "summary": text, "url": url} or None on any error.
    """
    slug = topic.lower().replace(" ", "-")
    url = f"https://examine.com/topics/{slug}/"
    headers = {"User-Agent": _USER_AGENT}

    try:
        resp = requests.get(url, headers=headers, timeout=8)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")

        # Try common summary containers in priority order
        summary_text = ""

        for selector in [
            {"class": "summary-box"},
            {"class": "examine-summary"},
        ]:
            tag = soup.find("div", selector)
            if tag:
                summary_text = tag.get_text(separator=" ", strip=True)
                break

        if not summary_text:
            # First <p> inside <article> or <main>
            for container_name in ("article", "main"):
                container = soup.find(container_name)
                if container:
                    first_p = container.find("p")
                    if first_p:
                        summary_text = first_p.get_text(separator=" ", strip=True)
                        break

        if not summary_text:
            # Fallback: meta description
            meta = soup.find("meta", attrs={"name": "description"})
            if meta and meta.get("content"):
                summary_text = meta["content"].strip()

        if not summary_text:
            return None

        return {
            "topic": topic,
            "summary": summary_text[:500],
            "url": url,
        }
    except Exception:
        # Silently return None — examine.com may block or change structure
        return None


def get_research_context(metrics: dict, goal: dict | None = None) -> str:
    """Determine relevant research queries, check cache, fetch if stale.

    Returns a formatted [RESEARCH CONTEXT] block string, or empty string
    if all fetches fail or no queries can be determined.
    """
    # ------------------------------------------------------------------
    # 1. Determine research queries (max 2)
    # ------------------------------------------------------------------
    queries: list[str] = []

    hrv_data = metrics.get("hrv", {})
    sleep_data = metrics.get("sleep", {})
    activity_data = metrics.get("stats", {})  # Garmin stats sub-dict
    workout_count = metrics.get("workout_count", 0)

    hrv_avg = hrv_data.get("period_avg_ms")
    sleep_avg = sleep_data.get("avg_total_h")
    avg_steps = activity_data.get("avg_daily_steps")

    workouts_per_week = metrics.get("workouts_per_week", 0)

    # HRV signal
    if hrv_avg is not None and hrv_avg < 45:
        _append_unique(queries, "HRV heart rate variability training recovery athletes")

    # Sleep signal
    if len(queries) < 2 and sleep_avg is not None and sleep_avg < 6.5:
        _append_unique(queries, "sleep deprivation athletic performance strength")

    # Low activity signal
    if len(queries) < 2 and avg_steps is not None and avg_steps < 5000:
        _append_unique(queries, "low physical activity health outcomes sedentary")

    # High training frequency signal
    if len(queries) < 2 and workouts_per_week >= 5:
        _append_unique(queries, "training frequency recovery overtraining prevention")

    # Goal-based signals
    primary_obj = (goal or {}).get("primary_objective", "")
    if primary_obj:
        obj_lower = primary_obj.lower()
        if len(queries) < 2 and "weight" in obj_lower:
            _append_unique(queries, "resistance training fat loss body composition")
        if len(queries) < 2 and ("cardio" in obj_lower or "endurance" in obj_lower):
            _append_unique(queries, "VO2 max training adaptations aerobic")

    # Default fallback
    if not queries:
        queries.append("exercise recovery sleep performance optimization")

    # ------------------------------------------------------------------
    # 2. Fetch / retrieve from cache for each query
    # ------------------------------------------------------------------
    try:
        db = get_db()
    except Exception as exc:
        print(f"[knowledge_client] DB unavailable: {exc}", file=sys.stderr)
        db = None

    pubmed_sections: list[str] = []

    for query in queries[:2]:
        cache_key = "pubmed:" + hashlib.md5(query.encode()).hexdigest()
        result_text: str | None = None

        # Cache check
        if db is not None:
            try:
                cached = db.get_cached_knowledge(cache_key)
                if cached:
                    result_text = cached["result_text"]
            except Exception as exc:
                print(f"[knowledge_client] Cache read failed: {exc}", file=sys.stderr)

        # Live fetch on cache miss
        if result_text is None:
            papers = search_pubmed(query, max_results=2)
            if papers:
                lines: list[str] = []
                for p in papers:
                    abstract_snippet = p["abstract"][:200]
                    if len(p["abstract"]) > 200:
                        abstract_snippet += "..."
                    byline = f"{p['authors']}, {p['year']}".strip(", ")
                    lines.append(f"• {p['title']} ({byline}): {abstract_snippet}")
                result_text = "\n".join(lines)

                if db is not None:
                    try:
                        db.save_knowledge_cache(cache_key, "pubmed", query, result_text)
                    except Exception as exc:
                        print(
                            f"[knowledge_client] Cache write failed: {exc}",
                            file=sys.stderr,
                        )

        if result_text:
            pubmed_sections.append(
                f'PubMed — "{query}":\n{result_text}'
            )

    # ------------------------------------------------------------------
    # 3. Examine.com fetch for goal-relevant supplement topic
    # ------------------------------------------------------------------
    examine_section = ""
    if goal is not None:
        obj_lower = (goal.get("primary_objective") or "").lower()
        examine_topic: str | None = None
        if "weight" in obj_lower:
            examine_topic = "caloric-restriction"
        elif "strength" in obj_lower:
            examine_topic = "creatine"
        elif "cardio" in obj_lower or "endurance" in obj_lower:
            examine_topic = "caffeine"

        if examine_topic:
            cache_key = "examine:" + hashlib.md5(examine_topic.encode()).hexdigest()
            result_text = None

            if db is not None:
                try:
                    cached = db.get_cached_knowledge(cache_key)
                    if cached:
                        result_text = cached["result_text"]
                except Exception as exc:
                    print(
                        f"[knowledge_client] Examine cache read failed: {exc}",
                        file=sys.stderr,
                    )

            if result_text is None:
                examine_data = fetch_examine(examine_topic)
                if examine_data:
                    result_text = examine_data["summary"]
                    if db is not None:
                        try:
                            db.save_knowledge_cache(
                                cache_key,
                                "examine",
                                examine_topic,
                                result_text,
                            )
                        except Exception as exc:
                            print(
                                f"[knowledge_client] Examine cache write failed: {exc}",
                                file=sys.stderr,
                            )

            if result_text:
                label = examine_topic.replace("-", " ").title()
                examine_section = f"Examine.com — {label}:\n{result_text}"

    # ------------------------------------------------------------------
    # 4. Assemble output block
    # ------------------------------------------------------------------
    all_sections = pubmed_sections + ([examine_section] if examine_section else [])
    if not all_sections:
        return ""

    body = "\n\n".join(all_sections)
    # Token budget: keep total output under 600 chars
    if len(body) > 560:
        body = body[:557] + "..."

    return f"[RESEARCH CONTEXT]\n\n{body}"


def _append_unique(lst: list[str], item: str) -> None:
    """Append *item* to *lst* only if not already present."""
    if item not in lst:
        lst.append(item)
