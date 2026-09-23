"""Return-risk feature definitions shared by training (fusion.py) and serving
(nlp_pipeline.py).

Why this module exists
----------------------
The two sides used to compute the same-named features differently, and the
model was scoring products it had never been trained to see (audit E-01/E-02):

- `rating_avg` was the mean of the star-balanced review sample. ingest.py keeps
  50 reviews per star, so it was exactly 3.0 for every product, and the model's
  most-used split (the root of 60/100 trees) was fed a constant. It must be the
  product's real mean, which is in `raw_star_distribution`, captured before
  balancing.
- `rating_sentiment_gap` was `abs(avg_compound - (rating_avg/5 - 0.5))` in the
  training generator but `abs(rating_avg/5 - avg_positive_score)` at serving,
  unchanged since the first commit. The training formula is the one the proxy
  label is defined with, so it is the one kept.

Both definitions live here, once, so the parity test in
tests/test_fusion_parity.py can hold the two sides to the same function.

Pure Python on purpose: no numpy, pandas or model imports, so importing this
costs nothing on either side.
"""

from __future__ import annotations

import math
from typing import Mapping

# The model's inputs, in vector order. fusion.build_feature_vector and the
# served features dict both follow this list exactly.
#
# Four earlier inputs were dropped: rating_std, review_length_avg, n_topics
# and pct_outlier_reviews. The generator drew them uniformly, independent of
# the label, so the trees fit noise on them (126 splits); at serving three were
# constants and two were stale LDA-era values (audit MDL-03).
MODEL_FEATURES: tuple[str, ...] = (
    "avg_compound_score",
    "pct_negative",
    "pct_positive",
    "avg_positive_score",
    "avg_negative_score",
    "rating_avg",
    "rating_sentiment_gap",
)


def rating_stats(raw_star_distribution: Mapping[str, int] | Mapping[int, int]) -> tuple[float, float]:
    """Mean and population std of a product's real star ratings.

    `raw_star_distribution` maps star (1-5, as str or int) to review count, as
    written by ingest.get_reviews before balancing. Raises ValueError if it
    holds no reviews: silently falling back to the balanced sample is exactly
    the bug this replaces.
    """
    counts = {int(star): int(n) for star, n in raw_star_distribution.items()}
    total = sum(counts.values())
    if total <= 0:
        raise ValueError("raw_star_distribution has no reviews")
    mean = sum(star * n for star, n in counts.items()) / total
    variance = sum(n * (star - mean) ** 2 for star, n in counts.items()) / total
    return mean, math.sqrt(variance)


def rating_sentiment_gap(rating_avg: float, avg_compound_score: float) -> float:
    """How far review sentiment sits from what the star rating implies.

    Maps the 1-5 rating onto the compound-sentiment scale as `rating/5 - 0.5`
    and takes the absolute difference. This is the training generator's
    original definition, and the proxy label weights it at 0.2.
    """
    return abs(avg_compound_score - (rating_avg / 5 - 0.5))
