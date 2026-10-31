# Diagrams

Nine figures, drawn as Excalidraw scenes rather than photographed from a browser.
Each one is generated from `scripts/render_diagrams.py`, so the drawing is source:
review it, change a card, regenerate, and the picture follows.

`arch-09-system-atlas` is the one to open first: it is the whole system on a single
sheet, and it names where each of the other figures goes deeper. The remaining eight
each answer one question and assume you already know where you are.

## Where the architecture lives

There is no `hackathon/` directory: **the repository root is that project.** Older
documents used the prefix while the tree was nested; any path still starting with
`hackathon/` is stale, not a missing folder. The architecture is split across five
kinds of file, and each answers a different question:

| Question | Authoritative file |
|---|---|
| What am I allowed to change, and what must a change carry? | `AGENTS.md` — binding rules, invariants, change protocol, gates |
| What runs where, and what holds state? | `docs/project/SYSTEM_ARCHITECTURE.md` + `arch-01` |
| Which module may import which? | `AGENTS.md` §3 + `arch-02` |
| What happens to one request, end to end? | `arch-09` (every stage), `arch-03` (demo), `arch-04` (provider) |
| What does a node, edge or status prove? | `docs/project/POLICY_KNOWLEDGE_GRAPH.md` + `AGENTS.md` §4 + `arch-08` |
| How does a challenge propagate? | `docs/project/CHALLENGE_AND_REASSESSMENT_ENGINE.md` + `arch-02` (planner card) and `arch-03` (challenge lane) |
| What is stored, and what may be called audit? | `docs/project/DATA_AND_PERSISTENCE_DESIGN.md` + `arch-01` (state) and `arch-07` (seam three) |
| Which route, on which port, with which cap? | `docs/project/BACKEND_AND_API_DOCUMENTATION.md` |
| What is tested, and what do the counts prove? | `docs/project/TESTING_AND_VERIFICATION.md` + `arch-05` |
| What is known to be wrong right now? | `docs/reviews/ARCHITECTURE_AND_CODE_REVIEW.md` + `AGENTS.md` §15 |

Read `arch-09` first if you want to see a request cross every layer; then `arch-01`
for the shape of the system and `arch-02` for the shape of the code. The remaining
figures each answer one question and do not repeat the others.

## The nine figures

| Figure | Answers |
|---|---|
| `arch-09-system-atlas` | How one request crosses every layer, what computes and what refuses at each stage, and what is stored. |
| `arch-01-system-overview` | What runs where, on which port, and what actually holds state. |
| `arch-02-backend-modules` | Which module does what, band by band, from request entry to offline analysis. |
| `arch-03-demo-proposal-flow` | What happens to one synthetic policy pair on `:8083`, including the challenge lane. |
| `arch-04-provider-boundary` | The only path a policy could leave the machine, and every error code that refuses first. |
| `arch-05-test-map` | Where the 481 tests live, and what the counts do not prove. |
| `arch-06-four-stacks` | What each of the four programs owns, keeps and proves, and the imports that cross between them. |
| `arch-07-three-seams` | The three joins where the weaknesses live, what each costs, and the decision fixing it forces. |
| `arch-08-claim-identity` | The one irreversible choice: what a claim is keyed by, and what each key can still prove. |

## How to read any figure

- **The numbered rail is the reading order.** Bands run top to bottom; inside a band,
  cards run left to right. A band is one stage or one shelf, not a column of a table.
  In `arch-09` the left-to-right arrows are reading order only; the vertical spine is
  the flow.
- **Arrows are imports or consequences, never decoration.** In `arch-02` and `arch-06`
  an arrow means one module imports another; in `arch-07` it means one fact causes
  the next. `arch-09` is the one sheet where a horizontal arrow only orders the
  reading (context → input → mechanism → refusal → output) and the vertical spine is
  the flow; its footer says so. A figure's footer says which rule it follows.
- **Dashed arrows are annotations.** In `arch-01` they are reads and writes; in
  `arch-03` they are the challenge posted into a session and the event appended.
- **Colour is a family, not a severity.** Green demo, orange handover, pink proposal
  seam, blue epistemic core, violet safety/evaluation, sand storage/offline graph,
  grey session state, red a refusal.
- **The dashed footer is the caveat.** It states what the figure does not claim.
  If you quote a figure, quote the footer with it.

## Reading guide

### `arch-09-system-atlas` — the whole system on one sheet

**Question:** how does one request travel through this system, and what refuses at
each stage?

**Rows:** seventeen bands. 01 runtime, 02 intent, 03 admission, 04 session, 05 pair,
06 envelope, 07 normalise, 08 compare, 09 validate, 10 challenge, 11 recompute,
12 project, 13 plan, 14 record, 15 prove — then 16 siblings and 17 stores, the parts
outside that path.

**Start here:** the spine, not the first card. Every band puts its mechanism in the
middle column, so the arrows between bands form one continuous line from *change
question* to *one event*. Trace that line alone and you have the request; read the
cells either side of it and you have the contract around each step.

**How to read one band:** five cells, left to right — who acts, what is handed in,
what computes, what can stop it, what comes out. The refusal cell is a designed
branch, not an error: it names the code the caller receives instead of an output.

**Stage by stage:**

| Band | What it settles | Card to read first |
|---|---|---|
| 01 Runtime | What actually runs, and where state lives | `Demo API :8083` |
| 02 Intent | The one question, and what it refuses to answer | `Change question` |
| 03 Admission | How a request becomes a bounded object | `Bounded reader` |
| 04 Session | Which scenario, and which generation may write | `Generation gate` |
| 05 Pair | The source contract, checked once then frozen | `validate_policy_pair` |
| 06 Envelope | What the candidate generator may see | `Deterministic adapter` |
| 07 Normalise | Strictness: a mismatch is refused, never repaired | `normalize_proposal_response` |
| 08 Compare | Why a caller's claim stays an assertion | `compare_candidate` |
| 09 Validate | The only output the system signs | `INCONCLUSIVE` |
| 10 Challenge | Who names the rule, the passage and the department | `Applicability audit` |
| 11 Recompute | What is actually computed after a challenge | `recompute (scripted)` |
| 12 Project | Why the graph is a view, rebuilt per request | `project_policy_graph` |
| 13 Plan | Why a plan is reachability, not truth | `plan_challenge_impact` |
| 14 Record | Compute first, then write one bounded event | `Ring buffer` |
| 15 Prove | What the suite proves, and what it does not | `Not claimed` |
| 16 Siblings | The other two products, and their isolation | `No cross-import` |
| 17 Stores | Four storage regimes, one of them blocked | `Blocked gate` |

**The arc in five sentences.** A reviewer asks whether the newer policy changed an
obligation (02). The body is bounded, the session pins one scenario and one
generation, and the pair is frozen with a digest per version (03-05). A deterministic
fake candidate proposes a relation; the proposal is normalised without repair,
compared with the caller's claims kept untrusted, and validated into a literal
`INCONCLUSIVE` (06-09). A challenge names a department, the audit grounds or refuses
the applicability condition, and the recompute is a scripted abstention rather than a
derivation (10-11). That result is projected into a typed graph, planned as a bounded
reachability question, and recorded as one event — the graph and the plan are computed
beside the result and never feed it (12-14).

**Watch for:** horizontal arrows order the reading within a band; only the vertical
spine is flow. Bands 16-17 are outside the path and share the sheet, not the
sequence. And the recompute card says `scripted` for a reason: the abstention is fixed
by construction, so no arrow from the plan reaches it.

**Does not claim:** semantic support, audit completeness, a live provider, durable
storage, authentication, or that the graph is stored.

**Written from:** `backend/*.py`, `backend/app/*.py`, `backend/tests/` and
`AGENTS.md`, on 2026-10-31; the suite figures are read from `AGENTS.md` §13.

### `arch-01-system-overview` — the deployment picture

**Question:** what runs, and what survives a request?
**Rows:** Client (one browser, one proxy) → Services (three FastAPI apps, one port
each) → Process (what each port actually runs) → State (the only things that
outlive a request).**Start here:** the State band. Three services hold two kinds of memory — a session
  dict on `:8083` and SQLite owned by `:8081` — and `:8082` holds nothing at all.
**Does not claim:** that the three services call each other (they do not), or that
anything is deployed, authenticated or backed up.
**Written from:** `README.md`, `app/main.py`, `policy_api.py`, `policy_demo_api.py`,
the Vite config.

### `arch-02-backend-modules` — the code picture

**Question:** which module does what, and which imports define a layer?
**Rows:** Entry points → Seam → Shared core → Records → Graph and planner → Wire →
Evaluation.
**Start here:** the Graph band. `policy_demo_graph.py` is the only module that knows
both the hotel corpus and the typed graph; `policy_dependency_graph.py` imports
nothing from the scenario layer, so a scenario edit is not a graph edit. Its note
carries the one import not drawn (the challenge route → the projection), because a
straight drop from the entry column would run through three bands of cards.
**Watch for:** three cards in the Records band are listed rather than routed —
`policy_demo_session`, `app/store`, `app/access`. The generator prints those three
declarations on every run; they are declared exceptions to the no-floating-card
rule, not oversights.
**Does not claim:** the full import graph, call frequency, or runtime order.
**Written from:** the import statements in `backend/` and `backend/app/`.

### `arch-03-demo-proposal-flow` — one pair, one challenge

**Question:** what happens to a synthetic policy pair on `:8083`?
**Rows:** Pipeline (scenario → envelope → candidate → normalise → validate) →
Challenge (posted challenge → applicability audit → recompute) → Session (manager →
history).
**Start here:** the dashed "challenge posted" arrow. The challenge lane re-uses the
pair from step 1 and lowers the relation to `INCONCLUSIVE`; it never flips it to a
contradiction. The recompute is a scripted abstention, so everything the lane shows
after the audit is fixed by construction.
**Watch for:** the graph summary and impact plan the challenge now returns are
computed *beside* this lane and never feed it. The figure leaves them out on
purpose; `arch-02` shows where they are built.
**Does not claim:** that the recompute is derived from the graph, or that the
session log is durable.
**Written from:** `policy_evidence_demo.py`, `policy_proposal_contract.py`,
`policy_mock_provider_runner.py`, `policy_compare.py`.

### `arch-04-provider-boundary` — the only egress path

**Question:** how could a policy leave the machine, and what refuses first?
**Rows:** Projection → Guard → Wire → Response → Parsed. Each row is one stage: the
violet guard in the middle, its refusals on either side.
**Start here:** any red card. Each one is a named code that refuses *before* the next
stage, so the answer to "what stops this?" is a specific card, not a promise. The
attempt is reserved before the call and not refunded after a failure, so a refusal
cannot quietly become a retry loop.
**Watch for:** the mock adapter sits behind the same boundary, so the demo exercises
these refusals instead of bypassing them; a real provider would inherit every check
without a call site changing.
**Does not claim:** that a real provider is selected, that credentials exist, or that
this boundary is an authorization control.
**Written from:** `app/provider_safety.py`, `app/httpx_transport.py`,
`app/mock_provider.py`.

### `arch-05-test-map` — size, not strength

**Question:** where do the tests live, and what do the counts prove?
**Rows:** five groups of test modules; bar length is the number of test functions in
that module, parsed from `backend/tests` on 2026-10-31.
**Start here:** the callout. 62 tests assert nothing but raise, 68 of 481 carry a
docstring, and no test reaches the UI at all — which is why a hook-order crash
survived until the review. Two launcher tests fail away from Windows.
**Does not claim:** coverage, pass status, or that a long bar means a strong test.
**Written from:** parsing `backend/tests`; the counts describe size, not defensibility.

### `arch-06-four-stacks` — the product boundaries

**Question:** what does each of the four programs own, keep and prove?
**Rows:** Entry point → What it owns → What it keeps → What the code proves; the four
columns are A (handover), B (comparison), D (demo), C (graph).
**Start here:** the horizontal arrows. There are exactly two: demo imports five
modules from the comparison core, and demo projects the graph per challenge. Stack C
has no process and no route of its own — it is reached from `:8083` and stores
nothing. Stack A shares no runtime module with any other stack.
**Watch for:** the red line that used to run from the graph into the hotel corpus is
gone; the callout records why. The test counts under each column are parsed, not run.
**Does not claim:** that the stacks exchange data, or that a larger test count is
better evidence.
**Written from:** the import statements in `backend/` and parsed test counts.

### `arch-07-three-seams` — what is actually weak

**Question:** where are the joins that cost something, and what does fixing each force?
**Rows:** The seam → What it costs → The fix → What each fix forces; read each column
top to bottom.
**Start here:** seam two. The demo's recompute is a literal `INCONCLUSIVE`, not a
derivation from the plan, while the UI copy reads as derivation. That is a live
mismatch between claim and mechanism, and it is why the figure now names it instead
of the layering inversion that has been fixed.
**Watch for:** seams one and three reduce to one decision — what a claim is keyed by.
`arch-08` walks that choice. The recompute seam forces a different owner decision and
is not a migration.
**Does not claim:** that any of the three is scheduled, or that the fixes are
refactors rather than decisions.
**Written from:** `policy_dependency_graph.py`, `policy_demo_session.py`,
`policy_evidence_demo.py`, `app/store.py`.

### `arch-08-claim-identity` — the irreversible choice

**Question:** what is a stored claim filed under, and what can each key still prove?
**Rows:** The two keys → What it decides (the queries it allows) → Two ways out, each
keeping one half.
**Start here:** the footer test. Can every stored before/after be re-expressed as an
event over a node id, without guessing at a quote and without losing which passage
was cited? If yes, take the node id; if no, the blob key is the honest choice and the
graph stays a view.
**Watch for:** the costs are not symmetric. Option 1 re-references history and rebuilds
the revision CAS; Option 2 means typed edges never reach a stored conclusion.
**Does not claim:** which option is correct — that is an owner decision
(`AGENTS.md` §16, D-1).
**Written from:** `app/store.py` (`claim_versions`, `history`) and
`policy_dependency_graph.py` (node ids).

## Files

```
docs/diagrams/
  src/*.excalidraw     the scene: editable in Excalidraw, this is the source of truth
  arch-0*.svg          rendered for READMEs, print and zooming
  README.md            this file
```

There is no PNG in the repository on purpose. A PNG is a second, unchecked copy
of the scene that quietly drifts; the scene and the SVG are both regenerable.

## Regenerate

```bash
python3 scripts/render_diagrams.py
```

That rewrites the nine scenes in `src/`. The build fails rather than shipping a
card whose text is wider than its cell, so run it before committing.

Render a scene to an image with the Excalidraw MCP server, which uses the official
Excalidraw renderer:

```text
excalidraw.render(path="docs/diagrams/src/arch-01-system-overview.excalidraw",
                  format="svg", saveTo="docs/diagrams/arch-01-system-overview.svg")
```

Repeat for the other eight names. `excalidraw.validate` reports schema, binding,
text-overflow and overlap problems; run it with
`rules: ["schema", "bindings", "text_overflow", "overlap"]` and expect `[]`.
Warnings that a card's label sits inside its card are expected (that is the
point); anything else is worth fixing before committing an image.

## Style

The look follows the `P2-bridge-component-map` diagram: hand-drawn and confident,
not corporate.

- **Virgil type** (Excalidraw's hand-drawn face) at 28 px titles, 15 px subtitles,
  15 px card titles, 13 px body, 11 px labels and rail text.
- **Rough 2 px strokes** with 12 px rounded corners, on white. Fills are Open Color
  tints at 4-6% so the ink stays the strongest thing on the page.
- **Accent title, dark body.** Each card's name is painted in its family colour and
  the explanation below it in near-black, so the eye can scan names without reading.
- **A numbered left rail owns every heading.** `01`, `02`, … then an uppercase
  heading and a one-line note. The rail is outside the card grid, which is what
  lets a connector run past it without ever crossing text.
- **One pale rule** closes the title block, so the sheet starts where it starts.
- **Arrows take the colour of the family they land in**, and leave from the edge
  facing the target.
- **Dashed callouts** carry the caveat at the bottom of each figure: what the
  diagram does not claim, or the one sentence worth remembering.

## Layout conventions

The rules are enforced by the generator, not by eye — see its docstring.

- **A column grid, not free placement.** Cards snap to cells and may span columns.
  Every band's cards share one height, with their text vertically centred, so rows
  read as shelves and nothing drifts when a line changes.
- **Lanes live in the gutters.** A cross-band arrow drops into the gutter above its
  target band, runs sideways, and enters the card from the top. Arrow labels are
  seated against a list of card and heading rectangles, so a label never prints
  across a box.
- **A card is exactly as tall as its text.** A requested width is a minimum: if a
  card would clip its own text, the build stops.
- **Colour means something**, consistently across all nine figures: green is the
  demo and synthetic path, orange is the legacy handover app, pink is the proposal
  seam, blue is the epistemic core, violet is safety and evaluation, sand is
  storage and the offline graph, grey is session state, red is a refusal.
- **Every figure states its own scope** in the footer, including what it does not
  claim, and names the files it was read from with the date.

## What the figures deliberately avoid

- No arrows between modules that do not import each other. The backend map shows
  the imports that define a layer, and says in its own callout that it is not the
  full import graph; the graph band's note carries the one import it does not draw,
  because a drop from the entry column would run through three bands of cards.
  `arch-06` draws the crossing imports that do fit — demo into the comparison core
  and demo into the offline graph — and neither `policy_dependency_graph` nor
  `policy_challenge_propagation` imports the scenario layer. `arch-07`'s arrows are
  consequences (a seam costs something, a cost is fixed by something), never
  imports, and its footer says so.
- No box without a connection. `Figure.save` walks every solid card and fails the
  build if one is not bound to an arrow. A card that is listed rather than routed —
  because its caller sits three bands away and routing it would cross the core —
  has to be declared with `fig.unconnected_ok(key, reason)`; the generator prints
  each declaration on every run, so the exception cannot be silent. `arch-02`
  declares three such cards; no other figure declares any.
- No numbers that the repository cannot reproduce. The test map counts come from
  parsing `backend/tests`; the provider figure's caps (16 KiB request, 4 KiB
  response, 20 s, 17 attempts, $5.00) are read from `app/provider_safety.py`.
- No "future work" boxes. Anything not implemented is absent, not drawn as if it
  existed.
