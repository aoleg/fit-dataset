# k2prep

k2prep takes a messy folder of mixed photographs and produces a small, clean,
bucket-tight training set for musubi-tuner's Krea 2 trainer: every accepted image
is cropped and resized onto one of 7 aspect ratios across 3 resolution tiers, so
the trainer sees at most 21 buckets instead of the 15+ an ordinary photo folder
scatters across.

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
run.bat "L:\train\photos" --threshold 6 --emit-toml
```

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
| `--force` | off | Overwrite existing outputs instead of skipping. |
| `--emit-toml` | off | Also write a ready-to-use musubi dataset TOML. |

`--report` and `--threshold` compose: `--report --threshold 7` shows what a
threshold-7 run *would* do without writing anything.

Use `--filter box` for heavily compressed sources. Box averaging suppresses 8×8
block artifacts more cleanly than Lanczos, which can ring on them.

Output goes to `<folder>/_prep/{1024,768,512}/`, flat, with `.txt` caption
sidecars copied alongside. Reports go to `<folder>/_prep/reports/`, timestamped
and never overwritten, so two threshold settings are diffable.

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

## Do not set `bucket_no_upscale = true`

The emitted TOML sets it to `false` and says so in a comment. Setting it `true`
bypasses the bucket list and gives each image its own dimensions floored to 16 —
which is exactly the bucket explosion this tool exists to prevent.

## Reading the bucket distribution

This is the section that tells you whether the exercise worked:

```
BUCKET DISTRIBUTION
  tier 1024
       1248x832 3:2       1,890
      1024x1024 1:1         902
       912x1136 4:5         197   *** WARNING: odd count, trailing batch of 1
       768x1360 9:16          3   *** WARNING: fewer than 8 images
```

Batches are formed per bucket, and `num_batches = ceil(len(bucket) / batch_size)`:

- **fewer than 8 images** — the bucket produces one or two tiny batches whose
  gradients are noisy relative to the rest of the run.
- **odd count** — always leaves a trailing batch of 1.

If the list still shows 15 populated buckets in one tier, something upstream is
wrong: check the TARGET BUCKETS table against the family list.

Either warning is worth acting on by adding or removing a few images of that
shape, not by changing `batch_size`.

## The D metric is uncalibrated

Four sub-metrics are scored 1–10 on fixed absolute scales, and the composite is
their **minimum**, not their mean — a quality fault is disqualifying, so
`--threshold 6` means "every available metric is at least 6".

- **Q** — estimated JPEG quality from the quantization tables. Lossless inputs
  score 10; encoders using non-standard tables (Adobe, several phone makers)
  report `n/a` and are excluded rather than guessed at.
- **B** — 8×8 DCT block edge strength. Unreliable for images rescaled after JPEG
  encoding, since the grid no longer aligns; those scores are marked `?`.
- **D** — detail, as high-frequency energy normalised by contrast.
- **R** — resolution headroom against the *assigned tier's* bucket, reported as a
  raw factor rather than scored.

**The D bands are a starting point and are explicitly uncalibrated.** They produce
genuine false positives on bokeh, fog, snow, and deliberately minimal
compositions. Run `--report` on your actual folder, read the QUALITY
DISTRIBUTION histogram — it covers every image that reached a tier, including
those below the threshold, so you can see what a different threshold would
recover — and adjust `D_BANDS` at the top of `k2prep.py` before trusting
`--threshold` to act on D.

## Tests

```bash
python test_k2prep.py
```

Covers the bucket generation port, the per-tier family table, and the geometry
half of the acceptance criteria.

## License

MIT.
