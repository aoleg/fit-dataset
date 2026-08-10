# k2prep

k2prep takes a messy folder of mixed photographs and produces a small, clean,
bucket-tight training set for musubi-tuner's Krea 2 trainer: every accepted image
is cropped and resized onto one of 7 aspect ratios across 3 resolution tiers, and
buckets too small to form a real batch are then consolidated into their nearest
healthy neighbour — so instead of the 15+ buckets an ordinary photo folder
scatters across, the trainer typically sees two or three per tier.

The output is a **filtered subset**, not a transformation of the whole folder.
Images that fail the quality threshold or are too small are skipped entirely, and
the source folder is never written to, moved within, or deleted from — the report
is the only record of a rejection.

## Install and run

```bash
install.bat
```

Then look before you leap:

```bash
run.bat "L:\train\photos" --report
```

and when the report looks right:

```bash
run.bat "L:\train\photos" --threshold 6
```

That is the whole workflow. One run scans, assigns buckets, consolidates the
undersized ones, renders and scores every image, writes the ones that pass along
with their captions, and emits `_prep/dataset.toml` ready to hand to
musubi-tuner.

**Run `--report` first.** It is a dry run: it analyses everything and writes a
report but no images. Because rejections leave no artifact on disk — nothing is
copied, moved or marked — the report is the only place a rejected file is ever
named. Recovering from too high a threshold means lowering it and re-running,
which is cheap (already-written images are skipped), but you cannot recover the
list of what was dropped after the fact if you never generated it.

Python 3.10+. Dependencies are Pillow, numpy and tqdm; nothing else.

## Options

```
k2prep.py <folder> [options]
```

| Option | Default | Meaning |
|---|---|---|
| `<folder>` | required | Input folder, positional. Non-recursive. |
| `--report` | off | Dry run. Analyse and write a report; write no images. |
| `--threshold N` | 0 | Process only images whose composite score ≥ N. 0 processes everything that fits a tier. Range 0–10. |
| `--png` | off | Write PNG instead of JPEG q97 4:4:4. |
| `--filter NAME` | `lanczos` | `lanczos`, `box`, `bicubic`, `bilinear`. |
| `--threads N` | 4 | Worker threads. Range 1–32. |
| `--force` | off | Overwrite existing outputs instead of skipping, and ignore the score cache. |
| `--no-merge` | off | Skip bucket consolidation; leave every image in the bucket its own aspect ratio picks. |
| `--single-pass` | off | Score the source and reject before rendering, instead of scoring the rendered result. |

`--report` and `--threshold` compose: `--report --threshold 7` shows what a
threshold-7 run *would* do without writing anything.

Use `--filter box` for heavily compressed sources. Box averaging suppresses 8×8
block artifacts more cleanly than Lanczos, which can ring on them.

Output goes to `<folder>/_prep/{1024,768,512}/`, flat, with `.txt` caption
sidecars copied alongside, plus `_prep/dataset.toml`. Every run writes two
timestamped reports to `<folder>/_prep/reports/`:

- `*-preliminary.txt` — the natural, per-family bucket assignment, before any
  consolidation and before anything is scored. This is the bucket explosion in
  its raw form.
- `*-final.txt` — what was actually written, with the rendered scores, what the
  merge pass moved, and what it could not.

Reports are never overwritten, so two threshold settings are diffable — and so
are the two stages of a single run.

`_prep/` belongs to k2prep. Each run makes the tier folders match its own plan
exactly: outputs left by an earlier run that the current one does not place
(because the threshold changed, or merging moved an image elsewhere) are removed
and listed under `SUPERSEDED OUTPUTS` in the final report. The source folder is
never touched, so anything removed is one re-run away from coming back.

## Why the output dimensions look arbitrary

The 1024-tier 4:3 bucket is **1184×880**, not 1168×880. That is not a rounding
error.

musubi-tuner generates a bucket list per resolution and assigns each image to the
nearest entry **by aspect ratio alone**. The list is not "any multiple of 16" —
it is produced by walking widths on a 16px grid and flooring `area // w` to 16,
which yields a specific set of 65 pairs at 1024 (49 at 768, 33 at 512). Rounding
`sqrt(area × AR)` to a multiple of 16 by hand gives values that look plausible and
are not in that list.

k2prep therefore generates its targets with musubi's own algorithm, ported
verbatim. If output dimensions do not match a real bucket exactly, the trainer
snaps by aspect ratio to a nearby bucket and applies a **second blind
center-crop** on top of ours — undoing the careful crop and silently discarding
edge content. When the dimensions do match, musubi skips its resize entirely
(`if bucket_reso == (image_width, image_height): return`) and our resampler is
the final word on what the VAE encoder sees.

The per-tier tables differ, because the 16px grid is coarser relative to a
smaller image — 9:16 is 768×1360 at the 1024 tier but 576×1024 at 768. `--report`
prints the full table it used.

## Bucket merging

Assigning every image to its nearest aspect-ratio family is the right first
answer, but on a real folder it leaves a long tail. A tier that looks like this
trains in batches of three no matter what `batch_size` says:

```
  tier 512
        512x512 1:1           5   *** WARNING: fewer than 8 images
        560x464 5:4           3   *** WARNING: fewer than 8 images
        384x672 9:16          1   *** WARNING: fewer than 8 images
        416x624 2:3           1   *** WARNING: fewer than 8 images
        448x576 4:5           1   *** WARNING: fewer than 8 images
```

So after the preliminary report and before anything is written, k2prep
consolidates buckets holding fewer than 8 images. Moved images are re-rendered
**from the original source**, never rescaled from an already-downsized output,
and go through the same crop-box code as everything else. The rules, in order:

1. **Same tier.** Move to the nearest healthy bucket (8+ images) by aspect ratio.
2. **One tier below.** Same test. Demotion costs 44% of the pixels, so it is only
   reached when no same-tier bucket will take the image.
3. **Rescue.** Images that no healthy bucket will take are pooled per tier, and
   if they total 8 they merge into whichever of their own buckets can absorb the
   most of them. This is what fixes the tier above: it becomes 10 in `512x512`
   plus the one 9:16 that would have needed a 43% crop.

A move is refused, and the image stays where it is, if it would:

- crop away more than **40%** of the source,
- leave the image too small to fill the destination within the upscale tolerance,
- or **flip the image between portrait and landscape**. That last one matters
  more than it looks: 4:5 and 5:4 are only 0.44 apart in linear aspect ratio, so
  without the rule a portrait photograph gets cropped into a landscape frame —
  which throws away the subject, not just the margins.

Everything the pass did is in the final report: a `MERGED` table with each move
and its before/after crop, a `STILL UNDERSIZED` table naming every image it left
behind and why, and a bucket distribution showing `was -> now`. Pass
`--no-merge` to turn it all off and get the raw per-family placement.

## Do not set `bucket_no_upscale = true`

The emitted TOML sets it to `false` and says so in a comment. Setting it `true`
bypasses the bucket list and gives each image its own dimensions floored to 16 —
which is exactly the bucket explosion this tool exists to prevent.

## Reading the bucket distribution

This is the section that tells you whether the exercise worked:

```
BUCKET DISTRIBUTION   (was -> now, across the merge)
  tier 1024
       1136x912 5:4         9 ->    16
       832x1248 2:3         2 ->    13   *** WARNING: odd count, trailing batch of 1
       768x1360 9:16        6 ->     0   (dissolved)
      1024x1024 1:1         3 ->     0   (dissolved)
```

Batches are formed per bucket, and `num_batches = ceil(len(bucket) / batch_size)`:

- **fewer than 8 images** — the bucket produces one or two tiny batches whose
  gradients are noisy relative to the rest of the run. Merging exists to remove
  these; any that survive it are listed under `STILL UNDERSIZED` with a reason.
- **odd count** — always leaves a trailing batch of 1. Merging does not chase
  this one: making a bucket even just makes another bucket odd. Add or drop a
  single image of that shape if it bothers you.

If the final report still shows a long list of populated buckets in one tier,
check the preliminary report first — if the two are identical, merging found
nothing it was allowed to move, and the reasons are in `STILL UNDERSIZED`.

## Quality is scored on the rendered image, not the source

Quality is resolution-dependent, so measuring the source tells you about pixels
the trainer never sees. Take one photograph, save it twice at JPEG q30 — once at
5056×3792, once at 1300×975 — and both land in the same 1136×912 bucket. They are
not the same training image:

| | source-scored (`--single-pass`) | rendered-scored (default) |
|---|---|---|
| 5056×3792 @ q30 | 1 | **10** |
| 1300×975 @ q30 | 1 | **2** |

The large one is downscaled 4×, which averages the 8×8 block edges away
completely; what reaches the VAE is clean. The small one arrives at roughly 1:1
and keeps every artifact it ever had. Scoring the source cannot tell them apart,
and rejects the good one.

So by default k2prep renders every image that fits a tier, scores that, and only
then writes the ones that pass. Rejected images are never written — the rendered
copy exists in memory only long enough to be measured.

- **D** — detail, as high-frequency energy normalised by contrast, on the
  rendered image. This carries most of the scoring.
- **B** — strength of the source's 8×8 block grid *where it survived the resize*.
  An 8px source block lands every `8 × scale` output pixels, so the metric looks
  for periodicity at that (usually fractional) period. Below 3 output pixels per
  block it reports `n/a` — not a gap in the measurement, the artifacts are
  genuinely gone. Only JPEG sources have a grid to look for.
- **Q~** — estimated JPEG quality from the source's quantization tables.
  **Reported only, deliberately excluded from the score.** It describes the
  source encode, which a downscale has already discarded. Letting it into a
  `min()` composite is exactly what made good high-resolution material score 1.
- **R** — resolution headroom against the assigned tier's bucket, a raw factor
  rather than a score.

The composite is the **minimum** of the metrics that apply, so `--threshold 6`
means "every available metric is at least 6".

`--single-pass` restores the old behaviour: Q, B and D measured on the source,
and the threshold applied before anything is rendered. It is faster and it is
what you want if you already know your sources are uniform in resolution.

### Cost, and the score cache

The default mode renders each image twice on a first run — once to score, once
to write. Scores do not depend on `--threshold`, so they are cached in
`_prep/scores.json`, keyed on file size and mtime. Re-running at a different
threshold reuses every score and rewrites only what changed, which makes the
tune-and-re-run loop essentially free. Delete the file to force a rescore;
`--force` ignores it.

### The bands are uncalibrated

**Both band tables are a starting point and are explicitly uncalibrated.** They
were fitted against a 29-image reference folder and a controlled quality sweep,
which is better than nothing and a long way from calibrated. D in particular
produces genuine false positives on bokeh, fog, snow, and deliberately minimal
compositions.

Run `--report` on your actual folder and read the QUALITY DISTRIBUTION histogram
in the final report — it covers every image that reached a tier, including those
below the threshold, so you can see what a different threshold would recover.
Then adjust `D_RENDERED_BANDS` and `B_RENDERED_BANDS` at the top of `k2prep.py`
before trusting `--threshold` to act on them.

## Tests

```bash
python test_k2prep.py
```

Covers the bucket generation port, the per-tier family table, the geometry half
of the acceptance criteria, the merge rules, and the rendered-image metrics.

## License

MIT.
