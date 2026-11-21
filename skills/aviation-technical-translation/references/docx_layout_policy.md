# Publication-grade DOCX layout policy

## Rule classification

- `CORE_RULE` governs how layout evidence, structure, rendering, and QA are represented. It must not contain one project's pages, counts, identifiers, dimensions, or repair values.
- `LAYOUT_PROFILE` supplies project-selected typography, spacing, geometry, captions, and renderer settings.
- Keep document-specific settings and review evidence in the job directory.

## Layout authority and profile

**CORE_RULE.** Derive layout from the authoritative source or an approved template, then freeze it in a machine-readable specification. Page size, margins, palette, fonts, section boundaries, special pages, object widths, TOC levels, and renderer are project data rather than Skill constants. Check font availability before layout work; substitution invalidates dependable pagination and exact pixel comparisons.

Select and record one profile:

- `source_faithful` (`LAYOUT_PROFILE`): derive typography and spacing from source/template evidence. This is the neutral choice when no Chinese house style is authorized.
- `zh_formal_print` (`LAYOUT_PROFILE`, optional): Chinese body, lists, requirement/regulatory text, and bibliography use SimSun at 12 pt; Latin text uses Times New Roman; major headings use SimHei for Chinese; minor headings use SimSun; Figure/Table captions use SimSun at 10.5 pt with Latin text in Times New Roman; equations use Cambria Math. Profile values may be overridden only by explicit project evidence.

`zh_formal_print` is never a mandatory default. A project may define another approved profile.

`personal_zh_review` is an opt-in personal typography profile (see personal_style.md), not another document's layout template. Source colours, margins, role hierarchy and special pages are initialized afresh. Individual approved project overrides take precedence within their exact scope.

## Font system

**CORE_RULE.** Control Word font axes independently:

- `w:rFonts/@w:eastAsia` for Chinese;
- `w:rFonts/@w:ascii` and `@w:hAnsi` for Latin text;
- `@w:cs` when complex-script fallback is relevant;
- Cambria Math for mathematical runs and OMML.

Set fonts through semantic named styles wherever possible, and verify direct-format runs cannot defeat them. Any change to fonts or fallback mapping requires Word repagination, PDF export, every-page rendering, and renewed visual QA. A DOCX XML inspection alone cannot approve typography.

## Styles, headings, captions, and TOC

**CORE_RULE.**

- Define leading in the paragraph style and check the effective spacing after direct overrides. Use the adjacent paragraph styles to produce one intended gap. Remove spacer paragraphs, unnecessary keep chains and manual breaks that create holes. Keep figures and tables with their own captions. Allow tall inline mathematics to clear neighboring lines. Check same-style baselines and the visible space before paragraphs, figures and tables in the rendered Word export.
- Use named semantic Word styles; do not hard-code every paragraph independently.
- Preserve visible source numbering as explicit text unless an approved numbering model proves equivalent. Remove unintended `numPr` to prevent double numbering.
- Use one semantic `figure_caption` role and one semantic `table_caption` role. A layout profile controls their Word style name, font axes, size, spacing, alignment, and keep rules.
- Do not add a Word caption when an approved asset already contains it. Record `caption_embedded` and enforce exactly one caption source.
- QA all captions of the same semantic type for style consistency; compare caption wording, label, numbering, placement, and page relationship to source.
- Build the TOC from an explicit whitelist rather than every heading-looking paragraph. NoTOC counterparts omit `w:outlineLvl` while retaining the intended visible style.
- Insert a real TOC field and update it in Microsoft Word. A field code created by `python-docx` does not prove that displayed results were refreshed.
- After refresh, compare actual TOC text, page number, level, order, last-entry spacing, group spacing, and special-entry spacing against source/template visual evidence. Store expected spacing relationships in `toc_map.json`; do not invent universal numeric gaps.

## Sections, ownership, and pagination

**CORE_RULE.**

- Represent page/section transitions explicitly; never position content with runs of blank paragraphs.
- Configure page geometry, headers, footers, linkage, and page-number restart per section profile.
- Annex, Bibliography, Back Cover, and other special sections may each carry a source-evidenced `title_spacing_override`. Do not assume all Annexes share one heading gap.
- Use keep rules where semantically appropriate, then verify the actual Word pagination for orphan headings, clipped objects, accidental blank pages, and uncontrolled table splits.
- Every requirement or quoted regulatory block must contain one `owner_ref` and one `source_owner_ref`. Both resolve to the same valid heading in the same section and agree with source order. The active semantic owner is established by source mapping, not by page position or visible proximity.
- After repagination, revalidate that a block has not migrated under a different heading and that structured order still matches source order.

## Tables and requirement frames

**CORE_RULE.** Use real Word tables with declared columns, deterministic widths, disabled AutoFit, repeating header rows, cell alignment, border rules, and row-splitting policy. Validate every row/merge before writing. A framed requirement/note is a semantic object even when implemented as a one-cell table.

Distinguish logical source tables from physical render tables. Same-page continuation tables may be joined in the presentation layer when authorized, preserving all source cell coordinates and aliasing only repeated semantic headers. Repeat headers at actual page breaks, not at every source-PDF break. Keep semantically separate requirement frames separate. Compare coordinate-to-cell consumption, not a hard requirement that physical table counts match source counts. Bibliography uses true hanging indent/tab design, never spaces.

## Equations and footnotes

**CORE_RULE.** Inventory source formulas independently, including image streams and inline symbols. Prefer true OMML/Cambria Math; if reliable reconstruction is impossible, use a lossless source-quality formula asset with a documented reason and explicit acceptance—not ordinary Unicode pretending to be an equation. Check normalized symbols and actual visual form. Insert true Word footnotes at the exact phrase, not paragraph end. Every source occurrence needs an anchor/body; two legitimate occurrences may have identical body text. Missing or leaked action markers fail, but repeated prose alone is not a duplicate marker. Verify occurrence IDs, order, binding and full rendered body after Word processing.

## Figures and branding assets

**CORE_RULE.** Use only approved assets; preserve aspect ratio, avoid unjustified upscaling, disable Word compression, and record hash, pixel dimensions, approval, embedded-caption state, placement, and source.

Declare every required flag, logo, seal, or other brand object in the layout `brand_assets` registry so publication evidence cannot silently omit it.

For EU flags and aviation/aerospace organization logos, verify all of the following in the Word-exported PDF and page raster:

- the complete asset is visible;
- no source-image crop has been applied unintentionally;
- the asset stays inside page, cell, header/footer, and drawing bounds;
- aspect ratio is locked and matches the approved source asset;
- transparency/background treatment and adjacent labels do not hide any part;
- the visual-review evidence names the reviewed page/object and records PASS/FAIL.

If translated labels obscure arrows, axes, or data, rebuild from a source-quality asset. Repeated raster paint-over is not an acceptable repair workflow.

## 保存前后实际生效检查

运行 `docx_preflight.py --docx 文件.docx --report 新报告.json`，在Word前和实际保存后各检查一次。检查所有含段落的Word故事区，拒绝词内U+FEFF、重复或位于内容之后的w:rPr/w:pPr；不删除合法ZWJ、NBSP或数学符号。该检查不会修文件，也不保证所有OOXML均有效。

源文强调须映射到具体出现位置及完整短语边界；中文别名、括号和语序变化不能靠字面关键词匹配处理。样式继承、主题字体与直接格式共同决定有效外观；有XML属性不等于Word保存后生效。

列表标记位置、真实tab、正文起点和续行是四个关系，不能用普通空格替代。检查contextualSpacing是否压掉同样式段距；目标/MOC框、长框分页与短框整体保持分别验证。短标签或手动换行不能被两端对齐拉散。表格以本篇列角色决定对齐，不统一全部表头居中。

## Word rendering

**CORE_RULE.** When Microsoft Word Desktop is authoritative:

1. copy the generated DOCX to an isolated work copy;
2. open through the current verified, authorized Word invocation/profile, without globally changing security prompts;
3. resolve OMML and footnote actions, failing on missing/duplicate markers;
4. update every story field and TOC, repaginate, update page numbers, and save;
5. export PDF and decoded page images;
6. record Word version, page dimensions, pixel digests, and structural counts;
7. release COM objects and verify no new WINWORD process remains;
8. independently repeat only at the stable final gate; use scoped single-render iteration beforehand (see word_execution.md).

Compare the two final runs in content, dimensions and decoded pixels. Investigate nonzero differences; a specific human nonsemantic-difference acceptance does not establish a future tolerance. Source-to-target semantic and all-page visual gates remain necessary even when both renders agree. LibreOffice may diagnose but cannot satisfy a Word-authoritative gate.
