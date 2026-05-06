# Overlay Visual Feedback — Canonical Specification

This document is the **single source of truth** for all constants, colours, and animation parameters used by the overlay implementations in both the Python agent (`qplaywright/agent/_server.py`, implemented as `_AutomationOverlay` / `_OverlayManager`) and the C++ agent (`qplaywright/cpp/qplaywright_agent.h`).

When either implementation is changed, this document must be updated first and the other implementation must be aligned in the same commit.

---

## Widget Identity

| Name | Value | Purpose |
|------|-------|---------|
| `AUTOMATION_OVERLAY_OBJECT_NAME` | `"_qplaywright_automation_overlay"` | `QObject::objectName` used to exclude the overlay from selector queries |
| `AUTOMATION_OVERLAY_PROPERTY` | `"qplaywrightAutomationOverlay"` | Dynamic property set to `true` on the overlay widget — secondary exclusion guard |

---

## Layout Constants (px)

| Constant | Value | Description |
|----------|-------|-------------|
| `OVERLAY_EDGE_PADDING` | `3` | Gap between the overlay window edge and the drawn frame |
| `OVERLAY_FRAME_OUTSET` | `3` | How far the frame border extends outside the wrapped window rect |
| `OVERLAY_CORNER_RADIUS` | `6` | Rounded-corner radius of the frame rect |
| `OVERLAY_BADGE_GAP` | `3` | Vertical gap between the badge bottom and the frame top (non-maximised layout) |
| `OVERLAY_BADGE_LEFT_INSET` | `6` | Horizontal offset of the badge from the frame left edge (non-maximised layout) |
| `OVERLAY_BADGE_TOP_INSET` | `6` | Minimum gap between the badge and the frame top / target rect top (maximised layout) |
| `OVERLAY_BADGE_RADIUS` | `7` | Rounded-corner radius of the badge pill |

---

## Colours

### Frame (active-session outline)

| Role | RGBA | Notes |
|------|------|-------|
| Core / solid frame | `(20, 132, 255, 150)` | Base frame stroke colour |
| Glow pen (width 6) — stop 0.00 | `(0, 245, 255, 60)` | |
| Glow pen — stop 0.34 | `(20, 132, 255, 65)` | |
| Glow pen — stop 0.70 | `(255, 76, 196, 60)` | |
| Glow pen — stop 1.00 | `(0, 245, 255, 55)` | |
| Frame pen (width 2) — stop 0.00 | `(0, 245, 255, 185)` | |
| Frame pen — stop 0.34 | `(20, 132, 255, 150)` | = Core colour |
| Frame pen — stop 0.70 | `(255, 76, 196, 175)` | |
| Frame pen — stop 1.00 | `(0, 245, 255, 180)` | |

### Badge pill

| Role | RGBA |
|------|------|
| Background fill | `(9, 29, 61, 150)` |
| Border stroke | `(140, 228, 255, 135)` |
| Label text | `(255, 255, 255, 230)` |

### Cursor

| Role | RGBA |
|------|------|
| Shadow fill | `(0, 0, 0, 110)` |
| Arrow outline | `(0, 0, 0, 200)` |
| Arrow fill | `(255, 255, 255, 240)` |
| Core dot | `(20, 132, 255, 180)` |

### Click pulse ring

| Role | RGBA |
|------|------|
| Ring base | `(20, 132, 255, 220)` |
| Ring alpha at t=0 | 220 → fades linearly to 0 over `PULSE_SPAN` |

---

## Animation Parameters

| Parameter | Value | Unit | Notes |
|-----------|-------|------|-------|
| `PULSE_SPAN` | `220` | ms | Duration of one expanding ring |
| `PULSE_GAP` | `80` | ms | Delay between consecutive rings in a multi-pulse burst |
| `PULSE_CUTOFF` | `300` | ms | Pulse records older than this are discarded (`PULSE_SPAN + PULSE_GAP`) |
| Pulse start radius | `6` | px | |
| Pulse end radius | `26` | px | `6 + 20` |
| Timer interval | `16` | ms | ~60 fps repaint / sync tick |

---

## Invisible-Window Handling

| Situation | Behaviour |
|-----------|-----------|
| Target window hidden / minimised while active | Overlay is hidden immediately |
| Manager deactivated | Timer stopped, overlay hidden |
| Python `_sync()` tick — invisible target | Overlay is **dropped** (destroyed) to free resources |
| C++ `syncVisibility()` tick — invisible target | Overlay is kept but `setManagerActive(false)` (deferred cleanup via `QPointer` stale detection) |

> The Python and C++ strategies differ by design: Python uses garbage-collected objects and proactive cleanup; C++ uses `QPointer` for safe deferred cleanup and an event-filter for immediate response to `QEvent::Hide` / `QEvent::Close`.

---

## Event-Filter Coverage (C++ only)

The C++ `AutomationOverlayManager` installs itself as an event-filter on each tracked window. Python does not need this because the `_sync()` timer already handles repositioning.

| Event | Action |
|-------|--------|
| `Move`, `Resize`, `WindowStateChange`, `Show` | `syncToWindow()` (re-positions overlay) |
| `Hide`, `Close` | `setManagerActive(false)` (hides overlay) |
