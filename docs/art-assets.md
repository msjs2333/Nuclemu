# Scientific artwork assets

This initial pair supplies a physical-theme course cover and a transparent equipment variant. They are review-ready asset candidates. No application binding is included; the existing catalog and apparatus continue to use their existing assets until a separate integration change.

| File | Role | Dimensions | Transparency |
|---|---|---|---|
| [cover-alpha-energy-loss.webp](../nuclemu/static/cover-alpha-energy-loss.webp) | α energy-loss course cover | 960 × 600 | Opaque |
| [rig-counter-dual.webp](../nuclemu/static/rig-counter-dual.webp) | One counter with A/B windows | 426 × 480 | RGBA |

Machine-readable dimensions, body bounds, display regions and hashes are in [art-assets.json](../nuclemu/static/art-assets.json). Follow [the contributor guide](art-contributing.md) when extending the family.

## Alpha entering aluminium

The cover shows a compact four-sphere α symbol entering a simplified silver-blue aluminium structure. The two coral spheres represent protons and the two ochre spheres neutrons. An α particle contains two protons and two neutrons; see the [Australian Radiation Protection and Nuclear Safety Agency explanation](https://www.arpansa.gov.au/understanding-radiation/what-is-radiation/ionising-radiation/alpha-particles).

Aluminium is face-centred cubic. The material region uses an offset close-packed visual motif, but this generated perspective is not a verified crystallographic reconstruction and does not specify a crystal plane or lattice constant. The scientific structure reference is Nakashima, *The Crystallography of Aluminum and its Alloys* ([author's preprint](https://arxiv.org/abs/2002.01562)).

The particle-to-atom size ratio and four-sphere nuclear arrangement are schematic. The short streak indicates the intended direction; it does not encode speed, range, angular distribution, channeling or a sampled particle path. The diffuse blue material background is a visual convention, not a calculated electron-density map. The image does not measure or quantify energy loss. For physical definitions of electronic and nuclear stopping, see [NIST's STAR appendix](https://physics.nist.gov/PhysRefData/Star/Text/appendix.html).

Suggested accessible description: “A four-sphere alpha-particle symbol enters a simplified aluminium atomic structure. Qualitative illustration, not to scale.”

## One counter, two windows

The cutout depicts a fictional teaching instrument: one enclosure, one front panel and two equally prominent blank display windows, A at left and B at right. It does not document a commercial model, real-world dimensions, electrical wiring, input topology or implemented control functions. Its unmarked knobs are visual structure. Dynamic readings and operating controls must be supplied by a subsequent interface implementation.

The enclosure, material, corner screws, knobs, vents and shallow top/right camera view follow the project's existing [rig-counter.webp](../nuclemu/static/rig-counter.webp). The variant is a generated edit of that project asset. The existing file is retained. Do not reuse old display or connection coordinates without checking the new geometry; display inset polygons in the JSON index are conservative artwork regions, not tested text overlays.

Suggested accessible description: “A single light-grey teaching counter with blank A and B display windows.”

## Creation, sources and license scope

Both delivered images were made with OpenAI's built-in ImageGen tool in November 2026 and exported as lossless WebP with Pillow. The alpha cover was generated and revised; the counter was generated and revised using the existing project counter as its visual input. The tool did not supply an exact public model identifier or reproducible seed, so neither is asserted here.

The scientific webpages above were consulted for facts, not used as image inputs. No image or diagram from those sources is reproduced in this pair. The counter's only visual input was the already tracked project counter image.

These additions are supplied under the repository's [GNU GPL version 3 license](../LICENSE). This note does not claim exclusive human authorship or make a determination about the copyright status of AI-generated content. Retain the repository license and this provenance note when redistributing these files. Other repository assets keep their existing notices; this pair does not establish provenance for the entire asset collection.

## Checks performed

Decoded exports match the sizes above. The cover is opaque. The counter has alpha values from 0 to 255, all four outer image borders fully transparent, and one connected opaque-body component at alpha greater than 180/255. No EXIF, XMP or ICC profile was found in the counter export. Four-background composites were visually checked for edge halos and background rectangles.

The cover was inspected at 240 × 150, 320 × 200 and 384 × 240; the four-sphere particle remains distinguishable from the material. The counter was inspected at 160 × 180 and 213 × 240; both windows and A/B remain distinguishable. A common-baseline comparison with the existing counter, MCA and detector was inspected for material and camera consistency. These are asset checks, not UI-integration acceptance or an independent scientific approval.
