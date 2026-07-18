-- ListingLens analytical SQL (DuckDB)
-- Build the warehouse first:  python -m scripts.build_duckdb
-- Open it:                    duckdb data/processed/listinglens.duckdb
--
-- Tables: reviews, product_metrics, product_summary, product_features,
--         topics, conversations, conversation_turns, conversation_intents

-- 1. Portfolio overview: reviews, rating, and negativity per product.
SELECT asin, total_reviews, avg_rating, pct_negative, pct_positive
FROM product_metrics
ORDER BY pct_negative DESC;

-- 2. Sentiment vs star rating — do low ratings actually carry negative language?
SELECT rating,
       COUNT(*)                     AS n_reviews,
       ROUND(AVG(compound_score),3) AS avg_compound,
       ROUND(AVG(is_negative),3)    AS share_negative
FROM reviews
GROUP BY rating
ORDER BY rating;

-- 3. Most complaint-heavy topics across the catalog (HIGH complaint level).
SELECT asin, label, count, pct_negative, complaint_level
FROM topics
WHERE complaint_level = 'HIGH'
ORDER BY pct_negative DESC
LIMIT 20;

-- 4. Support intent mix per product (what customers contact about).
SELECT asin, intent, count
FROM conversation_intents
ORDER BY asin, count DESC;

-- 5. Conversation operations: resolution & escalation by product.
SELECT asin,
       COUNT(*)                                          AS conversations,
       ROUND(AVG(CASE WHEN resolved  THEN 1 ELSE 0 END),3) AS resolution_rate,
       ROUND(AVG(CASE WHEN escalated THEN 1 ELSE 0 END),3) AS escalation_rate,
       ROUND(AVG(n_turns),2)                             AS avg_turns
FROM conversations
GROUP BY asin
ORDER BY escalation_rate DESC;

-- 6. Sentiment recovery: do interactions end better than they start?
SELECT asin,
       ROUND(AVG(sentiment_start),3) AS avg_start,
       ROUND(AVG(sentiment_end),3)   AS avg_end,
       ROUND(AVG(sentiment_delta),3) AS avg_recovery
FROM conversations
GROUP BY asin
ORDER BY avg_recovery;

-- 7. Where the trained model deferred to the LLM (low-confidence intents).
SELECT intent_source, COUNT(*) AS n,
       ROUND(AVG(intent_confidence),3) AS avg_confidence
FROM conversations
GROUP BY intent_source;

-- 8. Do products with more negative reviews also escalate more in support?
--    (review signal joined to conversation signal.)
SELECT m.asin,
       m.pct_negative,
       ROUND(AVG(CASE WHEN c.escalated THEN 1 ELSE 0 END),3) AS escalation_rate
FROM product_metrics m
JOIN conversations c USING (asin)
GROUP BY m.asin, m.pct_negative
ORDER BY m.pct_negative DESC;
