# Scientific artwork assets

This collection supplies two physical-theme course covers and a transparent equipment variant. They are review-ready assets. Application bindings are delivered and checked separately from the artwork change.

| File | Role | Dimensions | Transparency |
|---|---|---|---|
| [cover-alpha-energy-loss.webp](../nuclemu/static/cover-alpha-energy-loss.webp) | α energy-loss course cover | 960 × 600 | Opaque |
| [cover-beta-absorption.webp](../nuclemu/static/cover-beta-absorption.webp) | β transmission/absorption course cover | 960 × 600 | Opaque |
| [rig-counter-dual.webp](../nuclemu/static/rig-counter-dual.webp) | One counter with A/B windows | 426 × 480 | RGBA |

Machine-readable dimensions, body bounds, display regions and hashes are in [art-assets.json](../nuclemu/static/art-assets.json). Follow [the contributor guide](art-contributing.md) when extending the family.

## Alpha entering aluminium

The cover shows a compact four-sphere α symbol entering a simplified silver-blue aluminium structure. The two coral spheres represent protons and the two ochre spheres neutrons. An α particle contains two protons and two neutrons; see the [Australian Radiation Protection and Nuclear Safety Agency explanation](https://www.arpansa.gov.au/understanding-radiation/what-is-radiation/ionising-radiation/alpha-particles).

Aluminium is face-centred cubic. The material region uses an offset close-packed visual motif, but this generated perspective is not a verified crystallographic reconstruction and does not specify a crystal plane or lattice constant. The scientific structure reference is Nakashima, *The Crystallography of Aluminum and its Alloys* ([author's preprint](https://arxiv.org/abs/2002.01562)).

The particle-to-atom size ratio and four-sphere nuclear arrangement are schematic. The short streak indicates the intended direction; it does not encode speed, range, angular distribution, channeling or a sampled particle path. The diffuse blue material background is a visual convention, not a calculated electron-density map. The image does not measure or quantify energy loss. For physical definitions of electronic and nuclear stopping, see [NIST's STAR appendix](https://physics.nist.gov/PhysRefData/Star/Text/appendix.html).

Suggested accessible description: “A four-sphere alpha-particle symbol enters a simplified aluminium atomic structure. Qualitative illustration, not to scale.”

## Beta transmission through aluminium

The beta cover uses separate single spheres as electron symbols, rather than the four-sphere alpha symbol. Three separated aluminium sheets and a progressively sparser forward-going stream introduce the absorption experiment. A few curved streaks suggest deflection. Beta-minus particles are electrons, and thin metal layers can reduce their transmission; see the [NRC teaching resource](https://www.nrc.gov/education-regulatory-research/the-student-corner/unit-1-radiation). [NIST ESTAR](https://physics.nist.gov/PhysRefData/Star/Text/ESTAR.html) provides stopping-power and range information for electrons.

The sheets are separated and their apparent thickness exaggerated for readability. Particle sizes, counts, gaps and paths are symbolic. Neither their number nor the spacing of the sheets gives a transmission probability, energy, stopping range, mass thickness or attenuation law. Curved streaks are not sampled scattering angles or locations: the gaps separate the illustration's elements and do not assert specific motion or scattering in air. No measured events, instrument readings or source-energy distribution are encoded in this cover.

Suggested accessible description: “Single-electron symbols pass through aluminium absorber layers; fewer continue forward. Qualitative cross-scale illustration, not to scale.” Keep the complete 16:10 image visible, including both the incoming and transmitted populations. Cropping either side can remove the distinction that explains the experiment.

## One counter, two windows

The cutout depicts a fictional teaching instrument: one enclosure, one front panel and two equally prominent blank display windows, A at left and B at right. It does not document a commercial model, real-world dimensions, electrical wiring, input topology or implemented control functions. Its unmarked knobs are visual structure. Dynamic readings and operating controls must be supplied by a subsequent interface implementation.

The enclosure, material, corner screws, knobs, vents and shallow top/right camera view follow the project's existing [rig-counter.webp](../nuclemu/static/rig-counter.webp). The variant is a generated edit of that project asset. The existing file is retained. Do not reuse old display or connection coordinates without checking the new geometry; display inset polygons in the JSON index are conservative artwork regions, not tested text overlays.

Suggested accessible description: “A single light-grey teaching counter with blank A and B display windows.”

## Creation, sources and license scope

All three images were made with OpenAI's built-in ImageGen tool in November 2026 and exported as lossless WebP with Pillow. The alpha cover was generated and revised; the beta cover used the alpha cover only as a lighting, material and palette reference. The counter was generated and revised using the existing project counter as its visual input. The tool did not supply an exact public model identifier or reproducible seed, so neither is asserted here.

The scientific webpages above were consulted for facts, not used as image inputs. No image or diagram from those sources is reproduced in these assets. The counter's only visual input was the already tracked project counter image.

These additions are supplied under the repository's [GNU GPL version 3 license](../LICENSE). This note does not claim exclusive human authorship or make a determination about the copyright status of AI-generated content. Retain the repository license and this provenance note when redistributing these files. Other repository assets keep their existing notices; these three files do not establish provenance for the entire asset collection.

## Checks performed

Decoded exports match the sizes above. The cover is opaque. The counter has alpha values from 0 to 255, all four outer image borders fully transparent, and one connected opaque-body component at alpha greater than 180/255. No EXIF, XMP or ICC profile was found in the counter export. Four-background composites were visually checked for edge halos and background rectangles.

The alpha cover was inspected at 240 × 150, 320 × 200 and 384 × 240; the four-sphere particle remains distinguishable from the material. The beta cover was inspected at 240 × 150, 306 × 191 and 320 × 200; the aluminium sheets, single-particle symbols and sparser transmitted population remain distinguishable. The counter was inspected at 160 × 180 and 213 × 240; both windows and A/B remain distinguishable. A common-baseline comparison with the existing counter, MCA and detector was inspected for material and camera consistency. These are asset checks, not UI-integration acceptance or an independent scientific approval.
