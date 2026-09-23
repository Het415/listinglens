"""src/nlp_pipeline.py: import-time side effects and keyword categories."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import src.nlp_pipeline as nlp

ROOT = Path(__file__).resolve().parent.parent


def test_import_makes_no_hf_call_even_with_a_token(tmp_path):
    """Audit E-08: importing the module used to call huggingface_hub.login().

    That was a blocking `whoami` with no timeout on the production /analyze
    path, raising when HF was unreachable. A subprocess gives a clean import;
    offline mode turns any HF request into an immediate error, so a
    reintroduced login() fails this test instead of hanging it.
    """
    env = {
        **os.environ,
        "HF_TOKEN": "hf_dummy_token_for_test",
        "HF_HUB_OFFLINE": "1",
        "HF_HOME": str(tmp_path / "hf_home"),
        "PYTHON_DOTENV_DISABLED": "1",
        "PYTHONPATH": str(ROOT),
    }
    out = subprocess.run(
        [sys.executable, "-c", "import src.nlp_pipeline"],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=60,
    )
    assert out.returncode == 0, out.stderr[-2000:]
    assert not (tmp_path / "hf_home" / "token").exists(), "a token was written to HF_HOME"


# ── Keyword categories match whole words (audit E-03) ─────────────────────────

def _categories_hit(text: str) -> set[str]:
    lowered = text.lower()
    return {label for (label, _), pattern in zip(nlp.CATEGORY_KEYWORDS, nlp._CATEGORY_PATTERNS)
            if nlp._review_matches_keywords(lowered, pattern)}


@pytest.mark.parametrize("text", [
    "I have used it for a year",       # "ear" in "year"
    "Very happy with it",              # "app" in "happy"
    "The main benefit is obvious",     # "fit" in "benefit"
    "I can hear it from the kitchen",  # "ear" in "hear"
    "Bought it at the Apple store",    # "app" in "apple"
])
def test_substrings_inside_other_words_do_not_match(text):
    assert _categories_hit(text) == set()


@pytest.mark.parametrize("text, category", [
    ("My ears hurt after an hour", "Comfort & Fit"),
    ("The batteries died fast", "Battery Life"),
    ("It stopped charging", "Battery Life"),
    ("I returned it", "Customer Service"),
    ("Too many apps preinstalled", "Features & Usability"),
    ("They keep fitting loosely", "Comfort & Fit"),
    ("Constant lagging and buffering", "Performance & Speed"),
    ("Hard to set  up the first time", "Setup & Installation"),
])
def test_whole_words_and_their_inflections_match(text, category):
    assert category in _categories_hit(text)


@pytest.mark.parametrize("text", [
    "The sound quality is great",  # no longer counts as Build Quality
    "It supports 4K",              # no longer counts as Customer Service
    "Works great, easy to set up", # "works"/"easy" no longer count as Features
])
def test_reviewed_generic_words_no_longer_saturate(text):
    hit = _categories_hit(text)
    assert "Build Quality" not in hit
    assert "Customer Service" not in hit
    assert "Features & Usability" not in hit


def test_fire_stick_comfort_and_fit_is_no_longer_205_of_250():
    """The audit's worked example: 0 Fire Stick 4K reviews contain the word
    "ear", yet substring matching put 205/250 in Comfort & Fit."""
    summary = json.loads((ROOT / "data/processed/features_B07GZFM1ZM.json").read_text())["summary"]
    counts = {c["label"]: c["count"] for c in summary["categories"]}
    assert counts.get("Comfort & Fit", 0) < 50
