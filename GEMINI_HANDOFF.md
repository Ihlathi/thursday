# JARVIS UI — AI Handoff Context

## Project

JARVIS is a system-wide AI accessibility assistant intended especially for:

- people with visual impairments;
- people who struggle with technology;
- people who do not know where controls/settings are;
- users who would benefit from describing what they want instead of navigating complicated interfaces.

Example intents:

- "Make my screen brighter."
- "What's on my screen?"
- "Where are my orders?"
- "Why isn't my sound working?"
- "Help me do this."

The long-term system combines AI reasoning, screen understanding,
accessibility APIs, speech, visual guidance, and computer control.

This is a team hackathon project.

---

# My Responsibility

My primary responsibility is the visual/interface portion of JARVIS.

My work is primarily under:

apps/ui/

The UI is a Tauri 2 application with a transparent system-wide Windows
overlay.

Do not treat the UI as the AI reasoning/backend implementation.

The UI should receive state/actions from the rest of JARVIS and communicate
them visually to the user.

The repository contains existing specifications/documentation describing
communication between components. Those specifications are authoritative.
Do not invent a competing integration protocol.

---

# Design Philosophy

The UI is not decoration.

Its purpose is to make AI computer control understandable to someone who
may know very little about computers.

The user should visually understand things such as:

- JARVIS has activated.
- JARVIS is listening.
- JARVIS has control of the mouse.
- JARVIS is moving the mouse.
- JARVIS clicked something.
- That click caused something on screen to happen.
- JARVIS has released control.

Visual causality is extremely important.

Overall personality:

intentional
understandable
helpful
alive
calm
magical
slightly whimsical
premium

Avoid:

cyberpunk
RGB/rainbow effects
purple-heavy AI gradients
chaotic particles
excessive neon
robotic movement
flashy effects that interfere with accessibility

Primary energy appearance:

pale sky blue + cool white luminous energy.

All visual effects should feel like manifestations of the SAME energy
rather than unrelated animations.

---

# Existing Visual System

## Summoning

JARVIS is globally summoned/dismissed with:

Ctrl + Alt + J

The summon originates at the CURRENT Windows cursor position.

A luminous circular wave expands outward from the cursor.

The wave physically reaches the screen edges.

The screen edges illuminate based on the actual geometry of the expanding
circle.

Near edges therefore react before distant edges.

The energy becomes the persistent JARVIS screen border.

The intended illusion is:

cursor pulse
→ expanding energy
→ energy contacts screen
→ energy enters edges
→ border becomes JARVIS

It should NOT look like one circle fades out while an unrelated rectangular
border fades in.

---

# JARVIS Border

The persistent border is sometimes referred to as the "lantern border."

It uses:

- a thin bright edge;
- white-blue luminous energy;
- substantial soft inward bloom;
- corner blooms;
- subtle breathing;
- magical blue-white particles.

Border particles drift away from the edge and fade.

Particles should be individually distinguishable but soft/blurry.

They should travel visibly into the screen rather than remaining directly
against the edge.

---

# Dismissal

Dismissal does NOT use the original summon cursor location.

Example:

Summon at cursor position A.
Move mouse to position B.
Dismiss JARVIS.
Energy collapses toward B.

Opening and closing therefore have independent cursor origins.

The current cursor position at dismissal time determines the closing target.

---

# Autonomous Mouse Visual Language

JARVIS can visually indicate that the AI has control of the mouse.

## Cursor Aura

When JARVIS controls the mouse, the REAL Windows cursor remains visible.

There must NOT be:

- a second cursor;
- a glowing duplicate cursor;
- a cursor silhouette underneath it;
- a ring;
- a circular UI indicator.

The aura is PURE LIGHT.

Desired appearance:

real cursor
→ concentrated soft blue-white illumination
→ broad pale-blue glow
→ heavily feathered blue haze
→ complete transparency

It should be relatively large, faint, blue, smooth, and extremely feathered.

There should be no obvious boundary.

Small magical particles dissipate away from the cursor, visually matching
the existing border particles.

---

# Autonomous Cursor Movement

Autonomous cursor movement should not look like robotic linear interpolation.

It should also NOT perform large decorative loops.

Movement should be:

mostly direct
+ subtle curvature
+ small path variations
+ natural acceleration/deceleration

Different movements can have different gentle paths:

- slight arc;
- subtle S curve;
- small asymmetric bend;
- slight directional adjustment.

The path should look like a human naturally moved the mouse from A to B.

Long decorative loops/curls are unwanted.

---

# Cursor Trail

When JARVIS moves the mouse, blue-white energy trails BEHIND the cursor.

Never show a planned trajectory ahead of the cursor.

The trail:

- follows the actual traveled path;
- has a luminous core;
- has soft blue-white bloom;
- fades gradually;
- helps inexperienced users understand where the cursor moved.

---

# Click Visual

The current click visual uses a whole-screen response.

Conceptually, the display contains an invisible field of tiny points.

These points are NOT normally visible.

When JARVIS clicks:

cursor arrives
→ aura concentrates
→ click
→ glossy local disturbance
→ wave propagates outward through the screen

As the wave passes through the invisible field, points briefly catch the
blue-white light.

The desired appearance resembles:

a droplet disturbing a sheet of luminous glass.

It should feel glossy, fluid, magical, and premium.

It should NOT merely look like a Canvas circle increasing in radius.

---

# Click / Border Interaction

When the click wave physically reaches the JARVIS border, the border reacts.

This is geometrically timed.

Example:

Click near left edge
→ wave reaches left border first
→ left border reacts first
→ expanding wave later reaches other edges
→ those edges react later.

Do NOT flash every border simultaneously.

The reaction can include:

- brief increased brightness;
- bloom;
- small energy response;
- subtle bounce/rebound;
- short propagation along the border;
- subtle particle response.

The purpose is to make the cursor, screen, and border feel like one physical
energy system.

---

# Settings

JARVIS has/is developing a Windows system-tray Settings interface.

Settings should directly control the REAL renderer.

Do not create a separate fake visual preview implementation.

Conceptually:

Settings UI
→ shared configuration
→ actual JARVIS renderer

Important visual properties should increasingly be adjustable through
settings instead of requiring source-code edits.

Settings should persist between launches.

---

# Development Controls

Ctrl + Alt + J
Summon/dismiss JARVIS.

Existing development controls also test individual autonomous mouse visuals.

Inspect the current source for the authoritative current keybind mappings,
because they may have changed during development.

Development controls should invoke the SAME reusable visual APIs used by
real integration events.

There should not be separate "fake demo animations."

---

# Integration Architecture

The UI now needs to communicate with the other team components.

IMPORTANT:

Read the existing repository specifications/documentation before modifying
integration behavior.

Inspect relevant:

docs/
shared/
mocks/
tests/

and then apps/ui/.

The repository specification is the source of truth for:

- communication mechanism;
- message schemas;
- commands;
- events;
- connection lifecycle;
- component responsibilities.

Do not invent another protocol if one already exists.

The desired conceptual boundary is:

Core/team message
→ UI integration layer
→ UI state/event
→ existing visual renderer

and when appropriate:

UI action
→ UI integration layer
→ documented outbound message
→ Core

The Canvas renderer should NOT contain scattered backend communication logic.

The UI must continue to work independently when the backend/Core is not
running.

Development keybinds should remain available.

---

# Important Architecture Rule

Real integration and development testing must converge on the same visual API.

Example:

development keybind ─┐
                     ├→ activateMouseControl()
Core event ──────────┘

NOT:

development keybind → demo implementation
Core event → separate production implementation

The existing implementation should be reused.

---

# Technology

UI:

- Tauri 2
- TypeScript
- Vanilla frontend
- HTML Canvas
- requestAnimationFrame
- Rust/Tauri backend

Primary UI project:

apps/ui/

Typical development command:

cd apps/ui
npm run tauri dev

The application uses a transparent, frameless, always-on-top Windows overlay.

The Canvas architecture is intentionally lightweight.

Avoid introducing large animation frameworks unless genuinely necessary.

---

# Git

My working branch is:

BlueJBlue/UI

Preserve Git history and make sensible checkpoint commits.

Before making substantial changes:

git status

Do not accidentally commit:

.vscode/
prototype backup directories
generated junk
unrelated teammate work

Do not create new branches unless explicitly requested.

---

# Team Boundaries

Other teammates own other portions of the project.

Avoid invasive modifications to:

core/
platform/windows/
platform/macos/

unless the documented integration contract genuinely requires a small shared
change.

Prefer adapting apps/ui to the shared specification.

This minimizes merge conflicts while teammates independently integrate their
components.

---

# Credit / Compute Efficiency

When using an AI coding agent, preserve compute/credits.

Do not:

- spawn unnecessary agents;
- broadly inspect the repository without purpose;
- perform unnecessary web research;
- repeatedly rebuild after tiny visual tweaks;
- add dependencies for effects Canvas already handles;
- refactor working systems for architectural perfection.

Preferred workflow:

inspect relevant docs/code once
→ understand current implementation
→ make cohesive change
→ validate/build once
→ fix actual errors
→ commit
→ stop

This is a hackathon project.

Priorities:

working
→ visually excellent
→ accessible/understandable
→ integration-ready
→ easy to iterate

Not production-scale architectural perfection.

---

# IMPORTANT FOR ANY NEW AI AGENT

This document describes design intent and historical decisions.

THE CURRENT SOURCE CODE AND CURRENT REPOSITORY SPECIFICATIONS ARE
AUTHORITATIVE FOR WHAT IS ACTUALLY IMPLEMENTED.

Before changing something:

1. Read this handoff.
2. Read relevant repository specifications.
3. Inspect the current implementation.
4. Check Git status/recent history.
5. Preserve existing behavior unless the requested task requires changing it.

If this handoff disagrees with the current code because development continued
after it was written, do not blindly revert the code to this document.
Determine the current intended behavior first.
