# Editing pictures

Studio → **Edit** (or **E** on any picture, or drop / paste / open a photo while
editing). Select an area — or nothing — say what to do, press **Apply**.

| Action | Needs | What happens |
|---|---|---|
| **Change** | words | With a selection: only the selection changes. Without: the whole picture follows the instruction ("make it winter", "pencil sketch"). |
| **Remove** | a selection, or a name | The selected thing disappears and the background is continued. Naming it ("the boat") helps when the selection holds several things. |
| **Hide** — blur, pixelate, cover | a selection | Instant, no AI, deterministic. Strong enough that faces and plates cannot be recovered by sharpening. |

Selection tools: **brush** (B; `[` `]` size), **rectangle** (R), **lasso** (L: click
points, or drag around; double-click, Enter or the first point closes), **erase**
(X, or hold Alt with any tool), undo (Ctrl+Z), invert, clear.

Every result is a new picture in the gallery; the editor moves on to it so edits
chain. **Hold the eye button** to see the previous version, the back arrow returns
to it. Nothing is ever overwritten.

## How it works

* The image model is **FLUX.2 Klein** in its editing mode: the picture is passed as
  a reference and the instruction says what to change. Instructions in other
  languages are translated by the local language model first (1–2 s).
* **Area edits crop and stitch.** The selection plus surrounding context is cut out,
  scaled to ~1 MP (small selections get far more pixels to work with), edited, scaled
  back and blended in through a feathered copy of the selection whose reach is
  bounded (`editing.influence`). Pixels outside that reach are **bit-identical** to
  the original, and the picture keeps its full resolution.
* Whole-picture edits are made at ~1 MP in the picture's proportions.

Typical times on an RTX 5080: 2–3 s per edit once the model is loaded.

## Why this way

Side-by-side runs on an RTX 5080 (book → coffee cup, remove a passer-by, remove a
boat, add sunglasses, change a shirt to a suit):

| Approach | Result |
|---|---|
| Klein reference edit of the crop + stitch (**chosen**) | Clean replacements and removals, natural sunglasses, invisible seams. |
| Masked inpainting without the reference | Invents unrelated scenery inside the selection. |
| Masked inpainting with the reference | Good replacements, but removals leave remnants (half a book, an outboard motor). |
| Reference with the selection filled grey | The model faithfully keeps the grey patch. |
| Reference with a red outline around the selection | The model keeps the object and the outline. |

Known limits: removing the main subject of the picture ("remove his head") tends to
redraw it instead — say what should be there instead with **Change**.
