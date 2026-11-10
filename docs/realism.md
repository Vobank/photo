# Realistic people

Faces are where generated photos give themselves away: model-perfect, symmetrical,
airbrushed. With **Auto** (or the **Photoreal** style) and people in the request,
Photo now asks for a raw, unedited photo and real skin:

> raw unedited photo, natural uneven light, real skin with visible pores and natural
> imperfections, natural hair with flyaways, candid unposed moment, true-to-life colors

Other photographic looks (cinematic, film, noir, …) add a short version of it when
people are in the picture. Nothing changes for scenes without people.

## How it was chosen

Same seeds, same scenes (an old woman cooking, a man in the subway, a family dinner
in a garden, a woman in the rain), RTX 5080:

| Variant | Result | Time |
|---|---|---|
| Previous photo recipe (Klein) | Model-like faces, airbrushed skin. | 1.4 s |
| "Raw smartphone photo" + wrinkles, blemishes, clutter | Very real faces, but everyone aged (a family became four old men) and scenes got dirty. | 1.4 s |
| "iPhone / smartphone" wording | Selfie framing and wide-angle distortion; faces still idealised. | 1.5 s |
| Film-stock wording | Natural colour, faces still a little idealised. | 1.5 s |
| **Raw photo + real skin, without age or dirt words (chosen)** | Ordinary-looking people of the right age, real skin texture at 100 %. | 1.4 s |
| Same + second pass at 1.5× | More texture but harsh, "crunchy" skin that ages faces. | 2.6 s |
| Z-Image (base, non-distilled) + negative prompt | The grittiest documentary look, but ages people, roughens skin, drifts to East-Asian faces for neutral prompts. | ~38 s |

Two traps found along the way:

* **Skin words without people add people.** "Real skin with pores" put a woman in
  front of a mountain lake. The recipe is used only when the request mentions people
  (`styles.mentions_people`, English and Russian).
* **Translation lost gender.** "подруги" (female friends) became "friends" and a man
  appeared. The classification step now keeps every person's gender and age.

## Image quality: noise, flatness, resolution

The first realism recipe made pictures look *real* but technically poor: visible
grain, a milky low-contrast haze and soft, smeared detail at 1 MP. Same seeds again:

| Variant | Result | Time |
|---|---|---|
| Old photo recipe ("unretouched", "imperfections", "sensor grain") | Noisy, washed out, flat. | 1.5 s |
| **Clean recipe**: crisp detail, deep contrast, depth, directional light, no noise | Vivid, three-dimensional, clean. | 1.5 s |
| Clean recipe, native **1584 px (~2.4 MP)** | Big jump in fine detail (foliage, stone, eyes, hair). | ~3 s |
| Clean recipe, native 2048 px | A little more detail. | ~6.5 s |
| 1 MP + upscale + refine to 2048 px | Detail similar to native, keeps the 1 MP composition. | ~7.5 s |
| Same recipe on Z-Image Turbo | Drew **a camera into the scene** from "full-frame camera, prime lens". | 11 s |

Consequences: the photo recipe asks for crisp, deep, clean images and names no camera
equipment; the people recipe keeps real skin but adds sharp focus and depth; the
studio's default size is now XL (~2.4 MP).
