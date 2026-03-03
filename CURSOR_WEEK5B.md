Read CURSOR.md before making any changes.

## Task: Week 5B — Pattern RAG Retrieval Activation

## PREREQUISITE: Do NOT run this prompt until:

## pattern_outcomes table has 100+ resolved rows

## \_is_pattern_rag_ready() returns True (enforced in code)

## Week 5A has been running successfully for 4+ weeks

### Objective

Activate Pattern RAG retrieval in TechnicalAgent.
Use accumulated historical pattern memory to influence
quality scoring only — not direction, not setup name.
System must remain safe, non-biased, and distribution-verified.

---

### What to change

File: backend/rag/retriever.py (add retrieve_similar_patterns)
File: backend/agents/technical_agent.py (add RAG block + gate)

### STRICT Do NOT touch

- graph.py — no changes whatsoever
- ForexState — no changes whatsoever
- coach_agent.py — no changes whatsoever
- macro_agent.py — no changes whatsoever
- journal_agent.py — no changes whatsoever
- signal_agent.py — no changes whatsoever
- calculate_indicators() — do not modify
- detect_structure() — do not modify
- analyse_timeframes() — do not modify
- calculate_levels() — do not modify
- embed_and_store_pattern() — do not modify
- build_pattern_text() — do not modify
- Any gating logic in CoachAgent
- Direction logic — RAG cannot change BUY/SELL decision

TechnicalAgent output schema must remain exactly:
{ setup: str, direction: "BUY"|"SELL"|"NEUTRAL", quality: float 0-1 }

---

### Step 1 — Add configurable constants to retriever.py

File: backend/rag/retriever.py

Add these constants at the TOP of the file before any functions:

# ─────────────────────────────────────────────────────────────

# Pattern RAG Configuration

# DO NOT auto-adjust these values in code.

# Only change manually after reviewing pattern data at scale.

#

# Threshold evolution plan (change manually when data allows):

# 100 patterns → 0.75 (current default)

# 250 patterns → 0.78

# 500 patterns → 0.80

# 1000 patterns → 0.82–0.85

#

# As dataset grows, similarity becomes STRICTER not looser.

# This increases moat depth and prevents weak match influence.

# ─────────────────────────────────────────────────────────────

PATTERN_SIMILARITY_THRESHOLD: float = 0.75
MIN_SIMILAR_PATTERNS: int = 3

Rules for these constants:

- Never programmatically lower PATTERN_SIMILARITY_THRESHOLD
- Never auto-adjust based on result count
- If fewer than MIN_SIMILAR_PATTERNS results found above threshold
  → return found=False, do not lower threshold to get more results
- Only a human reviewing 200+ patterns should change these values
- Type annotations required on constants

---

### Step 2 — Add retrieve_similar_patterns() to retriever.py

File: backend/rag/retriever.py

Add this function:

def retrieve_similar_patterns(
pair: str,
direction: str,
pattern_text: str,
limit: int = 5
) -> dict:
"""
Retrieves historically similar patterns from pattern_outcomes
using pgvector cosine similarity.

    Only retrieves resolved patterns above PATTERN_SIMILARITY_THRESHOLD.
    Returns performance summary only — not raw pattern rows.
    Never influences direction or setup name.
    Only quality score can be adjusted by caller.

    Args:
        pair:         currency pair e.g. "GBP/JPY"
        direction:    "BUY" or "SELL"
        pattern_text: current pattern description to match against
        limit:        max candidates to retrieve before threshold filter

    Returns:
    {
        "found":           bool,
        "count":           int,
        "win_rate":        float | None,
        "avg_pips":        float | None,
        "sample_outcomes": list[str],
        "retrieval_note":  str,
        "threshold_used":  float
    }
    """

Implementation rules:

1. Embed pattern_text using OpenAI text-embedding-ada-002
   Get OPENAI_API_KEY from environment — never hardcode
   If embedding fails: log warning, return found=False dict

2. Query pattern_outcomes:
   SELECT \*, 1 - (embedding <=> {query_embedding}) as similarity
   FROM pattern_outcomes
   WHERE outcome IS NOT NULL
   AND embedding IS NOT NULL
   AND pair = {pair}
   AND direction = {direction}
   ORDER BY similarity DESC
   LIMIT {limit}

3. Filter results by threshold AFTER retrieval:
   filtered = [r for r in results
   if r["similarity"] > PATTERN_SIMILARITY_THRESHOLD]

   Log threshold filtering:
   logging.info(
   f"Pattern RAG {pair}: {len(results)} candidates retrieved, "
   f"{len(filtered)} above threshold {PATTERN_SIMILARITY_THRESHOLD}"
   )

4. Check minimum patterns:
   if len(filtered) < MIN_SIMILAR_PATTERNS:
   logging.info(
   f"Pattern RAG {pair}: only {len(filtered)} matches above "
   f"threshold {PATTERN_SIMILARITY_THRESHOLD} "
   f"(minimum {MIN_SIMILAR_PATTERNS} required) — skipping"
   )
   return {
   "found": False,
   "count": 0,
   "win_rate": None,
   "avg_pips": None,
   "sample_outcomes": [],
   "retrieval_note": "Insufficient high-similarity matches",
   "threshold_used": PATTERN_SIMILARITY_THRESHOLD
   }

5. Calculate performance from filtered results only:
   wins = count where outcome = "win"
   losses = count where outcome = "loss"
   win_rate = wins / len(filtered)
   avg_pips = average of pips_result values

6. Build sample_outcomes list (last 3):
   Format each as: "win +43 pips" or "loss -21 pips"

7. Build retrieval_note plain English:
   Example:
   "3 of 5 similar GBP/JPY BUY setups were winners (60%),
   averaging +20 pips. Recent: win, loss, win.
   Similarity threshold: 0.75."

8. Return full dict with found=True

Additional rules:

- If Supabase query fails: log warning, return found=False
- NEVER crash TechnicalAgent — always return dict
- Always include threshold_used in return for auditability
- Type hints required
- Use logging module not print()

---

### Step 3 — Add \_is_pattern_rag_ready() to technical_agent.py

File: backend/agents/technical_agent.py

Add this function before the main agent function:

def \_is_pattern_rag_ready() -> bool:
"""
Checks if pattern_outcomes has sufficient quantity
AND distribution before activating RAG retrieval.

    Both checks are mandatory.
    Count alone is not enough — distribution prevents bias.

    Distribution requirement:
    - 20+ wins AND 20+ losses required
    - Prevents self-reinforcing bias from skewed datasets
    - If all wins: quality floor would permanently inflate
    - If all losses: quality ceiling would permanently deflate

    Returns:
        bool: True only if count >= 100 AND distribution verified
    """
    try:
        result = supabase.table("pattern_outcomes").select(
            "id", "outcome", count="exact"
        ).not_.is_("outcome", "null").not_.is_(
            "embedding", "null"
        ).execute()

        count = result.count or 0

        # Gate 1 — minimum count
        if count < 100:
            logging.info(
                f"Pattern RAG not ready: {count}/100 patterns stored. "
                f"Continue trading to build history."
            )
            return False

        # Gate 2 — distribution check
        # Count alone is not sufficient — verify spread of outcomes
        rows = result.data or []
        wins = sum(1 for r in rows if r.get("outcome") == "win")
        losses = sum(1 for r in rows if r.get("outcome") == "loss")

        if wins < 20 or losses < 20:
            logging.warning(
                f"Pattern RAG not ready: insufficient distribution. "
                f"wins={wins} losses={losses}. "
                f"Require 20+ wins AND 20+ losses before activation. "
                f"Skewed dataset would bias quality scores permanently."
            )
            return False

        logging.info(
            f"Pattern RAG ready: {count} patterns verified. "
            f"Distribution: {wins} wins, {losses} losses. "
            f"Activating retrieval."
        )
        return True

    except Exception as e:
        logging.warning(
            f"Pattern RAG readiness check failed: {e} — "
            f"defaulting to False (safe)"
        )
        return False

---

### Step 4 — Update TechnicalAgent to use Pattern RAG

File: backend/agents/technical_agent.py

After Week 4 calculate_levels block and before LLM call:

1. Check readiness gate:
   rag_ready = \_is_pattern_rag_ready()

2. If rag_ready = True:
   Build current pattern text:
   current_pattern_text = build_pattern_text(
   signal_data={
   "pair": pair,
   "direction": structure.get("structure_bias", "unknown"),
   "setup": "pending",
   "session": current_session,
   "entry_price": levels.get("entry_price") if levels else None,
   "stop_loss": levels.get("stop_loss") if levels else None,
   "take_profit": levels.get("take_profit") if levels else None,
   "risk_reward": levels.get("risk_reward_ratio") if levels else None
   },
   technical_context={
   "indicators": indicators,
   "structure": structure,
   "mtf": mtf
   }
   )

   Retrieve similar patterns:
   similar = retrieve_similar_patterns(
   pair=pair,
   direction=structure.get("structure_bias", "NEUTRAL"),
   pattern_text=current_pattern_text
   )

3. If rag_ready = False:
   similar = {"found": False}
   Skip retrieval entirely

4. If similar["found"] = True:
   Add fifth block to LLM prompt after Week 4 levels block:

--- HISTORICAL PATTERN PERFORMANCE (Pattern RAG) ---
Similar past setups found: {similar["count"]}
Similarity threshold used: {similar["threshold_used"]}
Historical win rate: {similar["win_rate"]\*100:.0f}%
Average pips result: {similar["avg_pips"]:.1f} pips
Recent outcomes: {", ".join(similar["sample_outcomes"])}
Summary: {similar["retrieval_note"]}

---

5. If similar["found"] = False:
   Do NOT add the block
   Do NOT mention Pattern RAG to LLM
   System continues exactly as Week 4

6. Add quality adjustment rules to LLM system prompt:
   "If and only if the HISTORICAL PATTERN PERFORMANCE block
   is present above, apply these quality adjustments:

   win_rate > 0.65:
   Quality floor rises by 0.05.
   You may not score below (your calculated quality + 0.05).

   win_rate < 0.40:
   Quality ceiling drops by 0.10.
   You may not score above (your calculated quality - 0.10).

   win_rate 0.40-0.65:
   No quality adjustment. Score normally.

   HARD CONSTRAINTS — never violate:
   - You cannot change direction based on historical data
   - You cannot change setup name based on historical data
   - Quality score adjustment is the ONLY allowed influence
   - If no historical block is present, ignore all rules above
   - These adjustments apply to quality only, not CoachAgent gate"

---

### Step 5 — Verify nothing is broken

After implementation confirm ALL of the following:

Readiness gate:

- \_is_pattern_rag_ready() returns False when count < 100 ✅
- \_is_pattern_rag_ready() returns False when wins < 20 ✅
- \_is_pattern_rag_ready() returns False when losses < 20 ✅
- \_is_pattern_rag_ready() returns True only when all conditions met ✅
- Exception in gate → returns False safely ✅

Threshold enforcement:

- Results below PATTERN_SIMILARITY_THRESHOLD filtered out ✅
- Fewer than MIN_SIMILAR_PATTERNS → found=False returned ✅
- Threshold never auto-lowered in code ✅
- threshold_used always in return dict ✅

Quality influence:

- win_rate > 0.65 → quality floor +0.05 confirmed ✅
- win_rate < 0.40 → quality ceiling -0.10 confirmed ✅
- Direction unchanged regardless of historical data ✅
- Setup name unchanged regardless of historical data ✅

Failure safety:

- Break OPENAI_API_KEY → found=False → no RAG block ✅
- Break Supabase → found=False → no RAG block ✅
- System generates signals normally in all failure cases ✅

Schema:

- TechnicalAgent output exactly { setup, direction, quality } ✅
- @observe decorators present on all agent files ✅
- graph.py untouched ✅
- Type hints on all new functions ✅
- logging used not print() ✅
- No secrets hardcoded ✅

---

### Threshold evolution reminder

Document this in retriever.py comment block.
Do not implement in code — manual change only:

Current: 0.75 (activate at 100 patterns)
Next: 0.78 (raise manually at 250 patterns)
Then: 0.80 (raise manually at 500 patterns)
Then: 0.82 (raise manually at 1000 patterns)

Check current pattern count before raising:
SELECT COUNT(\*) FROM pattern_outcomes
WHERE outcome IS NOT NULL
AND embedding IS NOT NULL;

---

### Success criteria

Week 5B is complete when:

1. \_is_pattern_rag_ready() enforces count AND distribution ✅
2. retrieve_similar_patterns filters by 0.75 threshold ✅
3. Fewer than 3 matches above threshold → found=False ✅
4. Quality influenced only when win_rate outside 40-65% ✅
5. Direction never influenced by historical data ✅
6. System identical to Week 4 when gate returns False ✅
7. All failure modes return found=False gracefully ✅

### Save this prompt

Store as: /forexmind/CURSOR_WEEK5B.md
Activate only when Supabase confirms:

- COUNT >= 100
- wins >= 20
- losses >= 20
  \_is_pattern_rag_ready() will enforce this automatically.
  Manual SQL verification is optional but recommended.
