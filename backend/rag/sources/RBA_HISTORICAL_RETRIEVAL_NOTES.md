# RBA Historical Loader — Retrieval Quality Notes

## Load Summary
- **50 statements** loaded from rba.gov.au/media-releases (2022–present)
- **~140–280 chunks** in forex_documents (source=rba_historical)
- Chunk size: ~500 tokens (2000 chars), sentence-boundary aware

## Retrieval Test 1: "hawkish RBA statement inflation"
- **Expected:** 2022–2023 tightening cycle statements (rate hikes, inflation focus)
- **Results:** High similarity (0.69) — content about "Services price inflation", "central banks have eased policy", "commodity prices"
- **Assessment:** Relevant. Returns inflation-focused, tightening-era content.

## Retrieval Test 2: "RBA cutting rates dovish"
- **Expected:** Different set — dovish/pause/cut signals (2023–2024)
- **Results:** Similarity 0.60–0.61 — "extraordinary support is no longer needed", "return inflation to target", "underlying inflation continuing to decline"
- **Assessment:** Partially relevant. Some overlap with hawkish query; dovish/cutting semantics could be sharper. Different ranking than Query 1.

## Overall
- Retrieval distinguishes between hawkish (inflation/tightening) and dovish (target/cuts) intents.
- Results feel directionally accurate; some overlap due to shared vocabulary (inflation, target).
- Chunking at 500 tokens preserves context; no mid-sentence cuts observed.
