# MCP API Usability Improvements

## Summary

After extended usage of the qplaywright MCP tools for Qt application automation, several API usability issues were identified that add friction without providing corresponding value.

---

## Issues

### 1. `choose` has overly strict parameter requirements

**Severity:** Minor

**Description:** The `choose` tool requires exactly one of `value`, `index`, or `label` to be provided. In practice, selecting by label is often the most readable and maintainable approach, but the current validation logic makes it error-prone.

**Current behavior:**
```
choose(target="#role", label="Admin")  # May fail with "Exactly one of value, index, or label must be provided"
```

**Impact:** Users often fall back to using `index` which is less maintainable (brittle to option order changes).

---

### 2. `screenshot` returns base64 instead of a file path

**Severity:** Minor

**Description:** When capturing screenshots, the tool returns a large base64 string in the response. This is inconvenient for downstream processing.

**Current behavior:**
```json
{
  "data": "iVBORw0KGgoAAAANSUhEUgAAAz...",
  "width": 800,
  "height": 600
}
```

**Suggested improvement:** Either return a file path directly, or support a `save_to` parameter to specify where the screenshot should be written.

---

### 3. `snapshot` / `inspect` return information overload

**Severity:** Minor

**Description:** Even with a reasonable `depth` setting, the snapshot includes many internal/hidden widgets (e.g., `#qt_scrollarea_viewport`, `#qt_scrollarea_hcontainer`) that clutter the output and make it harder to find relevant UI elements.

**Current behavior:** A depth=4 snapshot of a form with a few visible fields returns 50+ widget entries, most of which are internal scroll containers.

**Suggested improvement:**
- Add a filter option like `include_hidden=false` (default) to exclude invisible/internal widgets
- Or provide a more structured response that groups visible controls separately from layout infrastructure

---

### 4. Missing wait/polling utilities

**Severity:** Minor

**Description:** After performing an action (e.g., clicking a button), verifying the result requires manually calling `inspect` or `snapshot` and then parsing the response to check for expected state.

**Current behavior:**
```python
click(target="#login_btn")
# Now need to poll or wait and re-inspect to verify login succeeded
snapshot(target="#status")
# Check if status text contains "Logged in"
```

**Suggested improvement:** A generic `wait_until` or `wait_for` function that accepts a condition and polls until it passes or times out.

---

### 5. Inconsistent return structures across window tools

**Severity:** Minor

**Description:** Window-related tools return different top-level keys:
- `window list` returns `{"windows": [...]}`
- `window resize` returns `{"active_window": {...}}`
- Other tools may vary

**Impact:** Forces users to remember specific response shapes rather than having a consistent pattern to follow.

---

### 6. Click/operation responses lack state verification

**Severity:** Minor

**Description:** Operations like `click` return success/failure status but don't indicate whether the underlying widget state actually changed. This is especially problematic for buttons that might be disabled.

**Current behavior:**
```json
{
  "ok": true,
  "count": 1,
  "target": "#login_btn"
}
```

**Suggested improvement:** Consider including a brief state indication for relevant operations, such as whether the button was enabled/disabled at click time.

---

## Test Scenario Used

The above observations came from a comprehensive test flow against a demo application that included:
- Form filling (username, password, notes)
- Checkbox toggles (remember me, notify, escalate)
- ComboBox selection (role, environment)
- Dialog operations (Review Payment dialog)
- Log verification and clearing
- Scroll operations

---

## Priority Recommendation

All issues are minor/usability-level. None block basic functionality. If addressed, items **#2** (screenshot path) and **#4** (wait utilities) would provide the most value to users.
