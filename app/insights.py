"""Grounded, cited candidate-comparison insights via OpenRouter (Claude Sonnet 4.5).

Hard rules (enforced via system prompt, see SYSTEM_PROMPT):
  1. Only claims traceable to the candidate JSON we pass in.
  2. Every bullet carries the source URL from that JSON.
  3. Neutral, nonpartisan, comparative tone -- never endorse or tell anyone how to vote.
  4. Explicitly say when data is missing ("has not taken a public position on X in our data").
  5. 2-3 bullets per candidate on "what this could mean for you", using whichever profile
     fields are present, plus a short "bottom line differences" paragraph and a caveats line.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

from openai import OpenAI

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
MODEL = "anthropic/claude-sonnet-4.5"

SYSTEM_PROMPT = """You are a nonpartisan voter-information assistant. You will be given:
  (1) a voter profile (may have missing fields -- only use fields that are present)
  (2) JSON data for ALL candidates in exactly one race, each candidate's data including
      finance figures, voting record, sponsored bills, and issue positions, each fact
      tagged with a "source" URL.

HARD RULES -- follow all of these exactly:
1. Only make claims that are directly traceable to the provided candidate JSON. Never use
   outside knowledge, never speculate about facts not present in the JSON.
2. Every bullet you write must carry the exact source URL string it is grounded in, taken
   verbatim from the JSON's "source" or "sources" fields.
3. Stay neutral and nonpartisan. Write in a comparative, informative tone. NEVER tell the
   voter who to vote for, NEVER rate candidates as better/worse overall, NEVER use
   endorsement language ("you should vote for", "the best choice", etc).
4. If a candidate's data does not cover a topic relevant to the voter profile, say so
   explicitly, e.g. "has not taken a public position on healthcare in our data" -- do not
   fill the gap with a guess.
5. For each candidate, write 2-3 bullets under "what this could mean for you", each bullet
   grounded in whichever profile fields (occupation, income bracket, age bracket, homeowner/
   renter, kids in public school, health coverage, veteran, small business owner, student)
   are actually present in the profile you were given -- do not invent profile fields.
   Then write one short "bottom line differences" paragraph comparing the candidates
   factually (no ranking/endorsement), and one short "caveats" line noting data gaps and
   that this is not exhaustive or an endorsement.

Respond with ONLY valid JSON (no markdown fences, no commentary) matching exactly this
shape:
{
  "candidates": {
    "<candidate_id>": [
      {"text": "<bullet text>", "source": "<source url>"},
      ...
    ]
  },
  "summary": "<bottom line differences paragraph>",
  "caveats": "<caveats line>"
}
"""


def _profile_lines(profile: dict[str, Any]) -> str:
    """Render only the present profile fields (never invent missing ones)."""
    if not profile:
        return "(no profile fields provided)"
    parts = []
    for key, value in profile.items():
        if value in (None, "", [], {}):
            continue
        parts.append(f"- {key}: {value}")
    return "\n".join(parts) if parts else "(no profile fields provided)"


def build_user_prompt(profile: dict[str, Any], race: dict[str, Any], candidates: dict[str, Any]) -> str:
    race_meta = {
        "race_id": race.get("race_id"),
        "office": race.get("office"),
        "level": race.get("level"),
        "district": race.get("district"),
        "context": race.get("context"),
    }
    return (
        "VOTER PROFILE (only use fields listed):\n"
        f"{_profile_lines(profile)}\n\n"
        "RACE:\n"
        f"{json.dumps(race_meta, indent=2)}\n\n"
        "CANDIDATE DATA (the ONLY source of facts you may use):\n"
        f"{json.dumps(candidates, indent=2)}\n\n"
        "Produce the JSON response now, following every hard rule in the system prompt."
    )


def _extract_json(raw: str) -> dict[str, Any]:
    """Defensively parse a JSON object out of a model response."""
    raw = raw.strip()
    # Strip ```json ... ``` or ``` ... ``` fences if present.
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", raw, re.DOTALL)
    if fence:
        raw = fence.group(1).strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    # Fall back to grabbing the outermost {...} block.
    start = raw.find("{")
    end = raw.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidate = raw[start : end + 1]
        return json.loads(candidate)
    raise ValueError("Could not parse JSON from model response")


def _candidate_source_urls(candidate: dict[str, Any]) -> set[str]:
    urls: set[str] = set()

    def add(value: Any) -> None:
        if isinstance(value, str) and value.strip():
            urls.add(value.strip())

    for source in candidate.get("sources") or []:
        add(source)

    finance = candidate.get("finance")
    if isinstance(finance, dict):
        add(finance.get("source"))

    record = candidate.get("record")
    if isinstance(record, dict):
        add(record.get("source"))
        for vote in record.get("key_votes") or []:
            if isinstance(vote, dict):
                add(vote.get("source"))

    for position in candidate.get("positions") or []:
        if isinstance(position, dict):
            add(position.get("source"))

    return urls


def _validate_candidate_bullets(parsed: dict[str, Any], candidates: dict[str, Any]) -> dict[str, list[dict[str, str]]]:
    raw_candidates = parsed.get("candidates")
    if not isinstance(raw_candidates, dict):
        raise ValueError("Model response missing candidates object")

    expected_ids = set(candidates)
    unexpected_ids = set(raw_candidates) - expected_ids
    if unexpected_ids:
        raise ValueError(f"Model response included unknown candidate ids: {sorted(unexpected_ids)}")

    allowed_sources = {
        cid: _candidate_source_urls(candidate if isinstance(candidate, dict) else {})
        for cid, candidate in candidates.items()
    }
    validated: dict[str, list[dict[str, str]]] = {}
    invalid: list[str] = []

    for cid in expected_ids:
        bullets = raw_candidates.get(cid)
        if not isinstance(bullets, list):
            invalid.append(f"{cid}: missing bullet list")
            continue

        kept: list[dict[str, str]] = []
        for idx, bullet in enumerate(bullets):
            if not isinstance(bullet, dict):
                invalid.append(f"{cid}[{idx}]: bullet is not an object")
                continue
            text = bullet.get("text")
            source = bullet.get("source")
            if not isinstance(text, str) or not text.strip():
                invalid.append(f"{cid}[{idx}]: missing text")
                continue
            if not isinstance(source, str) or source.strip() not in allowed_sources[cid]:
                invalid.append(f"{cid}[{idx}]: source not present in candidate JSON")
                continue
            kept.append({"text": text.strip(), "source": source.strip()})

        if not kept:
            invalid.append(f"{cid}: no valid sourced bullets")
        validated[cid] = kept

    if invalid:
        raise ValueError("; ".join(invalid[:8]))

    return validated


def generate_insights(
    profile: dict[str, Any],
    race: dict[str, Any],
    candidates: dict[str, Any],
    api_key: str,
) -> dict[str, Any]:
    """Call OpenRouter (Claude Sonnet 4.5) for a grounded, cited comparison.

    Returns {"candidates": {candidate_id: [{"text","source"}, ...]}, "summary": str, "caveats": str,
    "horizons": dict} -- "horizons" mirrors the cached-path shape (currently always {} on the live path).
    Raises ValueError on unparseable model output (caller maps to an HTTP error).
    """
    client = OpenAI(base_url=OPENROUTER_BASE_URL, api_key=api_key)
    user_prompt = build_user_prompt(profile, race, candidates)

    completion = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.3,
    )
    raw = completion.choices[0].message.content or ""
    parsed = _extract_json(raw)
    if not isinstance(parsed, dict):
        raise ValueError("Model response must be a JSON object")

    validated_candidates = _validate_candidate_bullets(parsed, candidates)

    # Defensive shape normalization. Bullets are validated against the
    # provided candidate JSON before anything can be returned or cached.
    result = {
        "candidates": validated_candidates,
        "summary": parsed.get("summary", "") if isinstance(parsed.get("summary"), str) else "",
        "caveats": parsed.get("caveats", "") if isinstance(parsed.get("caveats"), str) else "",
        "horizons": {},
    }
    return result
