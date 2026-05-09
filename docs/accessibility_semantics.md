# Accessibility Semantics for Agent-Friendly Qt UIs

This document defines how Qt accessibility metadata should be used to improve
QPlaywright's ability to understand, locate, and operate complex QWidget UIs.

It is specifically aimed at applications with one or more of these traits:

- custom-painted controls whose visible labels are not exposed through `text()`
- icon-only controls
- composite widgets with rich domain behavior
- softtool or ribbon-like business menus whose semantics are not recoverable
  from the widget tree alone

The immediate motivation is simple: if a control's meaning only exists in
painting code, the automation layer can click it but cannot reliably understand
what it represents. That is not sufficient for MCP-driven agents.

## Goals

This document targets four outcomes:

1. make widget snapshots understandable to an agent without OCR or image
   heuristics
2. make selector matching work for custom-painted or icon-only controls
3. keep business semantics explicit instead of overloading generic UI actions
4. preserve a clean separation between accessibility text and structured
   domain APIs

## Non-Goals

This document does not propose:

- replacing explicit method metadata with accessibility text
- introducing compatibility aliases for legacy selector forms
- inferring business actions from screenshots or pixel analysis
- encoding complex structured state entirely inside accessibility strings

## Qt Accessibility Fields

### accessibleName

`QWidget::accessibleName` is the primary short name announced by assistive
technologies.

Qt's intended usage makes it a strong fit for automation understanding when a
widget does not expose meaningful visible text through normal Qt APIs.

Use it for:

- icon-only buttons
- custom-painted buttons
- painter-drawn softtool entries
- controls whose visual meaning is obvious to a human but not represented in
  the widget API

Good examples:

- `功率扫描`
- `扫描`
- `点数`
- `开始测量`
- `Delete trace`

Bad examples:

- full sentences
- localized help text mixed with state
- opaque identifiers such as `btn_7`

### accessibleDescription

`QWidget::accessibleDescription` is a short explanatory description for
assistive technologies.

It should add context, not replace the name.

Use it for:

- what the control does
- what domain action it triggers
- contextual hints that are not obvious from the short name alone

Good examples:

- `切换测量类型为功率扫描`
- `打开扫描参数页`
- `确认并启动当前测量`
- `Delete the selected trace from the active channel`

Bad examples:

- full documentation paragraphs
- raw JSON
- unstable runtime blobs with too much state

### accessibleIdentifier

Qt 6.9 introduced `QWidget::accessibleIdentifier`, and Qt explicitly describes
it as suitable for identifying widgets in automated tests.

This is the right long-term place for a stable automation identifier.

However, the current primary C++ environment for this repository is Qt 5.14.2,
so this field cannot be relied upon as the main contract today.

For current codebases:

- use `objectName` or explicit metadata for stable identifiers now
- plan for `accessibleIdentifier` as the future stable automation key on Qt 6.9+

## Evaluation Summary

### Short Answer

`accessibleName` and `accessibleDescription` should absolutely be used.

They are not the complete solution, but they are the highest-leverage way to
make custom-painted Qt controls legible to QPlaywright and MCP agents.

### What They Solve Well

- turning non-text controls into understandable snapshot entries
- making custom-painted controls selectable without image analysis
- giving agents a semantic description for planning and disambiguation
- improving live debugging, inspect output, and browser-style snapshots

### What They Do Not Solve

- structured domain state
- method discovery
- precise business workflows
- stable, non-localized test identifiers across language packs

Those concerns still belong to explicit widget metadata and invokable methods.

## Recommended Semantic Stack

These mechanisms should not compete with each other. They should form a clear
layered contract.

### Layer 1: Stable identity

Use one of these for machine-stable identification:

- `objectName`
- explicit widget metadata
- `accessibleIdentifier` when Qt 6.9+ is available

### Layer 2: Human-readable semantics

Use these for agent understanding and operator readability:

- `accessibleName`
- `accessibleDescription`

### Layer 3: Structured business behavior

Use `qplaywrightClassMetadata` and `invoke()`-style methods for:

- structured state reads
- explicit business actions
- composite widget operations
- value setting that should not be modeled as generic `fill()`

This repository already uses that direction for custom widgets and should keep
going that way.

## Proposed QPlaywright Contract

### Text Field Definition

In QPlaywright, `text` has one meaning only: the widget's real visible text as
exposed by the widget's own native text-bearing API.

`text` is not a generic "best available label" field.

The following must not be collapsed into `text`:

- `accessibleName`
- `accessibleDescription`
- `currentText`
- `value`
- `windowTitle`
- `placeholderText`
- `toolTip`

Each of those concepts has its own semantics and must remain a separate field
when surfaced.

Consequences:

- a custom-painted control with no native visible text must not gain a fake
  `text` field
- a combobox's `currentText` must remain `currentText`, not be rewritten as
  `text`
- a container title or window title must remain a title field, not become
  `text`
- accessibility metadata must remain accessibility metadata

This keeps selectors, inspect output, and snapshots semantically stable.

### Truthful Serialization Principle

Widget serialization must faithfully reflect the UI's actual structure and the
widget's actual capabilities.

Serialization must not invent a uniform schema by attaching fields that the
widget does not naturally provide.

Examples of forbidden distortion:

- adding `text` to a custom-painted control that has no visible text API
- rewriting `currentText`, `value`, or `windowTitle` as `text`
- rewriting `accessibleName` as `text`
- adding `checked` to a widget that is not checkable
- adding `value` to a widget that does not expose a value-bearing state

Examples of required preservation:

- `checked: false` on a checkable control
- `currentIndex: 0` on an index-bearing control
- an empty child list only when the representation layer explicitly chooses to
  expose children as a complete structural field

This principle is stricter than generic sparse serialization. The goal is not
to minimize keys at any cost. The goal is to serialize only real properties,
while preserving real state even when that state is `false`, `0`, or another
falsy value.

Rationale:

- preserves the true shape of the UI
- avoids fake cross-widget uniformity
- keeps valid state distinguishable from absence of capability
- reduces token consumption without sacrificing semantic correctness

Examples:

An icon-only button with no visible text:

```json
{"class": "QToolButton", "objectName": "scan_btn", "accessibleName": "功率扫描", "visible": true, "enabled": true}
```

A standard push button:

```json
{"class": "QPushButton", "text": "Login", "objectName": "login_btn", "visible": true, "enabled": true}
```

A checkable control:

```json
{"class": "QCheckBox", "text": "Remember me", "objectName": "remember", "visible": true, "enabled": true, "checked": false}
```

Fields such as `text`, `accessibleName`, `accessibleDescription`, `checked`,
`value`, `currentText`, `currentIndex`, and `windowTitle` should appear only
when they are real properties of the widget and carry real information.

Falsy but meaningful state must be preserved. For example:

- `checked: false` is real state and must not be dropped
- `currentIndex: 0` is real state and must not be dropped

Absent fields mean either the widget does not expose that capability or the
chosen representation layer does not surface it. They must not be created to
make unrelated widget types look uniform.

### Progressive Disclosure

QPlaywright should expose UI data from broad to narrow scope and from coarse to
fine detail.

The layers are:

1. widget tree or snapshot scope: broad, fast, coarse-grained understanding
2. target inspect scope: narrow, capability-aware, fine-grained detail
3. explicit method metadata: domain-specific structured behavior

These layers should become more detailed as scope narrows. They should not all
be forced into the same key set.

### Snapshot Rendering

Snapshot text should prefer real visible text first.

When no visible text exists but `accessibleName` does, the snapshot should show
that name and mark it as accessibility-derived.

Recommended rendering style:

```text
- QToolButton "Start"
- MenuButton "功率扫描" [a11y] @w12 ~#measure_type_btn
```

This avoids pretending that an accessibility label is visible widget text while
still making the control understandable.

Snapshot rendering is allowed to choose one human-readable label for display,
but that display choice does not redefine the underlying fields. A rendered
label derived from `accessibleName` remains accessibility-derived and must stay
distinct from raw `text` semantics.

The snapshot line is a rendered view for human and agent consumption. It is not
the raw widget node. Rendering may choose the most useful human-readable label,
but it must not rewrite the underlying widget data model by turning
`accessibleName` into `text`.

The `[a11y]` marker should coexist with other existing snapshot markers such as
`[active]`, compact handle markers like `@w12`, compact selector hints like
`~#measure_type_btn`, and transparency hints such as `!transparent` on the same
line. Snapshot parsers should treat bracket markers and compact suffix markers
as additive entry metadata.

### Inspect Output

`inspect` should return a capability-aware detailed view of the target widget.
There is no fixed universal field set shared by all widget types.

Common fields include:

- `text` — only when visible text exists
- `accessibleName` — only when set
- `accessibleDescription` — only when set
- `currentText` — only for controls that expose a current text state
- `objectName` — only when non-empty
- `visible`, `enabled` — always present (fundamental state)
- `checked` — only for checkable controls
- `value` — only for value-bearing controls
- `windowTitle` — only for title-bearing widgets when relevant
- `bounding_box` — only when requested or relevant
- `methods` — only when `include_methods=true` and the widget exposes methods

This gives the agent a compact, truthful view of the widget's capabilities
without wasting context on fields the widget does not support.

`inspect` should be more detailed than a tree snapshot, but it must still stay
truthful to the widget's real capabilities. It should not pad missing
capabilities with placeholder fields.

### Selector Extensions

Add explicit selector forms instead of overloading `text=` further.

Selector semantics are:

- `text=` matches only real visible text
- `a11y-name=` matches only `accessibleName`
- `a11y-desc=` matches only `accessibleDescription`

Recommended additions:

- `a11y-name=...`
- `a11y-desc=...`
- optional future alias `aid=...` for `accessibleIdentifier`

These selectors should be atomic, consistent with the current selector model,
and available in both Python and C++ agents.

### MCP Surface

The MCP snapshot and inspect tools should surface accessibility semantics
without requiring any special debug mode.

Recommended behavior:

- snapshot output includes accessibility-derived names when visible text is absent
- inspect returns raw accessibility fields explicitly
- tool documentation explains when to prefer `a11y-name=` over `text=`

## Authoring Guidance for Application Teams

### When to Set accessibleName

Set `accessibleName` whenever the control's meaning is not already exposed by a
standard Qt text-bearing API.

This includes:

- custom-painted buttons
- tool buttons represented only by icons
- softtool entries drawn in `paintEvent()`
- composite widgets whose visual caption is external to the control itself

Do not rely on the agent discovering painter text later. If the meaning matters
to a user, it should exist as data.

### When to Set accessibleDescription

Set `accessibleDescription` when a short name is not enough for correct action
selection.

Examples:

- two controls both named `扫描`, but one opens configuration and the other
  starts execution
- a menu entry whose business consequence matters more than its visual label
- a control whose label is terse but whose effect is domain-critical

### Localization Rules

Both `accessibleName` and `accessibleDescription` should be localized, just like
visible UI strings.

That means they are good for agent understanding and operator-facing snapshots,
but not ideal as the only stable automation identifier.

### Stability Rules

Use these rules:

- `accessibleName` should be concise and stable within one UI language
- `accessibleDescription` should be stable in meaning, not overloaded with
  transient state
- neither field should embed long dynamic status payloads

## Relationship to Custom Widget Metadata

Accessibility metadata and custom widget metadata serve different purposes.

### Accessibility metadata answers

- what is this control called?
- what does it roughly do?

### Custom widget metadata answers

- what explicit methods does this widget expose?
- what arguments do those methods accept?
- how should domain behavior be invoked or queried?

For example, a softtool button might use:

- `accessibleName = "功率扫描"`
- `accessibleDescription = "切换测量类型为功率扫描"`

while a composite measurement widget might expose methods such as:

- `measurementType()`
- `setMeasurementType(value)`
- `availableMeasurementTypes()`

The right design is additive, not exclusive.

## Recommended Patterns

### Good Pattern: custom-painted softtool entry

```cpp
menuButton->setAccessibleName(QStringLiteral("功率扫描"));
menuButton->setAccessibleDescription(QStringLiteral("切换测量类型为功率扫描"));
```

This immediately makes the widget legible to snapshots and selectors.

### Good Pattern: composite widget with explicit methods

```cpp
setAccessibleName(QStringLiteral("测量类型"));
setAccessibleDescription(QStringLiteral("显示并切换当前测量类型"));

QPlaywrightClassMetadata metadata;
metadata.role("combobox")
    .addMethod(QPlaywrightClassMethod().name("measurementType").returnType("QString"))
    .addMethod(
        QPlaywrightClassMethod()
            .name("setMeasurementType")
            .addArg(QPlaywrightMethodArg().name("value").type("QString").required(true))
            .returnType("void")
    );
setProperty("qplaywrightClassMetadata", QVariant::fromValue(metadata));
```

This supports both understanding and reliable action.

### Bad Pattern: hiding business state in description text

Do not do this:

```text
accessibleDescription = "current=powersweep; licenseRequired=false; points=201; channel=1"
```

That is structured state and should be exposed through explicit methods or
state-bearing APIs.

## Implementation Requirements

The end-state implementation must satisfy all of the following.

### Accessibility Fields

Surface `accessibleName` and `accessibleDescription` as first-class widget
fields in both Python and C++ agents.

### Capability-Aware Serialization

Serialize only real widget properties and real widget state.

Required behavior:

- omit properties that the widget does not naturally expose
- preserve valid falsy state such as `false` and `0`
- keep broad tree views coarse and compact
- keep target inspect views more detailed than broad tree views

### Explicit Selectors

Support these selector forms end-to-end:

- `a11y-name=...`
- `a11y-desc=...`

Sync requirements: new selector forms must be added simultaneously to
`protocol.py` selector documentation, Python agent `_selector.py` parser,
and C++ agent `qplaywright_agent.h` `QPlaywrightSelector::parse`. This follows
the same synchronization rule as adding new protocol methods.

### Snapshot Annotation Requirement

Render accessibility-derived labels in snapshots when visible text is absent,
and mark them explicitly with `[a11y]`.

### Tests

Cover at least these cases:

- custom-painted widget with no visible text but with `accessibleName`
- selector match by `a11y-name=`
- inspect output returns accessibility fields only when present
- inspect output preserves valid falsy state such as `checked: false`
- snapshot marks accessibility fallback labels clearly
- parity between Python and C++ agents

### Application Conventions

Application teams should set accessibility metadata whenever they introduce
painter-only or icon-only interactive controls.

## User Guidance

User-facing guidance should be:

- prefer `text=` when the control has real visible text
- use `a11y-name=` when the control is custom-painted or icon-only
- do not expect `text=` to match `accessibleName`, `currentText`, or other fallback labels
- use `invoke()` for business-specific widget behavior
- do not use accessibility text as a substitute for structured domain APIs

## Risks and Tradeoffs

### Localization sensitivity

Accessibility names are localized. This is good for human-facing automation and
bad for language-agnostic long-lived test identities.

Mitigation:

- use `objectName` or future `accessibleIdentifier` for stable identity
- use `accessibleName` primarily for understanding and natural selection

### Semantic drift

If UI teams treat accessibility strings as optional, automation quality will
vary across screens.

Mitigation:

- document accessibility naming as part of the UI contract
- add review checks for new custom-painted interactive widgets

### Overloading description text

Teams may try to stuff structured state into `accessibleDescription`.

Mitigation:

- keep descriptions short
- expose domain state through explicit methods instead

## Final Recommendation

Use `accessibleName` aggressively for any QWidget whose meaning is not otherwise
exposed.

Use `accessibleDescription` to provide concise action-oriented context.

Do not stop there.

For agent-grade automation, the complete design should be:

- stable identity through `objectName`, explicit metadata, and later
  `accessibleIdentifier`
- semantic readability through `accessibleName` and `accessibleDescription`
- structured business behavior through `qplaywrightClassMetadata` and `invoke()`

That combination gives QPlaywright a clean, explicit, and scalable automation
surface for complex Qt business applications.
