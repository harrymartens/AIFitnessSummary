"""Unit tests for knowledge_client — Stage 4A and 4B functions.

All HTTP calls are mocked via unittest.mock so the tests are fully offline.
A real (in-memory) DatabaseClient is used for cache tests to exercise the
full SQLite path without touching any real database.
"""

import sys
import os
from unittest.mock import MagicMock, patch, PropertyMock
from io import StringIO

import pytest

# Ensure project root is importable regardless of pytest invocation path.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from db_client import DatabaseClient
import knowledge_client


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_db(tmp_path) -> DatabaseClient:
    """Return a fresh in-file DatabaseClient for each test."""
    return DatabaseClient(str(tmp_path / "test_kc.db"))


# Minimal PubMed XML fixture containing two articles.
PUBMED_XML = """\
<?xml version="1.0" ?>
<!DOCTYPE PubmedArticleSet PUBLIC "-//NLM//DTD PubMedArticle, 1st January 2024//EN"
  "https://dtd.nlm.nih.gov/ncbi/pubmed/out/pubmed_240101.dtd">
<PubmedArticleSet>
  <PubmedArticle>
    <MedlineCitation>
      <PMID>11111111</PMID>
      <Article>
        <ArticleTitle>HRV and Athletic Recovery</ArticleTitle>
        <Abstract>
          <AbstractText>Heart rate variability is a reliable marker of recovery.</AbstractText>
          <AbstractText Label="CONCLUSION">HRV monitoring improves training outcomes.</AbstractText>
        </Abstract>
        <AuthorList>
          <Author><LastName>Smith</LastName></Author>
          <Author><LastName>Jones</LastName></Author>
        </AuthorList>
      </Article>
      <MedlineJournalInfo/>
    </MedlineCitation>
    <PubmedData>
      <History>
        <PubMedPubDate PubStatus="pubmed">
          <PubDate><Year>2022</Year></PubDate>
        </PubMedPubDate>
      </History>
    </PubmedData>
  </PubmedArticle>
  <PubmedArticle>
    <MedlineCitation>
      <PMID>22222222</PMID>
      <Article>
        <ArticleTitle>Sleep and Strength Performance</ArticleTitle>
        <Abstract>
          <AbstractText>Inadequate sleep reduces muscle protein synthesis.</AbstractText>
        </Abstract>
        <AuthorList>
          <Author><LastName>Brown</LastName></Author>
          <Author><LastName>White</LastName></Author>
          <Author><LastName>Green</LastName></Author>
          <Author><LastName>Black</LastName></Author>
        </AuthorList>
      </Article>
      <MedlineJournalInfo/>
    </MedlineCitation>
    <PubmedData>
      <History>
        <PubMedPubDate PubStatus="pubmed">
          <PubDate><Year>2023</Year></PubDate>
        </PubMedPubDate>
      </History>
    </PubmedData>
  </PubmedArticle>
</PubmedArticleSet>
"""

ESEARCH_JSON = {
    "esearchresult": {
        "idlist": ["11111111", "22222222"],
    }
}

EXAMINE_HTML = """\
<html><head>
  <meta name="description" content="Creatine is one of the most studied supplements.">
</head><body>
  <main>
    <div class="examine-summary">Creatine monohydrate is effective for strength gains.</div>
    <p>Additional context here.</p>
  </main>
</body></html>
"""


# ---------------------------------------------------------------------------
# search_pubmed tests
# ---------------------------------------------------------------------------

class TestSearchPubmed:
    """Tests for knowledge_client.search_pubmed()."""

    def _mock_post(self, url, **kwargs):
        """Side-effect function: return appropriate mock for each URL."""
        resp = MagicMock()
        resp.raise_for_status.return_value = None
        if "esearch" in url:
            resp.json.return_value = ESEARCH_JSON
        else:
            resp.text = PUBMED_XML
        return resp

    @patch("knowledge_client.time.sleep")  # suppress real sleep in tests
    @patch("knowledge_client.requests.post")
    def test_correct_url_construction(self, mock_post, mock_sleep):
        mock_post.side_effect = self._mock_post
        knowledge_client.search_pubmed("HRV recovery", max_results=2)

        calls = mock_post.call_args_list
        assert len(calls) == 2

        esearch_url = calls[0][0][0]
        efetch_url = calls[1][0][0]
        assert "esearch" in esearch_url
        assert "efetch" in efetch_url

    @patch("knowledge_client.time.sleep")
    @patch("knowledge_client.requests.post")
    def test_correct_result_parsing(self, mock_post, mock_sleep):
        mock_post.side_effect = self._mock_post
        results = knowledge_client.search_pubmed("HRV recovery", max_results=2)

        assert len(results) == 2

        first = results[0]
        assert first["pmid"] == "11111111"
        assert first["title"] == "HRV and Athletic Recovery"
        assert "Heart rate variability" in first["abstract"]
        assert "HRV monitoring improves" in first["abstract"]
        assert first["authors"] == "Smith, Jones"
        assert first["year"] == "2022"

        second = results[1]
        assert second["pmid"] == "22222222"
        assert second["title"] == "Sleep and Strength Performance"
        # More than 3 authors → "et al."
        assert "et al." in second["authors"]
        assert "Brown" in second["authors"]

    @patch("knowledge_client.time.sleep")
    @patch("knowledge_client.requests.post")
    def test_esearch_network_error_returns_empty(self, mock_post, mock_sleep):
        mock_post.side_effect = Exception("connection refused")
        results = knowledge_client.search_pubmed("test query")
        assert results == []

    @patch("knowledge_client.time.sleep")
    @patch("knowledge_client.requests.post")
    def test_efetch_network_error_returns_empty(self, mock_post, mock_sleep):
        call_count = [0]

        def side_effect(url, **kwargs):
            call_count[0] += 1
            resp = MagicMock()
            resp.raise_for_status.return_value = None
            if call_count[0] == 1:  # esearch succeeds
                resp.json.return_value = ESEARCH_JSON
            else:  # efetch fails
                resp.raise_for_status.side_effect = Exception("timeout")
            return resp

        mock_post.side_effect = side_effect
        results = knowledge_client.search_pubmed("test query")
        assert results == []

    @patch("knowledge_client.time.sleep")
    @patch("knowledge_client.requests.post")
    def test_empty_idlist_returns_empty(self, mock_post, mock_sleep):
        resp = MagicMock()
        resp.raise_for_status.return_value = None
        resp.json.return_value = {"esearchresult": {"idlist": []}}
        mock_post.return_value = resp

        results = knowledge_client.search_pubmed("obscure topic")
        assert results == []
        # efetch should NOT be called when there are no PMIDs
        assert mock_post.call_count == 1

    @patch("knowledge_client.time.sleep")
    @patch("knowledge_client.requests.post")
    def test_polite_delay_called(self, mock_post, mock_sleep):
        mock_post.side_effect = self._mock_post
        knowledge_client.search_pubmed("HRV recovery", max_results=2)
        mock_sleep.assert_called_once_with(1)

    @patch("knowledge_client.time.sleep")
    @patch("knowledge_client.requests.post")
    def test_user_agent_header_set(self, mock_post, mock_sleep):
        mock_post.side_effect = self._mock_post
        knowledge_client.search_pubmed("HRV recovery", max_results=2)

        for call in mock_post.call_args_list:
            headers = call[1].get("headers") or call[0][1] if len(call[0]) > 1 else {}
            # headers may come as a kwarg
            headers = call[1].get("headers", {})
            assert "AIFitnessSummary" in headers.get("User-Agent", "")


# ---------------------------------------------------------------------------
# fetch_examine tests
# ---------------------------------------------------------------------------

class TestFetchExamine:
    """Tests for knowledge_client.fetch_examine()."""

    @patch("knowledge_client.requests.get")
    def test_successful_parse_returns_dict(self, mock_get):
        resp = MagicMock()
        resp.raise_for_status.return_value = None
        resp.text = EXAMINE_HTML
        mock_get.return_value = resp

        result = knowledge_client.fetch_examine("creatine")

        assert result is not None
        assert result["topic"] == "creatine"
        assert "Creatine monohydrate" in result["summary"]
        assert "examine.com" in result["url"]

    @patch("knowledge_client.requests.get")
    def test_uses_slug_url(self, mock_get):
        resp = MagicMock()
        resp.raise_for_status.return_value = None
        resp.text = EXAMINE_HTML
        mock_get.return_value = resp

        knowledge_client.fetch_examine("Fish Oil")
        called_url = mock_get.call_args[0][0]
        assert "fish-oil" in called_url
        assert "examine.com/topics" in called_url

    @patch("knowledge_client.requests.get")
    def test_network_error_returns_none(self, mock_get):
        mock_get.side_effect = Exception("connection error")
        result = knowledge_client.fetch_examine("creatine")
        assert result is None

    @patch("knowledge_client.requests.get")
    def test_http_error_returns_none(self, mock_get):
        resp = MagicMock()
        resp.raise_for_status.side_effect = Exception("404 Not Found")
        mock_get.return_value = resp
        result = knowledge_client.fetch_examine("nonexistent-topic")
        assert result is None

    @patch("knowledge_client.requests.get")
    def test_summary_truncated_to_500_chars(self, mock_get):
        long_summary = "x" * 1000
        html = f'<html><body><div class="examine-summary">{long_summary}</div></body></html>'
        resp = MagicMock()
        resp.raise_for_status.return_value = None
        resp.text = html
        mock_get.return_value = resp

        result = knowledge_client.fetch_examine("creatine")
        assert result is not None
        assert len(result["summary"]) <= 500

    @patch("knowledge_client.requests.get")
    def test_meta_description_fallback(self, mock_get):
        html = """\
<html><head>
  <meta name="description" content="Caffeine boosts endurance performance significantly.">
</head><body><main><p></p></main></body></html>
"""
        resp = MagicMock()
        resp.raise_for_status.return_value = None
        resp.text = html
        mock_get.return_value = resp

        result = knowledge_client.fetch_examine("caffeine")
        assert result is not None
        assert "Caffeine" in result["summary"]

    @patch("knowledge_client.requests.get")
    def test_timeout_is_set(self, mock_get):
        resp = MagicMock()
        resp.raise_for_status.return_value = None
        resp.text = EXAMINE_HTML
        mock_get.return_value = resp

        knowledge_client.fetch_examine("creatine")
        _, kwargs = mock_get.call_args
        assert kwargs.get("timeout") == 8


# ---------------------------------------------------------------------------
# get_research_context tests
# ---------------------------------------------------------------------------

class TestGetResearchContext:
    """Tests for knowledge_client.get_research_context()."""

    def _make_metrics(
        self,
        hrv_avg=None,
        sleep_avg=None,
        avg_steps=None,
        workouts_per_week=0,
    ):
        return {
            "hrv": {"period_avg_ms": hrv_avg} if hrv_avg is not None else {},
            "sleep": {"avg_total_h": sleep_avg} if sleep_avg is not None else {},
            "stats": {"avg_daily_steps": avg_steps} if avg_steps is not None else {},
            "workouts_per_week": workouts_per_week,
        }

    @patch("knowledge_client.fetch_examine", return_value=None)
    @patch("knowledge_client.search_pubmed")
    @patch("knowledge_client.get_db")
    def test_cache_miss_triggers_pubmed_fetch(
        self, mock_get_db, mock_pubmed, mock_examine, tmp_path
    ):
        db = make_db(tmp_path)
        mock_get_db.return_value = db
        mock_pubmed.return_value = [
            {
                "title": "HRV Recovery Study",
                "abstract": "HRV is useful for recovery monitoring.",
                "authors": "Smith, Jones",
                "year": "2022",
                "pmid": "12345",
            }
        ]

        metrics = self._make_metrics(hrv_avg=40)
        result = knowledge_client.get_research_context(metrics)

        mock_pubmed.assert_called_once()
        assert "HRV Recovery Study" in result

    @patch("knowledge_client.fetch_examine", return_value=None)
    @patch("knowledge_client.search_pubmed")
    @patch("knowledge_client.get_db")
    def test_cache_hit_skips_pubmed_fetch(
        self, mock_get_db, mock_pubmed, mock_examine, tmp_path
    ):
        db = make_db(tmp_path)
        mock_get_db.return_value = db

        # Pre-populate the cache
        import hashlib
        query = "HRV heart rate variability training recovery athletes"
        cache_key = "pubmed:" + hashlib.md5(query.encode()).hexdigest()
        db.save_knowledge_cache(cache_key, "pubmed", query, "Cached HRV result text")

        metrics = self._make_metrics(hrv_avg=40)
        result = knowledge_client.get_research_context(metrics)

        mock_pubmed.assert_not_called()
        assert "Cached HRV result text" in result

    @patch("knowledge_client.fetch_examine", return_value=None)
    @patch("knowledge_client.search_pubmed", return_value=[])
    @patch("knowledge_client.get_db")
    def test_all_fail_returns_empty_string(
        self, mock_get_db, mock_pubmed, mock_examine, tmp_path
    ):
        db = make_db(tmp_path)
        mock_get_db.return_value = db
        metrics = self._make_metrics()
        result = knowledge_client.get_research_context(metrics)
        assert result == ""

    @patch("knowledge_client.fetch_examine", return_value=None)
    @patch("knowledge_client.search_pubmed")
    @patch("knowledge_client.get_db")
    def test_output_within_token_budget(
        self, mock_get_db, mock_pubmed, mock_examine, tmp_path
    ):
        db = make_db(tmp_path)
        mock_get_db.return_value = db
        # Return a very long abstract to stress the budget
        long_abstract = "A" * 2000
        mock_pubmed.return_value = [
            {
                "title": "Long Paper Title Here",
                "abstract": long_abstract,
                "authors": "Author A, Author B",
                "year": "2023",
                "pmid": "99999",
            }
        ]

        metrics = self._make_metrics(hrv_avg=40)
        result = knowledge_client.get_research_context(metrics)

        # Total output (including header) should stay around 600 chars
        assert len(result) <= 700  # slight headroom for the [RESEARCH CONTEXT] header

    @patch("knowledge_client.fetch_examine")
    @patch("knowledge_client.search_pubmed")
    @patch("knowledge_client.get_db")
    def test_examine_called_for_strength_goal(
        self, mock_get_db, mock_pubmed, mock_examine, tmp_path
    ):
        db = make_db(tmp_path)
        mock_get_db.return_value = db
        mock_pubmed.return_value = []
        mock_examine.return_value = {
            "topic": "creatine",
            "summary": "Creatine is effective.",
            "url": "https://examine.com/topics/creatine/",
        }

        metrics = self._make_metrics()
        goal = {"primary_objective": "Build strength and muscle mass"}
        result = knowledge_client.get_research_context(metrics, goal=goal)

        mock_examine.assert_called_once_with("creatine")
        assert "Creatine" in result

    @patch("knowledge_client.fetch_examine")
    @patch("knowledge_client.search_pubmed")
    @patch("knowledge_client.get_db")
    def test_examine_called_for_weight_goal(
        self, mock_get_db, mock_pubmed, mock_examine, tmp_path
    ):
        db = make_db(tmp_path)
        mock_get_db.return_value = db
        mock_pubmed.return_value = []
        mock_examine.return_value = {
            "topic": "caloric-restriction",
            "summary": "Caloric restriction promotes fat loss.",
            "url": "https://examine.com/topics/caloric-restriction/",
        }

        metrics = self._make_metrics()
        goal = {"primary_objective": "Lose weight"}
        result = knowledge_client.get_research_context(metrics, goal=goal)

        mock_examine.assert_called_once_with("caloric-restriction")

    @patch("knowledge_client.fetch_examine")
    @patch("knowledge_client.search_pubmed")
    @patch("knowledge_client.get_db")
    def test_examine_called_for_endurance_goal(
        self, mock_get_db, mock_pubmed, mock_examine, tmp_path
    ):
        db = make_db(tmp_path)
        mock_get_db.return_value = db
        mock_pubmed.return_value = []
        mock_examine.return_value = {
            "topic": "caffeine",
            "summary": "Caffeine improves endurance.",
            "url": "https://examine.com/topics/caffeine/",
        }

        metrics = self._make_metrics()
        goal = {"primary_objective": "Improve endurance"}
        result = knowledge_client.get_research_context(metrics, goal=goal)

        mock_examine.assert_called_once_with("caffeine")

    @patch("knowledge_client.fetch_examine", return_value=None)
    @patch("knowledge_client.search_pubmed", return_value=[])
    @patch("knowledge_client.get_db")
    def test_no_goal_no_examine_call(
        self, mock_get_db, mock_pubmed, mock_examine, tmp_path
    ):
        db = make_db(tmp_path)
        mock_get_db.return_value = db

        metrics = self._make_metrics()
        knowledge_client.get_research_context(metrics, goal=None)
        mock_examine.assert_not_called()

    @patch("knowledge_client.fetch_examine", return_value=None)
    @patch("knowledge_client.search_pubmed")
    @patch("knowledge_client.get_db")
    def test_result_starts_with_research_context_header(
        self, mock_get_db, mock_pubmed, mock_examine, tmp_path
    ):
        db = make_db(tmp_path)
        mock_get_db.return_value = db
        mock_pubmed.return_value = [
            {
                "title": "Test Paper",
                "abstract": "Test abstract text.",
                "authors": "Author A",
                "year": "2024",
                "pmid": "55555",
            }
        ]

        metrics = self._make_metrics(sleep_avg=5.5)
        result = knowledge_client.get_research_context(metrics)
        assert result.startswith("[RESEARCH CONTEXT]")

    @patch("knowledge_client.fetch_examine", return_value=None)
    @patch("knowledge_client.search_pubmed")
    @patch("knowledge_client.get_db")
    def test_max_two_queries(
        self, mock_get_db, mock_pubmed, mock_examine, tmp_path
    ):
        db = make_db(tmp_path)
        mock_get_db.return_value = db
        mock_pubmed.return_value = []

        # Metrics that trigger multiple signals simultaneously
        metrics = self._make_metrics(
            hrv_avg=40,
            sleep_avg=5.5,
            avg_steps=3000,
            workouts_per_week=6,
        )
        knowledge_client.get_research_context(metrics)

        # search_pubmed should be called at most 2 times
        assert mock_pubmed.call_count <= 2


# ---------------------------------------------------------------------------
# get_knowledge_context (Stage 4A) topic heuristics
# ---------------------------------------------------------------------------

class TestGetKnowledgeContextHeuristics:
    """Tests for select_relevant_topics() topic selection logic."""

    def test_low_hrv_selects_hrv_and_recovery(self):
        metrics = {
            "hrv": {"period_avg_ms": 35},
        }
        topics = knowledge_client.select_relevant_topics(metrics)
        assert "hrv" in topics
        assert "recovery" in topics

    def test_declining_hrv_selects_hrv(self):
        # Build daily HRV where recent values are lower than older ones
        daily = [
            {"last_night_avg_ms": 60},
            {"last_night_avg_ms": 62},
            {"last_night_avg_ms": 58},
            # recent (last 3)
            {"last_night_avg_ms": 45},
            {"last_night_avg_ms": 43},
            {"last_night_avg_ms": 40},
        ]
        metrics = {
            "hrv": {"period_avg_ms": 52, "daily": daily},  # avg ok but declining
        }
        topics = knowledge_client.select_relevant_topics(metrics)
        assert "hrv" in topics

    def test_short_sleep_selects_sleep(self):
        metrics = {
            "sleep": {"avg_total_h": 5.8},
        }
        topics = knowledge_client.select_relevant_topics(metrics)
        assert "sleep" in topics

    def test_low_deep_sleep_pct_selects_sleep(self):
        metrics = {
            "sleep": {"avg_total_h": 7.0, "avg_deep_h": 0.5},  # <15%
        }
        topics = knowledge_client.select_relevant_topics(metrics)
        assert "sleep" in topics

    def test_high_stress_selects_recovery(self):
        metrics = {
            "stress": {"avg_stress": 70},
        }
        topics = knowledge_client.select_relevant_topics(metrics)
        assert "recovery" in topics

    def test_low_body_battery_selects_recovery(self):
        metrics = {
            "body_battery": {"avg_max": 30},
        }
        topics = knowledge_client.select_relevant_topics(metrics)
        assert "recovery" in topics

    def test_vo2max_selects_cardiovascular(self):
        metrics = {
            "vo2max": {"vo2_max": 45.0},
        }
        topics = knowledge_client.select_relevant_topics(metrics)
        assert "cardiovascular" in topics

    def test_runs_selects_cardiovascular(self):
        metrics = {
            "runs": {"run_count": 3},
        }
        topics = knowledge_client.select_relevant_topics(metrics)
        assert "cardiovascular" in topics

    def test_many_workouts_selects_strength(self):
        metrics = {
            "workout_count": 5,
        }
        topics = knowledge_client.select_relevant_topics(metrics)
        assert "strength_training" in topics

    def test_default_fallback_no_metrics(self):
        topics = knowledge_client.select_relevant_topics({})
        assert "strength_training" in topics
        assert "sleep" in topics

    def test_at_most_two_topics_returned(self):
        # All signals firing at once
        metrics = {
            "hrv": {"period_avg_ms": 30},
            "sleep": {"avg_total_h": 5.0},
            "stress": {"avg_stress": 80},
            "body_battery": {"avg_max": 20},
            "vo2max": {"vo2_max": 50.0},
            "workout_count": 6,
        }
        topics = knowledge_client.select_relevant_topics(metrics)
        assert len(topics) <= 2

    def test_no_duplicate_topics(self):
        metrics = {
            "hrv": {"period_avg_ms": 30},
            "stress": {"avg_stress": 75},  # both hrv and stress → recovery
        }
        topics = knowledge_client.select_relevant_topics(metrics)
        assert len(topics) == len(set(topics))
