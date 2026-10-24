# Building Guide Web Product Plan

**Status:** Approved for MVP implementation  
**Project:** `hackathon-synera`  
**Product name:** `Wayfinder` (configurable product label, not a hard-coded architectural identifier)  
**Scope:** React frontend for the Track 01 indoor navigation challenge  
**Date:** 2026-10-24

## 1. Product Thesis

### 中文

产品名：**Wayfinder**。产品名称通过应用配置或品牌 token 注入，代码中不把它固化为不可修改的业务标识；项目名称固定为 `hackathon-synera`。

它不是一张“缩小版建筑 CAD 图”，而是一个能把用户的自然语言目标翻译成可跟随路线的室内向导：用户说“我在主入口，带我去 CNC 铣床，不能走楼梯”，界面同时回答三件事：

1. 我理解了什么；
2. 你要经过哪些空间、哪一层、走多远；
3. 现在应该在地图上看哪里、下一步做什么。

核心体验是 **route as a story**：路线不是一次性画出的红线，而是一段可以逐步播放、暂停、回看和切换楼层的空间故事。所有动画都服务于定位、方向感和可解释性。

### English

Product name: **Wayfinder**. The visible product label is configurable and must not be treated as a permanent domain identifier. The repository/project name is `hackathon-synera`.

Wayfinder is not a miniature CAD viewer. It translates a natural-language goal into a route a person can follow indoors. The interface makes three things explicit: what it understood, which spaces and floors the user will traverse, and where the user should look next.

The signature interaction is **route as a story**: a route is progressively revealed, paused, replayed, and stepped through across floors. Motion serves orientation and explanation, not decoration.

## 2. Users and Single Job

| User | Primary need | Default surface |
|---|---|---|
| First-day visitor | Find an unfamiliar room or everyday facility | Plain-language search and guided route |
| Wheelchair user | Reach a destination without stairs or inaccessible doors | Persistent step-free preference and honest unreachable state |
| Service technician | Follow a route with hands busy | Large next-step instruction, optional voice input later |
| Facility manager | Reflect a closed lift or proposed door change | Preview, explicit confirmation, revision-aware map |

**Single job:** get a person from a known or inferred starting point to a destination inside the building with the least cognitive load.

## 3. Experience Model

### First screen: “Orient, then ask”

The first viewport is an active navigation workspace, not a marketing hero:

```text
┌─────────────────────────────────────────────────────────────────────┐
│ WAYFINDER     Fertigung Ost 27        [step-free] [settings]        │
├──────────────────────────────┬──────────────────────────────────────┤
│                              │                                      │
│     FLOOR PLAN / ROUTE       │  GUIDE                               │
│     quiet map canvas          │  “Where are you going?”              │
│     animated route tape       │  [Main entrance to CNC mill...]     │
│     floor rail  1  0  -1     │                                      │
│                              │  Understood                          │
│                              │  Main entrance → CNC mill             │
│                              │  46.1 m · step-free · Ground floor    │
├──────────────────────────────┴──────────────────────────────────────┤
│  NEXT: Walk through Main aisle H-B2                         14 m →  │
└─────────────────────────────────────────────────────────────────────┘
```

### Primary interaction loop

1. User enters a sentence or selects a suggested destination.
2. Guide shows an “understood” summary before relying on the route.
3. The map focuses on the relevant floor and highlights destination/asset.
4. Route is drawn as a directional tape; the next instruction is prominent.
5. User can step through directions, jump to a floor, replay, or ask a follow-up.

### Signature element: the route tape

The route line is a physical-looking, high-contrast “tape” laid over the plan. It animates from the current position toward the next decision point. At a floor transition, the tape folds upward into a compact vertical connector marker, then reappears on the next floor. This makes cross-floor navigation legible without requiring a full 3D scene.

Three.js is used only for an optional **exploded floor stack** view and the transition between floors. The 2D plan remains the source of truth and the default interaction surface.

## 4. Visual Direction

### Design rationale

Industrial, civic, and campus buildings are usually represented with cold CAD conventions. Wayfinder borrows the language of **wayfinding signage and transparent tracing film**: neutral plan surfaces, one route accent, strong spatial labels, and a small amount of translucent overlay. This gives the product a recognizable identity without turning it into a game.

### Tokens

| Token | Value | Use |
|---|---|---|
| Ink | `#17211F` | Primary text, map labels |
| Paper | `#F6F7F3` | App background |
| Plan | `#E8ECE5` | Floor plan surface |
| Route | `#E4572E` | Route tape, destination, primary action |
| Signal | `#0E8F80` | Step-free, confirmed, active focus |
| Caution | `#D19A24` | Preview, ambiguity, pending action |
| Danger | `#B84747` | Unreachable, closed, destructive state |
| Grid | `#CBD5CD` | Plan lines and dividers |

Avoid a single-hue palette, purple gradients, decorative blobs, and excessive glassmorphism. Surfaces are mostly flat, bordered, and calm; the route tape carries the visual energy.

### Typography

- Display: `Space Grotesk`, restrained use for the product name and route distance.
- Body: `Inter`, optimized for compact instructions and multilingual fallback.
- Data/IDs: `IBM Plex Mono`, for room IDs, floor levels, distances, and request diagnostics.

Use sentence case, active verbs, and user vocabulary. Example: “Walk through Main aisle” instead of “Execute transition via node H-B2”.

## 5. Information Architecture

### Shell

- Desktop: compact top bar, two-column workspace, floor rail inside the map.
- Tablet: map remains primary; guide panel becomes a bottom sheet or right drawer.
- Mobile: map first, guide as a draggable bottom sheet; one persistent next-step control.
- No global sidebar in the first release; it would compete with the navigation task.

### Core surfaces

1. Building picker: searchable list with floors, lifts, stairs, and step-free entrance indicators.
2. Navigation workspace: map, route tape, floor rail, guide transcript, composer.
3. Search result layer: rooms/assets with floor, location, and “route here” action.
4. Clarification layer: 2–4 candidate chips from `ask` effects; no free-form form.
5. Route story: distance, accessibility, floor sequence, directions, replay/next controls.
6. Change preview: proposed closure/door with highlighted spaces, confirm/cancel, revision state.
7. Failure state: reachable false, closed connector explanation, alternative action.

## 6. API and Data Mapping

The frontend depends on the existing OpenAPI contract only. It must not calculate routes or infer geometry from raw UI state.

| API capability | UI responsibility |
|---|---|
| `buildings` | Building picker and capability badges |
| `sessions` | Session lifecycle, persisted preferences, reload recovery |
| `floors` | Floor rail and floor transition context |
| `plan` | Declarative geometry renderer; unknown effects ignored safely |
| `places` | Search suggestions and result layer |
| `routes` | Route tape, floor legs, direction list, reachable/unreachable states |
| `messages` | Conversation orchestration and `effects` application |
| `actions` | Preview, explicit confirmation, cancellation, revision refresh |

The existing fixture set is the first frontend integration target: `message-accepted.json`, `message-clarify.json`, `message-pending-action.json`, `route.json`, `route-unreachable.json`, `floor-plan.json`, and `floor-plan-closed.json`.

## 7. Frontend Architecture

### Proposed stack

- React + TypeScript + Vite.
- TanStack Query for server state and request lifecycle.
- Zustand or a small reducer for session/view state only; do not duplicate server truth.
- Zod-generated or hand-maintained OpenAPI boundary types, with runtime validation in development.
- `react-konva` or SVG for the reliable 2D plan renderer; use SVG when hit testing and accessible labels are more important than raw canvas throughput.
- Three.js / React Three Fiber for the optional exploded-floor visualization.
- Motion library with reduced-motion support for route reveal and panel transitions.
- Lucide icons for controls; icon-only controls require accessible names and tooltips.

### Module boundaries

```text
src/
  app/              routes, providers, error boundary
  domain/           session, route, floor, place, action models
  api/              OpenAPI client, fixture adapter, request errors
  features/
    building-picker/
    navigation/
    guide/
    route-story/
    change-preview/
  rendering/
    plan-2d/
    floor-stack-3d/
  design-system/    tokens, primitives, focus and motion rules
```

Dependency direction: UI features → domain/API adapters; renderers consume declarative plan data; domain models do not import React, HTTP, or Three.js.

## 8. State and Accessibility Contract

Every feature has intentional loading, empty, error, success, partial, and long-content states.

- `role="status"` announces route calculation and floor changes.
- `role="alert"` announces unreachable routes and destructive confirmation errors.
- Keyboard focus is visible and returned to the triggering control after dialogs.
- The route is never conveyed by color alone: line pattern, start/end markers, labels, and direction text are required.
- Step-free preference is a persistent toggle with a clear active state.
- Reduced motion replaces route animation with a static route plus a short status message.
- Map controls have button names such as “Zoom in”, “Show ground floor”, and “Replay route”.
- Mobile targets are at least 44px; no horizontal document overflow at 320px.

## 9. Delivery Plan

### Phase 0: contract proof

- Scaffold React/Vite app and fixture adapter.
- Render one floor plan from `floor-plan.json`.
- Render `route.json` with start, destination, route tape, and direction list.
- Add fixture-driven tests for accepted, clarify, pending action, and unreachable responses.

### Phase 1: usable navigation

- Building picker, session creation, floor rail, search, route creation.
- Route story with next-step focus and mobile bottom sheet.
- Step-free preference and reload recovery.

### Phase 2: distinctive demo layer

- Animated route tape and floor transition.
- Optional exploded floor stack with Three.js.
- Voice-ready composer boundary using the existing `input_mode` contract, without making speech recognition a dependency.

### Phase 3: change-aware building

- Pending action preview, confirm/cancel, revision refresh.
- Closed lift/door visualization and alternate-route messaging.
- Demo script covering ambiguity, accessible routing, and a confirmed map change.

## 10. Quality Gates

### Functional

- Correctly applies all known effect types: `highlight_spaces`, `highlight_assets`, `focus`, `draw_route`, `clear_route`, `set_closures`, `ask`, `building_patched`.
- Ignores unknown effects without breaking the response.
- Does not recompute `length_m` or fabricate route polylines.
- Does not apply a building change before confirmation.
- Preserves `last_route_id`, `pending_action_id`, `revision`, and preference state after reload.

### Visual and accessibility

- Check 320, 390, 768, 1024, and 1440px widths.
- Check light theme, keyboard navigation, reduced motion, long direction text, empty search, and unreachable route.
- Run Playwright smoke tests and axe WCAG AA checks on the navigation workspace.
- Verify route canvas/SVG is nonblank and no document-level horizontal overflow exists.

### Demo acceptance

1. “Where is the coordinate measuring machine?” focuses the correct asset and room.
2. “From the main entrance to the CNC mill without stairs” draws a 46.1 m route and exposes the next instruction.
3. “Where is the desk?” presents candidate choices instead of guessing.
4. Closing the office lift shows a preview, requires confirmation, then makes the route unreachable when appropriate.
5. A route across floors makes the floor transition understandable in 2D before the optional 3D view is shown.

## 11. Approved Decisions

The following decisions are approved for MVP implementation:

1. Product label: **Wayfinder**, configurable for later renaming; repository/project name: `hackathon-synera`.
2. MVP UI language: English. Internationalization is implemented from the first pass with English as the only populated locale; German is a planned future locale and other locale values remain intentionally empty.
3. API boundary: use the existing `/api/v1` OpenAPI contract as the only frontend/backend contract. The frontend must not introduce parallel payload shapes.
4. Default demo building: `proc-factory-dev-003`, while retaining the building picker for generality.
5. Three.js scope: implement the first visual prototype and evaluate it in the running app; keep it replaceable and secondary to the 2D plan renderer.

## 12. MVP Internationalization Contract

- All user-facing strings are keys, not inline text in feature components.
- `en` is complete for MVP.
- `de` is registered as a locale but may contain empty or fallback entries until the German pass begins.
- API field names, `operationId`, stable IDs, and diagnostic error messages remain English as required by the existing project contract.
- Locale selection is separate from building/session state and does not change API request bodies in MVP.
- Missing translations fall back to English and emit a development-only warning.

