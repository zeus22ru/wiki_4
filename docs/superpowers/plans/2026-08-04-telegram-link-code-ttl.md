# Telegram link code TTL + reuse Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Unused Telegram link codes last 24 hours and are reused on repeated `create_telegram_link` calls until expired or used.

**Architecture:** Persist codes in existing SQLite `telegram_links`. Change default TTL to 86400. `create_telegram_link` returns an existing unused non-expired code for the user when present; otherwise creates a new one.

**Tech Stack:** Python, SQLite via `ChatHistoryManager`, pytest, Flask settings from `config.settings`.

## Global Constraints

- Default `TELEGRAM_LINK_CODE_TTL_SECONDS` = `86400`
- Do not refresh `expires_at` when reusing a code
- No new API routes or UI changes
- Existing verified bindings remain permanent (unchanged)

---

### Task 1: Reuse active code in `create_telegram_link`

**Files:**
- Modify: `core/chat_history.py` (`create_telegram_link`)
- Modify: `tests/test_telegram_integration.py`
- Modify: `config/settings.py` (default TTL)
- Modify: `.env.example`, `docs/telegram_bot_setup.md`

**Interfaces:**
- Consumes: `settings.TELEGRAM_LINK_CODE_TTL_SECONDS`, table `telegram_links`
- Produces: `create_telegram_link(user_id: int) -> dict` with keys `code`, `expires_at` (same shape as today)

- [x] **Step 1: Write the failing reuse test; adjust invalidation assertion**

Add:

```python
def test_telegram_link_reuses_active_code(monkeypatch):
    from core.chat_history import get_chat_history

    monkeypatch.setattr("config.settings.TELEGRAM_LINK_CODE_TTL_SECONDS", 300)
    chat_history = get_chat_history()
    user = _create_test_user()

    first = chat_history.create_telegram_link(user.id)
    second = chat_history.create_telegram_link(user.id)
    assert second["code"] == first["code"]
    assert second["expires_at"] == first["expires_at"]
```

In `test_telegram_link_code_generation`, replace the “инвалидация старого кода” block with: after verify/use of `result3` path — or expire the first code, then assert a new create yields a different code. Preferred: remove the mid-test “result3 != code” assertion; after verify of first unused path, create again and assert new code differs from used one. Concrete edit: delete lines that create `result3` expecting different code before verify; instead verify `code`, then:

```python
    result_after_use = chat_history.create_telegram_link(user.id)
    assert result_after_use["code"] != code
    verify = chat_history.verify_telegram_link(
        result_after_use["code"], telegram_user_id=111, telegram_username="tg_name"
    )
```

(Keep uniqueness across users assertions.)

- [x] **Step 2: Run reuse test — expect FAIL**

Run: `pytest tests/test_telegram_integration.py::test_telegram_link_reuses_active_code -v`  
Expected: FAIL (`second["code"] != first["code"]`)

- [x] **Step 3: Implement reuse + TTL default 86400**

In `create_telegram_link`, before invalidate/insert:

```python
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT code, expires_at
                FROM telegram_links
                WHERE user_id = ?
                  AND used_at IS NULL
                  AND expires_at > ?
                ORDER BY created_at DESC
                LIMIT 1
            ''', (user_id, now.isoformat()))
            existing = cursor.fetchone()
            if existing:
                return {"code": existing["code"], "expires_at": existing["expires_at"]}
            # ... existing invalidate + insert ...
```

Set default in `config/settings.py` to `"86400"`. Update `.env.example` and `docs/telegram_bot_setup.md` (24 hours; reuse instead of always invalidate).

- [x] **Step 4: Run telegram link tests**

Run: `pytest tests/test_telegram_integration.py -k telegram_link -v`  
Expected: all PASS

- [ ] **Step 5: Commit** (only if user asks)
