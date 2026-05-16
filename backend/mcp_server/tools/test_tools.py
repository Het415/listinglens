"""Smoke tests for the 5 MCP tools.

Run: python -m backend.mcp_server.tools.test_tools

Tests are deliberately lightweight — they verify that each tool:
  - Loads without import errors
  - Returns a dict shaped like its Pydantic output model
  - Handles a known-good ASIN end-to-end

Heavier validation (LLM grounding quality, etc.) belongs in eval/.
"""
import sys
import traceback


def _ok(name: str) -> None:
    print(f"  \033[92mPASS\033[0m  {name}")


def _fail(name: str, err: Exception) -> None:
    print(f"  \033[91mFAIL\033[0m  {name}: {err}")
    traceback.print_exc()


def test_loader() -> bool:
    """Loader resolves repo paths and surfaces cached ASIN files."""
    try:
        from . import _loader
        feats = _loader.asin_features("B08XPWDSWW")
        assert "pct_negative" in feats, "features dict shape changed"
        df = _loader.asin_reviews_df("B08XPWDSWW", limit=10)
        assert len(df) > 0, "reviews df is empty"
        catalog = _loader.supported_asins()
        assert len(catalog) >= 12, "expected 12+ supported ASINs"
        mock = _loader.mock_market_data()
        assert "asin_to_category" in mock
        _ok("loader")
        return True
    except Exception as e:
        _fail("loader", e)
        return False


def test_return_risk() -> bool:
    """return_risk wraps src/fusion and returns the expected schema."""
    try:
        from .return_risk import predict_return_risk
        out = predict_return_risk("B08XPWDSWW")
        for key in ("asin", "risk_score", "risk_label", "risk_pct", "confidence", "explanation"):
            assert key in out, f"missing key {key}"
        assert out["risk_label"] in ("HIGH", "MEDIUM", "LOW")
        assert 0.0 <= out["risk_score"] <= 1.0
        _ok(f"return_risk (risk_label={out['risk_label']}, score={out['risk_score']:.2f})")
        return True
    except Exception as e:
        _fail("return_risk", e)
        return False


def test_competitor_search() -> bool:
    """competitor_search returns competitors for a known ASIN."""
    try:
        from .competitor import competitor_search
        out = competitor_search("B08XPWDSWW", max_results=3)
        assert out["asin"] == "B08XPWDSWW"
        assert out["category"] == "earbuds_tws"
        assert 0 < len(out["competitors"]) <= 3
        first = out["competitors"][0]
        for key in ("asin", "title", "brand", "price_usd", "rating", "review_count"):
            assert key in first, f"competitor missing {key}"
        _ok(f"competitor_search ({len(out['competitors'])} returned, top: {first['brand']} {first['title'][:40]})")
        return True
    except Exception as e:
        _fail("competitor_search", e)
        return False


def test_price_history() -> bool:
    """price_history synthesizes a 90-day curve from the seed."""
    try:
        from .price import price_history
        out = price_history("B010BWYDYA", days=90)
        assert out["asin"] == "B010BWYDYA"
        assert out["days"] == 90
        assert len(out["daily_prices"]) == 91  # 90 days walked back + today
        assert out["volatility"] in ("low", "medium", "high")
        # determinism: same input -> same curve
        out2 = price_history("B010BWYDYA", days=90)
        assert out["daily_prices"] == out2["daily_prices"], "curve is not deterministic"
        _ok(f"price_history (current=${out['current_price']}, range=${out['min_price_90d']}-{out['max_price_90d']}, vol={out['volatility']})")
        return True
    except Exception as e:
        _fail("price_history", e)
        return False


def test_trend_signal() -> bool:
    """trend_signal resolves both asin and category lookups."""
    try:
        from .trends import trend_signal
        out_by_asin = trend_signal(asin="B08RLW7918")
        assert out_by_asin["category"] == "security_camera"
        assert len(out_by_asin["values"]) == 12
        assert out_by_asin["trend_direction"] in ("rising", "falling", "flat")
        out_by_cat = trend_signal(category="security_camera")
        assert out_by_asin["values"] == out_by_cat["values"], "asin and category resolution diverge"
        _ok(f"trend_signal (security_camera, {out_by_asin['trend_direction']}, YoY {out_by_asin['yoy_change_pct']}%)")
        return True
    except Exception as e:
        _fail("trend_signal", e)
        return False


def test_review_qa() -> bool:
    """review_qa wraps the existing RAG. Requires GROQ_API_KEY in env."""
    import os
    if not os.getenv("GROQ_API_KEY"):
        print("  \033[93mSKIP\033[0m  review_qa (set GROQ_API_KEY to run this test)")
        return True
    try:
        from .review_qa import review_qa
        out = review_qa("B08XPWDSWW", "What are the top complaints in 1-star reviews?")
        for key in ("answer", "sources", "n_sources"):
            assert key in out, f"missing key {key}"
        assert len(out["answer"]) > 30, "answer suspiciously short"
        assert out["n_sources"] > 0, "no sources retrieved"
        _ok(f"review_qa (answer={len(out['answer'])} chars, {out['n_sources']} sources)")
        return True
    except Exception as e:
        _fail("review_qa", e)
        return False


def main() -> int:
    print("\nMCP tool smoke tests")
    print("-" * 50)

    results = [
        test_loader(),
        test_return_risk(),
        test_competitor_search(),
        test_price_history(),
        test_trend_signal(),
        test_review_qa(),
    ]

    print("-" * 50)
    passed = sum(results)
    total = len(results)
    if passed == total:
        print(f"\033[92m{passed}/{total} tests passed\033[0m")
        return 0
    print(f"\033[91m{passed}/{total} tests passed\033[0m")
    return 1


if __name__ == "__main__":
    sys.exit(main())
