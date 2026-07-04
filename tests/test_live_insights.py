"""Tests for the live insight-generation path (app/insights.py + the
POST /api/insights `mode: "live"` branch in app/main.py, including the
put_insight_block write-through).

Covers:
  - app/insights.py._extract_json: plain JSON, fenced JSON (```json and ```),
    JSON embedded in surrounding prose, and genuinely unparseable output.
  - app/insights.py.generate_insights: shape normalization (defensive
    fallback when the model returns non-dict JSON), and that every fact sent
    to the model (candidate JSON with its "source"/"sources" fields) is what
    the grounding contract is built on -- i.e. that a bullet's source is only
    ever traceable to data we actually supplied, never invented.
  - POST /api/insights live branch: mode "live" on a cache miss, write-through
    persists the block so a second identical request is served as "cached"
    (and the mocked LLM is not invoked a second time), a pre-existing cache
    file short-circuits the live path entirely, "unavailable" when no key and
    no cache, 404 for an unknown race_id, and clean 502s (never a 500 stack)
    on both an OpenRouter-style API failure and unparseable model output.
  - Write-through is best-effort: a put_insight_block failure must not turn
    an already-successful live generation into an error response.

The OpenAI client is mocked via a fake class built from real
`openai.AuthenticationError`/response-shaped objects where relevant,
monkeypatched only onto app.insights's own `OpenAI` reference -- exactly the
"monkeypatch the module's own imported name" idiom test_google_civic.py uses
for httpx, so these tests never risk redirecting some other module's client.

app/datastore.py's INSIGHTS_DIR is monkeypatched to a pytest tmp_path for
every test in this file (autouse fixture), so nothing here ever reads or
writes the real data/tx/insights/ directory -- these tests cannot damage the
committed cache, unlike the manual live proof (see the task write-up), which
used the real tx-cd05-2026 race, a temporary rename to .bak, and a byte-for-
byte sha256-verified restore.

Plus one honest live smoke call against the real OpenRouter API (Claude
Sonnet 4.5), only if OPENROUTER_API_KEY actually exists in the environment
at test-run time (skipped, never failed, otherwise) -- mirrors
test_google_civic.py's test_live_smoke_if_key_present pattern. It uses a
tiny synthetic 2-candidate fixture to keep token usage (and cost) minimal,
and automatically checks the full grounding contract: every bullet's source
must be traceable to the candidate JSON supplied.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Callable, Union

import httpx
import openai
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from app import datastore, insights, main  # noqa: E402
from app.middleware import RATE_LIMIT_HITS  # noqa: E402

# A real, stable, low-demo-rank race committed to the gold dataset (TX-05,
# data_quality.demo_rank 23). Used only for its race_id/candidate_ids
# metadata (read-only, via datastore.get_race) -- INSIGHTS_DIR is redirected
# to a tmp dir below, so no test here ever touches its real cache file.
REAL_RACE_ID = "tx-cd05-2026"

# handler(create_kwargs) -> completion text (str) or a BaseException to raise
Handler = Callable[[dict[str, Any]], Union[str, BaseException]]


# ---------------------------------------------------------------------------
# Isolation fixtures -- these tests must never depend on run order, touch the
# real data/tx/insights/ files, or depend on requests other test files
# already made against the (shared, in-process) rate limiter.
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _isolate_insights_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(datastore, "INSIGHTS_DIR", tmp_path / "insights")
    monkeypatch.setattr(datastore, "_pool", None)
    monkeypatch.setattr(datastore, "_pg_init_done", True)  # force JSON-fallback mode deterministically
    yield


@pytest.fixture(autouse=True)
def _reset_rate_limit():
    RATE_LIMIT_HITS.clear()
    yield


def _install_fake_openai(monkeypatch, handler: Handler) -> None:
    """Monkeypatch app.insights's own `OpenAI` reference to a stand-in whose
    chat.completions.create() is driven by `handler`. Mirrors
    test_google_civic.py's `_install_fake_civic_client` idiom: only the
    module-local name is patched, so a real `from openai import OpenAI`
    anywhere else is unaffected."""

    class _FakeMessage:
        def __init__(self, content: str) -> None:
            self.content = content

    class _FakeChoice:
        def __init__(self, content: str) -> None:
            self.message = _FakeMessage(content)

    class _FakeCompletion:
        def __init__(self, content: str) -> None:
            self.choices = [_FakeChoice(content)]

    class _FakeCompletions:
        def create(self, **kwargs: Any) -> "_FakeCompletion":
            outcome = handler(kwargs)
            if isinstance(outcome, BaseException):
                raise outcome
            return _FakeCompletion(outcome)

    class _FakeChat:
        def __init__(self) -> None:
            self.completions = _FakeCompletions()

    class _FakeOpenAI:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self.chat = _FakeChat()

    monkeypatch.setattr(insights, "OpenAI", _FakeOpenAI)


def _collect_sources(obj: Any, acc: set[str]) -> None:
    """Recursively collect every string under a "source" or "sources" key --
    the same grounding-check helper used in the manual live proof, now
    codified as a reusable assertion."""
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key in ("source", "sources"):
                if isinstance(value, str):
                    acc.add(value)
                elif isinstance(value, list):
                    acc.update(x for x in value if isinstance(x, str))
            _collect_sources(value, acc)
    elif isinstance(obj, list):
        for item in obj:
            _collect_sources(item, acc)


def _assert_grounded(candidates_block: dict[str, Any], valid_sources: set[str]) -> None:
    assert candidates_block, "expected at least one candidate's bullets back"
    for cid, bullets in candidates_block.items():
        assert isinstance(bullets, list) and bullets, f"expected at least one bullet for {cid}"
        for bullet in bullets:
            assert bullet.get("text"), f"bullet for {cid} missing text"
            assert bullet.get("source"), f"bullet for {cid} missing source"
            assert bullet["source"] in valid_sources, (
                f"[grounding violation] source {bullet['source']!r} for {cid} "
                "is not traceable to the candidate JSON supplied"
            )


# ---------------------------------------------------------------------------
# Fixture data for direct generate_insights() unit tests (synthetic, not the
# real gold dataset, so these tests are independent of pipeline reruns).
# ---------------------------------------------------------------------------

FIXTURE_PROFILE = {"veteran": True}
FIXTURE_RACE = {"race_id": "test-race-001", "office": "Test Office", "level": "federal", "district": "TX-99", "context": {}}
FIXTURE_CANDIDATES = {
    "candidate-a": {
        "name": "Alex Testcase",
        "party": "Independent",
        "positions": [
            {
                "issue": "healthcare",
                "summary": "Supports expanding rural clinics.",
                "source": "https://example.gov/candidate-a/healthcare",
            }
        ],
        "sources": ["https://example.gov/candidate-a"],
    },
    "candidate-b": {
        "name": "Bailey Fixture",
        "party": "Independent",
        "finance": {"receipts": 5000, "source": "https://example.gov/candidate-b/finance"},
        "sources": ["https://example.gov/candidate-b"],
    },
}


def _canned_model_json() -> str:
    return json.dumps(
        {
            "candidates": {
                "candidate-a": [
                    {
                        "text": "Candidate A supports expanding rural clinics, which as a veteran could improve "
                        "your access to VA-adjacent care options.",
                        "source": "https://example.gov/candidate-a/healthcare",
                    }
                ],
                "candidate-b": [
                    {
                        "text": "Candidate B's campaign reported $5,000 in receipts; no veteran-specific policy "
                        "data is available in our set.",
                        "source": "https://example.gov/candidate-b/finance",
                    }
                ],
            },
            "summary": "Candidate A has a stated healthcare position; Candidate B's available data is limited "
            "to campaign finance.",
            "caveats": "This is not exhaustive and is not an endorsement.",
        }
    )


# ---------------------------------------------------------------------------
# 1. _extract_json -- parse behavior (plain / fenced / embedded / unparseable)
# ---------------------------------------------------------------------------


def test_extract_json_plain():
    assert insights._extract_json('{"a": 1}') == {"a": 1}


def test_extract_json_fenced_with_json_tag():
    raw = '```json\n{"a": 1}\n```'
    assert insights._extract_json(raw) == {"a": 1}


def test_extract_json_fenced_without_lang_tag():
    raw = '```\n{"a": 1}\n```'
    assert insights._extract_json(raw) == {"a": 1}


def test_extract_json_embedded_in_prose_fallback():
    raw = 'Sure, here you go:\n{"a": 1}\nHope that helps!'
    assert insights._extract_json(raw) == {"a": 1}


def test_extract_json_unparseable_raises_value_error():
    with pytest.raises(ValueError):
        insights._extract_json("this is not json at all, no braces here")


def test_extract_json_braces_present_but_invalid_still_raises_value_error():
    """json.JSONDecodeError is itself a ValueError subclass, so the fallback
    slice-extraction failure still surfaces as something main.py's
    `except ValueError:` branch catches."""
    with pytest.raises(ValueError):
        insights._extract_json("prose before { not: valid, json, at, all } prose after")


# ---------------------------------------------------------------------------
# 2. build_user_prompt -- only present profile fields are rendered
# ---------------------------------------------------------------------------


def test_build_user_prompt_omits_missing_profile_fields():
    prompt = insights.build_user_prompt({"veteran": True}, FIXTURE_RACE, FIXTURE_CANDIDATES)
    assert "veteran: True" in prompt
    # Fields never supplied must never be invented into the prompt text.
    assert "occupation" not in prompt
    assert "income_bracket" not in prompt


def test_build_user_prompt_empty_profile_says_so_explicitly():
    prompt = insights.build_user_prompt({}, FIXTURE_RACE, FIXTURE_CANDIDATES)
    assert "(no profile fields provided)" in prompt


# ---------------------------------------------------------------------------
# 3. generate_insights() -- parse/shape-normalization unit tests (mocked client)
# ---------------------------------------------------------------------------


def test_generate_insights_parses_plain_json(monkeypatch):
    captured: dict[str, Any] = {}

    def handler(kwargs: dict[str, Any]) -> str:
        captured.update(kwargs)
        return _canned_model_json()

    _install_fake_openai(monkeypatch, handler)

    result = insights.generate_insights(FIXTURE_PROFILE, FIXTURE_RACE, FIXTURE_CANDIDATES, api_key="fake-key")

    assert captured["model"] == insights.MODEL
    assert captured["messages"][0]["role"] == "system"
    assert captured["messages"][1]["role"] == "user"
    assert set(result.keys()) == {"candidates", "summary", "caveats"}
    assert set(result["candidates"].keys()) == {"candidate-a", "candidate-b"}
    assert result["summary"].startswith("Candidate A")


def test_generate_insights_parses_fenced_json(monkeypatch):
    def handler(kwargs: dict[str, Any]) -> str:
        return "```json\n" + _canned_model_json() + "\n```"

    _install_fake_openai(monkeypatch, handler)
    result = insights.generate_insights(FIXTURE_PROFILE, FIXTURE_RACE, FIXTURE_CANDIDATES, api_key="fake-key")
    assert set(result["candidates"].keys()) == {"candidate-a", "candidate-b"}


def test_generate_insights_non_dict_json_defaults_to_empty_shape(monkeypatch):
    """Defensive shape normalization: valid JSON that isn't an object (e.g. a
    bare array) must never crash the caller -- it degrades to the documented
    empty shape instead."""

    def handler(kwargs: dict[str, Any]) -> str:
        return "[1, 2, 3]"

    _install_fake_openai(monkeypatch, handler)
    result = insights.generate_insights(FIXTURE_PROFILE, FIXTURE_RACE, FIXTURE_CANDIDATES, api_key="fake-key")
    assert result == {"candidates": {}, "summary": "", "caveats": ""}


def test_generate_insights_unparseable_raises_value_error(monkeypatch):
    def handler(kwargs: dict[str, Any]) -> str:
        return "the model rambled and never produced JSON, sorry about that"

    _install_fake_openai(monkeypatch, handler)
    with pytest.raises(ValueError):
        insights.generate_insights(FIXTURE_PROFILE, FIXTURE_RACE, FIXTURE_CANDIDATES, api_key="fake-key")


# ---------------------------------------------------------------------------
# 4. Grounding -- every bullet's source must be traceable to the candidate
#    JSON we actually supplied (the hard rule from CLAUDE.md / SYSTEM_PROMPT).
# ---------------------------------------------------------------------------


def test_generate_insights_grounding_sources_traceable_to_candidate_json(monkeypatch):
    def handler(kwargs: dict[str, Any]) -> str:
        # The candidate JSON (with its source URLs) must actually be present
        # in what we send the model -- grounding is only possible if the
        # facts and their citations are in context.
        user_msg = kwargs["messages"][1]["content"]
        assert "https://example.gov/candidate-a/healthcare" in user_msg
        assert "https://example.gov/candidate-b/finance" in user_msg
        return _canned_model_json()

    _install_fake_openai(monkeypatch, handler)
    result = insights.generate_insights(FIXTURE_PROFILE, FIXTURE_RACE, FIXTURE_CANDIDATES, api_key="fake-key")

    valid_sources: set[str] = set()
    _collect_sources(FIXTURE_CANDIDATES, valid_sources)
    _assert_grounded(result["candidates"], valid_sources)


def test_generate_insights_ungrounded_source_would_be_caught(monkeypatch):
    """Proves the grounding assertion helper is not a tautology: a bullet
    citing a source never present in the supplied candidate JSON must fail
    _assert_grounded."""

    def handler(kwargs: dict[str, Any]) -> str:
        return json.dumps(
            {
                "candidates": {
                    "candidate-a": [{"text": "fabricated claim", "source": "https://not-in-our-data.example.com"}]
                },
                "summary": "s",
                "caveats": "c",
            }
        )

    _install_fake_openai(monkeypatch, handler)
    result = insights.generate_insights(FIXTURE_PROFILE, FIXTURE_RACE, FIXTURE_CANDIDATES, api_key="fake-key")

    valid_sources: set[str] = set()
    _collect_sources(FIXTURE_CANDIDATES, valid_sources)
    with pytest.raises(AssertionError, match="grounding violation"):
        _assert_grounded(result["candidates"], valid_sources)


# ---------------------------------------------------------------------------
# 5. POST /api/insights -- live mode, write-through, cache priority, 404,
#    "unavailable", and clean 502s. tmp INSIGHTS_DIR (autouse fixture above)
#    means none of this ever touches the real data/tx/insights/ files.
# ---------------------------------------------------------------------------


def _real_race_candidate_ids() -> list[str]:
    race = datastore.get_race(REAL_RACE_ID)
    assert race is not None, f"fixture race {REAL_RACE_ID!r} must exist in the gold dataset"
    return race["candidate_ids"]


def _canned_real_race_json() -> str:
    cids = _real_race_candidate_ids()
    return json.dumps(
        {
            "candidates": {cid: [{"text": f"Live-mode test bullet for {cid}.", "source": "https://example.gov/test"}] for cid in cids},
            "summary": "Test summary comparing the candidates.",
            "caveats": "Test caveats: not exhaustive, not an endorsement.",
        }
    )


def test_endpoint_live_mode_and_write_through_then_served_cached(monkeypatch):
    monkeypatch.setattr(main, "OPENROUTER_API_KEY", "fake-key-for-tests")
    call_count = {"n": 0}

    def handler(kwargs: dict[str, Any]) -> str:
        call_count["n"] += 1
        return _canned_real_race_json()

    _install_fake_openai(monkeypatch, handler)

    client = TestClient(main.app)
    resp1 = client.post("/api/insights", json={"profile": {"veteran": True}, "race_id": REAL_RACE_ID})
    assert resp1.status_code == 200
    body1 = resp1.json()
    assert body1["mode"] == "live"
    assert body1["archetype_used"] == "veteran"
    assert call_count["n"] == 1
    for bullets in body1["candidates"].values():
        for bullet in bullets:
            assert bullet["text"]
            assert bullet["source"]

    # Write-through: a file now exists in the (tmp) INSIGHTS_DIR for this race.
    written = datastore.INSIGHTS_DIR / f"{REAL_RACE_ID}.json"
    assert written.exists(), "put_insight_block must have written through after a successful live generation"
    on_disk = json.loads(written.read_text(encoding="utf-8"))
    assert "veteran" in on_disk.get("archetypes", {})
    assert on_disk["archetypes"]["veteran"]["candidates"] == body1["candidates"]

    # Second identical request is served from cache -- the LLM is not called again.
    resp2 = client.post("/api/insights", json={"profile": {"veteran": True}, "race_id": REAL_RACE_ID})
    assert resp2.status_code == 200
    body2 = resp2.json()
    assert body2["mode"] == "cached"
    assert call_count["n"] == 1, "second identical request must not re-invoke the LLM"
    assert body2["candidates"] == body1["candidates"]
    assert body2["summary"] == body1["summary"]
    assert body2["caveats"] == body1["caveats"]


def test_endpoint_preexisting_cache_short_circuits_live_path(monkeypatch):
    """A cache file that already exists must be served without ever touching
    the LLM -- CLAUDE.md: "Live OpenRouter generation only when no cache file
    exists AND OPENROUTER_API_KEY is set."."""
    monkeypatch.setattr(main, "OPENROUTER_API_KEY", "fake-key-for-tests")
    cids = _real_race_candidate_ids()
    datastore.put_insight_block(
        REAL_RACE_ID,
        "base",
        {
            "candidates": {cids[0]: [{"text": "seeded", "source": "https://example.gov/seed"}]},
            "summary": "seeded summary",
            "caveats": "seeded caveats",
        },
    )

    def handler(kwargs: dict[str, Any]) -> str:
        raise AssertionError("must not call the LLM when a cache file already exists")

    _install_fake_openai(monkeypatch, handler)

    client = TestClient(main.app)
    resp = client.post("/api/insights", json={"profile": {}, "race_id": REAL_RACE_ID})
    assert resp.status_code == 200
    body = resp.json()
    assert body["mode"] == "cached"
    assert body["summary"] == "seeded summary"


def test_endpoint_unavailable_when_no_key_and_no_cache(monkeypatch):
    monkeypatch.setattr(main, "OPENROUTER_API_KEY", None)
    client = TestClient(main.app)
    resp = client.post("/api/insights", json={"profile": {}, "race_id": REAL_RACE_ID})
    assert resp.status_code == 200
    assert resp.json()["mode"] == "unavailable"


def test_endpoint_404_unknown_race_id(monkeypatch):
    monkeypatch.setattr(main, "OPENROUTER_API_KEY", "fake-key-for-tests")
    client = TestClient(main.app)
    resp = client.post("/api/insights", json={"profile": {}, "race_id": "tx-does-not-exist-9999"})
    assert resp.status_code == 404


def test_write_through_failure_does_not_break_a_successful_live_response(monkeypatch):
    """put_insight_block is best-effort: a caching failure must never turn an
    already-successful live generation into an error response (see the
    comment above the call site in app/main.py)."""
    monkeypatch.setattr(main, "OPENROUTER_API_KEY", "fake-key-for-tests")

    def handler(kwargs: dict[str, Any]) -> str:
        return _canned_real_race_json()

    _install_fake_openai(monkeypatch, handler)

    def _boom(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("simulated disk-full write-through failure")

    monkeypatch.setattr(datastore, "put_insight_block", _boom)

    client = TestClient(main.app)
    resp = client.post("/api/insights", json={"profile": {"veteran": True}, "race_id": REAL_RACE_ID})
    assert resp.status_code == 200
    assert resp.json()["mode"] == "live"


# ---------------------------------------------------------------------------
# 6. Failure paths -- clean 502 with a `detail` field, never a hang or a 500
#    stack. (The live proof of "never a hang" -- a real bogus-key call
#    against the real OpenRouter endpoint completing in ~1.4s with a clean
#    502 -- was done manually against a throwaway uvicorn port; see the task
#    write-up. These are the fast, deterministic, mocked-equivalent tests.)
# ---------------------------------------------------------------------------


def test_endpoint_502_on_openrouter_style_auth_failure(monkeypatch):
    monkeypatch.setattr(main, "OPENROUTER_API_KEY", "fake-key-for-tests")

    def handler(kwargs: dict[str, Any]) -> BaseException:
        request = httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions")
        response = httpx.Response(401, request=request, json={"error": {"message": "Invalid API key"}})
        return openai.AuthenticationError("Invalid API key", response=response, body=None)

    _install_fake_openai(monkeypatch, handler)

    client = TestClient(main.app)
    resp = client.post("/api/insights", json={"profile": {"veteran": True}, "race_id": REAL_RACE_ID})

    assert resp.status_code == 502
    assert resp.json() == {"detail": "Insight generation failed, try again"}
    assert "Traceback" not in resp.text
    assert "AuthenticationError" not in resp.text


def test_endpoint_502_on_unparseable_model_output(monkeypatch):
    monkeypatch.setattr(main, "OPENROUTER_API_KEY", "fake-key-for-tests")

    def handler(kwargs: dict[str, Any]) -> str:
        return "the model rambled and never produced JSON"

    _install_fake_openai(monkeypatch, handler)

    client = TestClient(main.app)
    resp = client.post("/api/insights", json={"profile": {"veteran": True}, "race_id": REAL_RACE_ID})

    assert resp.status_code == 502
    assert resp.json() == {"detail": "Could not generate insights right now, try again"}


def test_openai_client_has_a_bounded_default_timeout():
    """app/insights.py does not pass an explicit `timeout=` to OpenAI(...) or
    to chat.completions.create(...) -- confirm the SDK's own built-in default
    is nonetheless a bounded, finite timeout (never "wait forever"), so a
    stalled OpenRouter connection cannot hang a request indefinitely. See the
    task write-up for the honest gap this surfaces: the timeout is real but
    implicit (SDK default), not an explicit choice in this project's code."""
    client = insights.OpenAI(base_url=insights.OPENROUTER_BASE_URL, api_key="fake-key")
    timeout = client.timeout
    assert timeout is not None
    # httpx.Timeout exposes connect/read/write/pool; all must be finite numbers.
    for attr in ("connect", "read", "write", "pool"):
        value = getattr(timeout, attr)
        assert value is not None and value != float("inf"), f"timeout.{attr} must be finite, got {value!r}"


# ---------------------------------------------------------------------------
# 7. Optional live smoke call -- only runs if a real key is actually set.
# ---------------------------------------------------------------------------

LIVE_FIXTURE_PROFILE = {"veteran": True, "occupation": "teacher"}
LIVE_FIXTURE_RACE = {
    "race_id": "test-live-smoke-race",
    "office": "Test Office",
    "level": "federal",
    "district": "TX-99",
    "context": {},
}
LIVE_FIXTURE_CANDIDATES = {
    "candidate-a": {
        "name": "Alex Testcase",
        "party": "Independent",
        "positions": [
            {
                "issue": "education",
                "summary": "Supports raising teacher pay by 10%.",
                "source": "https://example.gov/candidate-a/education",
            }
        ],
        "sources": ["https://example.gov/candidate-a"],
    },
    "candidate-b": {
        "name": "Bailey Fixture",
        "party": "Independent",
        "finance": {"receipts": 5000, "source": "https://example.gov/candidate-b/finance"},
        "sources": ["https://example.gov/candidate-b"],
    },
}


@pytest.mark.skipif(
    not os.environ.get("OPENROUTER_API_KEY"),
    reason="OPENROUTER_API_KEY not set in the environment -- live smoke skipped",
)
def test_live_smoke_if_key_present():
    """One honest live call against the real OpenRouter API (model =
    app.insights.MODEL, currently anthropic/claude-sonnet-4.5 -- verified
    present on GET https://openrouter.ai/api/v1/models as part of this task).
    Uses a tiny synthetic 2-candidate fixture to keep token usage (and cost)
    minimal. Asserts the full grounding contract automatically: every bullet
    must carry text+source, and every source must be traceable to a
    source/sources field actually present in the candidate JSON supplied --
    never invented."""
    result = insights.generate_insights(
        LIVE_FIXTURE_PROFILE,
        LIVE_FIXTURE_RACE,
        LIVE_FIXTURE_CANDIDATES,
        api_key=os.environ["OPENROUTER_API_KEY"],
    )

    assert isinstance(result, dict)
    assert set(result.keys()) >= {"candidates", "summary", "caveats"}
    assert isinstance(result["candidates"], dict)

    valid_sources: set[str] = set()
    _collect_sources(LIVE_FIXTURE_CANDIDATES, valid_sources)
    _assert_grounded(result["candidates"], valid_sources)

    total_bullets = sum(len(v) for v in result["candidates"].values())
    print(
        f"[live smoke] generate_insights returned {total_bullets} grounded bullets "
        f"across {len(result['candidates'])} candidates via model={insights.MODEL}"
    )
