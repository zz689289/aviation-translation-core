# Scoped presentation evidence checks (candidate contract 1)

`check_presentation.py` checks supplied, hash-bound evidence. It does not render a
PDF, discover all objects, perform OCR, decide a translation or operate a native
reader. It is separate from the existing translation/workflow contract version 2.
No new dependency or source-PDF parser is introduced.

Prepare a private directory with source/target artifacts, two measurement profiles
and the evidence files. The source profile has `basis=SOURCE_EVIDENCE`; target has
`basis=OUTPUT_MEASURED`. Each binds its artifact SHA-256. Source observations must
be made from the original or an actual scoped user decision, before target values
are used as expectations. A file hash binds bytes, not an observer's honesty.

Declare the same nonempty `scope_ids` in the spec and source profile. Each unit has
an ID, kind, value, locator and nonempty hash-bound evidence; source units also
identify `source_measurement` or `scoped_decision` authority.

| Kind | Value | Comparison |
|---|---|---|
| `metric` | Finite number and explicit unit | Source absolute tolerance, default exact; no inferred tolerance |
| `role` | Nonempty role string | Exact; e.g. bold versus regular for the same source cell |
| `text` | `{path,sha256}` of a raw UTF-8 probe | Exact text including whitespace; no normalization hides duplicates |
| `pixels` | `{path,sha256}` of an 8-bit P6 PPM crop, plus `pixel_context` | Exact decoded width, height and RGB pixels |

Measure table geometry and emphasis separately from contents: correct numbers do
not prove that widths or highlighted cells are preserved. Measure bullet marker,
body and continuation anchors independently; do not substitute spaces for actual
coordinates. Keep all paper-specific values in private profiles, never in rules.

For figures, retain a source-to-target coordinate transform and label-role map.
Protect curves, arrows, frames, ticks, units and antialias edges before modifying
labels. Take crops from actual source/output rasters in the same color space.
Pixel units require matching declared `pixel_context` values for `renderer`,
`color_space` and aligned `sample_grid`. Missing or different contexts are invalid,
not a graphical FAIL or PASS. Context labels are caller evidence, not automatic
environment authentication. A renderer change can alter antialias/color values;
asset-to-output pixel identity does not prove fidelity to a differently rendered
source PDF. Keep those comparison stages separate.
Do not shrink a protected region or widen tolerances after failure just to pass;
investigate drift and retain the failed observation. Comparing a protected crop
does not certify the rest of a figure. Screen/readability inspection remains needed.

For inline mathematics, provide separate visual evidence and raw extraction
probes around the affected formula. Missing image-only mathematics and repeated
adjacent characters must not be hidden by whitespace cleanup. Native clipboard
status requires an actual selection/copy/paste operation outside this checker.

```powershell
& $py -X utf8 -I -B scripts/check_presentation.py `
  --root $privateRun --spec presentation.json --output presentation-result.json
```

See `schemas/presentation.schema.json` and `schemas/presentation-profile.schema.json`.
Like other entry points, outputs cannot overwrite inputs/existing files, private
paths/content are not printed, and file/symlink/hash checks use the existing Store.
Exit 0/1/2 means mechanical PASS / mismatch / invalid evidence. All outputs retain
`visual_qa=NOT_PERFORMED`, `native_clipboard=NOT_TESTED`, `human_approved=false`
and `released=false`. The selected measurements do not establish complete coverage.
