---
target: option-d-diadoc-tile-workspace.html
total_score: 21
max_score: 40
na_heuristics: 
p0_count: 2
p1_count: 2
timestamp: 2026-08-03T15-38-17Z
slug: plans-redisign-option-d-diadoc-tile-workspace-html
---
# Critique: Option D Diadoc tile workspace

## Design Health Score

| # | Heuristic | Score | Key Issue |
|---|-----------|-------|-----------|
| 1 | Visibility of System Status | 2 | Health/role visible; tab/action feedback goes to display:none notice |
| 2 | Match System / Real World | 3 | Strong Russian ops language; generic «Рабочее пространство» |
| 3 | User Control and Freedom | 2 | No sources/sidebar recovery ≤980/≤620; clear chats irreversible |
| 4 | Consistency and Standards | 2 | Tabs look real but don't switch panels; Источники button ≠ column behavior |
| 5 | Error Prevention | 1 | Clear-all unguarded; empty submit silent; no confirms |
| 6 | Recognition Rather Than Recall | 3 | History + labeled sources help; icon-only send; mid-width forces recall |
| 7 | Flexibility and Efficiency | 2 | Style + search + paste hint; no real accelerators |
| 8 | Aesthetic and Minimalist Design | 3 | Clean desktop Operate composition; chrome still busy |
| 9 | Error Recovery | 1 | No error UI; clear chats hides list with no restore |
| 10 | Help and Documentation | 2 | Sources blurb + composer tip; verify unexplained; hint hidden |
| **Total** | | **21/40** | **Acceptable — significant gaps before production** |

## Design Specificity Verdict

**LLM assessment:** Partially authored for БочкарИИ. Composition is product-specific (permanent sources rail, citation↔source coupling, ticket-shaped dialog titles, Russian ops copy, gold/sand/graphite shell). Still category-leaky: Segoe UI/Arial, generic H1, ChatGPT-shaped silhouette, default view hides the signature empty-state tiles. Identity lives in palette + sources column, not typography or empty-state ritual.

**Deterministic scan:** CLI `detect.mjs` returned `[]` (exit 0) — static HTML scan clean. Browser inject of `detect.js` found **20** runtime anti-patterns: low-contrast (3), undersized-ui-text (9), tiny-text (7), all-caps-body (1), line-length (1), overused-font (1), single-font (1). Detector caught contrast and 9–10px meta the LLM review flagged qualitatively.

**Visual overlays:** Injection succeeded during Assessment B; overlays were visible in the browser tab during that run. Console: `[impeccable] 20 anti-patterns found`. Live server stopped after assessment.

## Overall Impression

Desktop composition is the right Operate bet: dark answer + permanent sources + gold brand rail. The prototype undermines its own contract by hiding sources/sidebar without drawers, faking tab navigation, and CSS-killing the empty-state tiles that define Option D. Biggest opportunity: make the verify loop unreachable-never — sources always recoverable — and show empty vs populated as two honest states.

## What's Working

1. **Sources as desktop infrastructure** — 294px column + active card + citation rewrite embodies PRODUCT principle #1 (verifiable answers).
2. **Answer card as trust focal** — graphite panel vs neutral user bubble correctly elevates the decision artifact under ticket pressure.
3. **Brand rail + gold primary** — «БОЧКАРИИ», sand active dialog, gold CTA/tab underline read as intentional Diadoc-adjacent corporate UI.

## Priority Issues

### P0 — Sources vanish ≤980 with no drawer
- **Why:** Verification is the product. At common laptop widths the trust loop breaks; «Источники (3)» invites a dead `scrollIntoView` on `display:none`.
- **Fix:** Overlay/drawer with close, Escape, focus restore; wire Источники + citations to open/focus. Never hide without replacement.
- **Suggested command:** `$impeccable adapt`

### P0 — Sidebar vanishes ≤620 with no toggle
- **Why:** History/new chat/search are the agent's working set; silent disappearance strands the primary persona.
- **Fix:** Keyboard-accessible drawer/toggle; workspace full-width; sources remain drawer fallback (matches implementation plan).
- **Suggested command:** `$impeccable adapt`

### P1 — Tabs fake-navigate (docs/admin never shown)
- **Why:** Undermines “one work contour”; teaches users the chrome is lying.
- **Fix:** Show real panel stubs OR honest disabled state — do not mutate hidden titles as success.
- **Suggested command:** `$impeccable shape` / `$impeccable clarify`

### P1 — Default/new-chat never surfaces empty tiles
- **Why:** Signature Option D empty state is authored then CSS-killed; «+ Новый чат» leaves populated chat on screen.
- **Fix:** Toggle visibility: empty/new → tiles; populated → chat. New chat clears messages and reveals tiles.
- **Suggested command:** `$impeccable onboard` / `$impeccable distill`

### P2 — System typography + unlabeled send + undersized meta
- **Why:** Weakens specificity; «↑» fails recognition; 9–10px source meta fails AA usability; gold-on-white CTA ~3.4:1.
- **Fix:** Commit a Russian-capable UI font; label send; bump meta to ≥12px; darken gold or use dark text on gold for AA.
- **Suggested command:** `$impeccable typeset` + `$impeccable audit`

## Persona Red Flags

**Alex (tech-support under ticket pressure):** Mid-width cannot verify sources; fake admin/docs tabs waste clicks; clear-all unguarded; no keyboard accelerators.

**Jordan (first-timer):** Empty-state tiles invisible; «Проверить ответ» unexplained; tab clicks change nothing visible; send is arrow-only.

**Sam (a11y):** Sources/sidebar removed from a11y tree at breakpoints; live-region notice is display:none; unlabeled send; 9–10px meta and sand-on-dark citation need contrast QA.

## Minor Observations

- Mint unused in default (tiles hidden) — fine per contract.
- Status green off-palette but readable.
- Three equal-weight answer action pills — promote one primary.
- Composer paste-screenshot hint is excellent; attachment UI absent.
- Demo handlers update hidden `#notice` = false interactive completeness.
- `overused-font`/`single-font` may partly be environment resolving Segoe→Arial.

## Questions to Consider

1. If sources cannot stay visible under 980px, should «Источники (3)» open a full-width verify sheet rather than scroll to a ghost column?
2. Is the Diadoc tile empty state the brand moment, or is dark answer + sources rail the real brand — and should the default prototype lead with the latter?
3. What would «Проверить ответ» mean in one sentence so Alex trusts the answer in under 10 seconds?
4. Should «База знаний» / «Админка» live as tabs for non-admin agents, or collapse to overflow so chat stays ruthless?
