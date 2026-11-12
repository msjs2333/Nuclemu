# Contributing scientific artwork

Nuclemu uses two distinct image roles: course covers introduce a physical question; equipment cutouts identify the apparatus used to make a measurement. Keep the roles distinct when adding or revising assets. The [asset index](art-assets.md) records the initial pair and their limits.

## Course covers

Use one recognisable physical subject and a quiet background. Aim for a landscape 16:10 composition with important features inside an 8% safe region. The initial delivery size is 960 × 600 pixels. Review at 240 × 150 and 320 × 200 CSS pixels before accepting it for a four-column desktop catalog. A twelve-course contact sheet should have consistent visual weight, without relying on twelve different colors to identify the courses.

Avoid titles, formulas, scales, simulated measurements and small technical text inside the image. Course names and accessible descriptions belong in the interface. Do not treat a decorative track as a recorded event. When mixing nuclear and atomic scales, explicitly describe the picture as a qualitative, non-scale illustration. Any quantitative crystal plane, angle or geometry requires an independently checkable construction and review.

## Equipment cutouts

Match the existing equipment family: light grey powder-coated metal, restrained ivory panels, blue-grey blank display glass and graphite details. Use soft upper-left illumination with a shallow view of the top and right side. Prefer an almost orthographic camera over wide-angle perspective. Match a neighbouring instrument's silhouette, material and light direction before producing a full set.

Deliver real alpha transparency. Keep the whole enclosure, handles, connectors and feet inside the frame. Check the actual composite on white, light grey, dark grey and a checkerboard; a viewer's raw transparency preview is insufficient. Background color, checkerboards and status glows must not be baked into the cutout. Do not invent extra equipment, connectors or operating controls to fill space.

Keep display values blank. Fixed identifying marks such as A and B may be part of an equipment illustration, but operating labels and changing measurements must be drawn by the interface. A two-window housing is one instrument, not two detectors or two input chains. Decorative knobs do not establish supported operations.

The initial dual-window counter is 426 × 480 pixels, matching the existing counter canvas. Its measured body bounds and baseline are in [art-assets.json](../nuclemu/static/art-assets.json). A same-size file is not a drop-in geometric replacement: remeasure all connection and display anchors when integrating it. Do not apply `object-fit: cover` to equipment cutouts or stretch them to fit.

## Color, scale and layout

Keep equipment largely neutral. In covers, use color to distinguish physical subjects, consistently across courses. Encode particle paths and electrical signals with shape or line style as well as color. Warning, selection and application accent colors are interface decisions; artwork does not set the application's visual hierarchy.

An illustrated atom is not a scale reference for a nucleus. Nor does equal image height imply equal physical dimensions for two instruments. Publish physical dimensions only with a source. Otherwise use an explicit teaching-layout convention and align feet to a shared ground plane.

## Files and provenance

Put deliverable browser assets in `nuclemu/static/`, following the existing lowercase hyphenated naming convention. Use `cover-<course>.webp` for a new course cover and `rig-<equipment>-<variant>.webp` for an equipment variant. Keep existing public assets intact until a separate integration change intentionally replaces them. Record revisions and SHA-256 hashes in the asset index.

For each asset, record role, intended course or equipment, pixel dimensions, format, transparency, body bounds, baseline, display regions, source references, creation method, license scope and review state. Distinguish scientific references from visual reference inputs. Only claim authorship, commercial-model identity, measurements, permissions and review results that can be verified.

Retain working masters, exact prompts, alternate drafts and detailed review evidence in a local ignored workspace. The public index should contain the information needed to understand, reuse and review the delivered asset, without local paths or private discussions. AI-assisted creation should be disclosed; do not invent an exact generation model or seed when the tool did not supply one.

## Review and integration

1. Check the scientific story: particle identity, material structure, causal meaning and what the image cannot show. Cite the relevant public sources in the asset note.
2. Compare a new cutout beside the existing equipment family on a common ground line. Check the complete silhouette and both display windows at intended size.
3. Check pixels and formats: decoded dimensions, alpha range, transparent borders, image metadata and file hashes. Review four-background composites and actual-size thumbnails.
4. Have a separate reviewer inspect the artwork and its limitations. Keep review-ready candidates distinct from approved assets.
5. Integrate in a separate UI change. Check the target course or device identity, visible bounds, labels, connection anchors and crop at desktop teaching-lab window sizes and system scaling. Viewing an asset independently does not establish that UI integration has passed.

For desktop acceptance, record the actual window size and system/browser scaling. Representative review sizes are 1366 × 768, 1440 × 900 and 1920 × 1080. Mobile adaptation is outside this artwork baseline.
