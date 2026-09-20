"""image_audit tool — Amazon main-image compliance checks for a listing's images.

A thin HTTP client to the `vislens` audit service. All of the image handling
lives there, deliberately: `requirements.txt:36-53` records why torch cannot
come back into this process, and the image encoder, the Pillow decode, and the
only code that dereferences a user-supplied URL all sit on the far side of that
boundary. This module holds a URL, a timeout, and a degradation contract.

**The degradation story is better than `competitor_search`'s**, and that is the
point of the split. If the service is cold-starting or down, what is lost is an
enhancement, not the answer — the agent still has five working tools, and this
one reports `unavailable` with a reason rather than raising. A run is never lost
to a cold sidecar.

Everything this returns is a *rule verdict*, computed deterministically from
published Amazon requirements. It is not a model judgement, and
`prompts.py` instructs the synthesizer not to re-derive or soften it.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

from pydantic import BaseModel, Field

# The service's own default port. Override in production.
DEFAULT_BASE_URL = "http://localhost:8100"

# Short on purpose. The audit is an enhancement to an answer the agent can
# already give, so waiting out a free-tier cold start (measured at 32-81s on
# this project's own hosting) would cost more than the finding is worth. A
# cold service degrades once and warms for the next request.
DEFAULT_TIMEOUT_S = 8.0


class ImageAuditInput(BaseModel):
    asin: str = Field(..., description="10-character ASIN of the seller's product")
    image_urls: list[str] | None = Field(
        None,
        description=(
            "Optional image URLs on an allowlisted Amazon CDN host. When "
            "omitted the service attempts a best-effort product-page read."
        ),
    )
    main_index: int | None = Field(
        None,
        description=(
            "Which supplied image is the MAIN image. Three of the checks are "
            "main-image-only rules; without this they are measured but not "
            "claimed as verdicts."
        ),
    )


class ImageAuditOutput(BaseModel):
    asin: str
    status: str = Field(..., description="ok | unavailable | blocked")
    reason: str = ""
    # Passed through from the service verbatim. Re-shaping it here would be a
    # second place for the verdict semantics to drift.
    audit: dict[str, Any] | None = None


def _base_url() -> str:
    return os.getenv("VISLENS_URL", DEFAULT_BASE_URL).rstrip("/")


def _timeout() -> float:
    try:
        return float(os.getenv("VISLENS_TIMEOUT_S", DEFAULT_TIMEOUT_S))
    except ValueError:
        return DEFAULT_TIMEOUT_S


def _get(path: str) -> tuple[dict[str, Any] | None, str]:
    """GET JSON from the audit service, returning (body, error_reason)."""
    request = urllib.request.Request(f"{_base_url()}{path}", method="GET")
    try:
        with urllib.request.urlopen(request, timeout=_timeout()) as response:
            return json.loads(response.read().decode()), ""
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            # The service's audit store is a bounded in-memory cache on a host
            # with no persistent disk, so a 404 here is ordinary rather than
            # exceptional — a restart or an eviction loses it.
            return None, "that audit is no longer cached; re-run the upload"
        return None, f"audit service returned HTTP {exc.code}"
    except urllib.error.URLError as exc:
        return None, f"audit service unreachable ({exc.reason})"
    except TimeoutError:
        return None, f"audit service timed out after {_timeout():g}s"
    except Exception as exc:  # noqa: BLE001
        return None, f"audit service call failed ({type(exc).__name__})"


def _post(path: str, payload: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
    """POST JSON, returning (body, error_reason).

    Uses urllib rather than requests so this adds no dependency to an image
    budget that has ~42 MiB of headroom.
    """
    request = urllib.request.Request(
        f"{_base_url()}{path}",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=_timeout()) as response:
            return json.loads(response.read().decode()), ""
    except urllib.error.HTTPError as exc:
        # 4xx carries a usable reason from the service; 5xx does not.
        try:
            detail = json.loads(exc.read().decode()).get("detail")
        except Exception:  # noqa: BLE001
            detail = None
        return None, f"audit service returned HTTP {exc.code}" + (f": {detail}" if detail else "")
    except urllib.error.URLError as exc:
        return None, f"audit service unreachable ({exc.reason})"
    except TimeoutError:
        return None, f"audit service timed out after {_timeout():g}s"
    except Exception as exc:  # noqa: BLE001
        return None, f"audit service call failed ({type(exc).__name__})"


def image_audit(
    asin: str,
    image_urls: list[str] | None = None,
    main_index: int | None = None,
    audit_id: str | None = None,
) -> dict:
    """Audit a listing's images against Amazon's published main-image rules.

    Three input paths, in precedence order:

    1.  `audit_id` — the seller already uploaded files through the UI, which
        posted them straight to the audit service. This is the best path: the
        seller said which image is the main one, so the main-image rules
        produce real verdicts instead of measurements. It also means image
        bytes never pass through this process.
    2.  `image_urls` — explicit CDN URLs.
    3.  the ASIN alone — a best-effort product-page read, which usually cannot
        identify the main image and therefore cannot produce those verdicts.

    Never raises. A missing or slow service is reported as `unavailable`, so a
    cold start costs the agent one finding rather than the whole run.
    """
    if audit_id:
        record, error = _get(f"/audit/{audit_id}")
        if record is None:
            return ImageAuditOutput(asin=asin, status="unavailable", reason=error).model_dump()
        # The detail record wraps the agent payload alongside per-image detail
        # and hashes; the agent wants only the payload.
        return ImageAuditOutput(
            asin=asin, status="ok", audit=record.get("payload")
        ).model_dump()

    payload: dict[str, Any] = {"main_index": main_index}
    if image_urls:
        payload["image_urls"] = image_urls
    else:
        payload["asin"] = asin

    body, error = _post("/audit/urls", payload)

    if body is None:
        return ImageAuditOutput(
            asin=asin,
            status="unavailable",
            reason=error,
        ).model_dump()

    # The service reports an Amazon bot challenge as `blocked`. That is an
    # expected outcome from a hosted client, not a failure, and the remedy is
    # for the seller to upload the files rather than for us to retry.
    if body.get("status") == "blocked":
        return ImageAuditOutput(
            asin=asin,
            status="blocked",
            reason=body.get("reason", "the product page could not be read"),
            audit={"remedy": body.get("remedy", "")},
        ).model_dump()

    return ImageAuditOutput(asin=asin, status="ok", audit=body).model_dump()


TOOL_NAME = "image_audit"
TOOL_DESCRIPTION = (
    "Check a listing's product images against Amazon's published main-image "
    "requirements: pure white background, product filling at least 85% of the "
    "frame, resolution and format, marks on the background, and duplicate "
    "images across the set. Returns deterministic rule verdicts with the "
    "measured value and the rule each was measured against - not a model "
    "judgement. Findings under 'f' are verdicts; findings under 'a' are "
    "measurements only and must not be reported as violations."
)


if __name__ == "__main__":  # pragma: no cover - CLI parity with the other tools
    import sys

    target = sys.argv[1] if len(sys.argv) > 1 else "B08XPWDSWW"
    print(json.dumps(image_audit(asin=target), indent=2)[:2000])
