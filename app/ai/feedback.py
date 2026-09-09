"""Layer for section 16's feedback loop: a lightweight, explainable
"learn the user's preferences" mechanism rather than retraining a model.

Every 👍/👎 the user gives on a job match nudges the affinity of the
WORDS in that job's title (not the whole match score directly) up or
down. A later job whose title shares those words gets a small bonus or
penalty. This directly implements the spec's example - repeatedly
rejecting "Engineering Manager" while accepting "Principal Simulation
Architect" lowers the affinity of "engineering"/"manager" and raises
"principal"/"simulation"/"architect" - without needing a training
pipeline, GPU, or opaque model.
"""

from __future__ import annotations

from app.ai.scoring import title_tokens
from app.core.constants import FeedbackRating

_RATING_WEIGHT = {
    FeedbackRating.EXCELLENT.value: 2.0,
    FeedbackRating.GOOD.value: 1.0,
    FeedbackRating.NOT_INTERESTED.value: -1.0,
    FeedbackRating.POOR.value: -1.5,
    FeedbackRating.NEVER_SHOW_SIMILAR.value: -3.0,
}

# How much of a swing the learned affinity can apply to a job's
# user-preferences component score (itself only a 5% weight in the
# overall score by default - see DEFAULT_SCORE_WEIGHTS) - a strong
# influence on that one bucket, never enough to override hard filters
# or overwhelm the rest of the evidence-based scoring.
_MAX_BONUS = 15.0
_SCALE = 3.0


def compute_title_affinity(rated_titles: list[tuple[str, str]]) -> dict[str, float]:
    """`rated_titles` is a list of (rating, job_title) pairs, oldest to
    newest feedback the user has given so far."""
    affinity: dict[str, float] = {}
    for rating, title in rated_titles:
        weight = _RATING_WEIGHT.get(rating, 0.0)
        if weight == 0.0:
            continue
        for token in title_tokens(title):
            affinity[token] = affinity.get(token, 0.0) + weight
    return affinity


def learned_title_bonus(job_title: str, affinity: dict[str, float]) -> float:
    """Returns a bonus/penalty in [-15, 15] to add to a job's
    user-preferences score, or 0.0 when there's no relevant feedback
    history yet (never penalizes a job just because feedback is
    absent)."""
    if not affinity:
        return 0.0
    tokens = title_tokens(job_title)
    scores = [affinity[t] for t in tokens if t in affinity]
    if not scores:
        return 0.0
    average = sum(scores) / len(scores)
    return max(-_MAX_BONUS, min(_MAX_BONUS, average * _SCALE))


def never_show_similar_titles(rated_titles: list[tuple[str, str]]) -> set[str]:
    """Distinct title tokens the user has explicitly said "never show
    similar" for - exposed separately so callers can treat it as a
    stronger signal than the general affinity (e.g. surfacing it in the
    UI) even though it's already folded into `compute_title_affinity`."""
    tokens: set[str] = set()
    for rating, title in rated_titles:
        if rating == FeedbackRating.NEVER_SHOW_SIMILAR.value:
            tokens |= title_tokens(title)
    return tokens
