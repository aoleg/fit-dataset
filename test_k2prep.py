#!/usr/bin/env python3
"""Unit tests for k2prep's bucket and geometry logic.

Plain asserts, no pytest dependency:

    python test_k2prep.py

Covers SPEC.md section 4.2 (the bucket list must match musubi-tuner exactly),
section 4.3 (the per-tier family table), and the pure-function half of the
acceptance criteria in section 12.
"""

import k2prep as k


def test_bucket_list_sizes():
    assert len(k.generate_buckets(1024)) == 65
    assert len(k.generate_buckets(768)) == 49
    assert len(k.generate_buckets(512)) == 33


def test_musubi_exact_dimensions():
    """4:3 at 1024 is 1184x880. Rounding sqrt(area * AR) to a multiple of 16
    gives 1168x880, which is not a bucket and would make the trainer re-crop."""
    buckets = k.generate_buckets(1024)
    assert (1184, 880) in buckets
    assert (1168, 880) not in buckets


def test_family_table():
    """The per-tier dimensions in SPEC.md section 4.3, verbatim."""
    expected = {
        "9:16": [(768, 1360), (576, 1024), (384, 672)],
        "2:3":  [(832, 1248), (624, 944), (416, 624)],
        "4:5":  [(912, 1136), (688, 848), (448, 576)],
        "1:1":  [(1024, 1024), (768, 768), (512, 512)],
        "5:4":  [(1136, 912), (848, 688), (560, 464)],
        "3:2":  [(1248, 832), (944, 624), (624, 416)],
        "16:9": [(1360, 768), (1024, 576), (672, 384)],
    }
    for family, rows in expected.items():
        for tier, want in zip(k.TIERS, rows):
            assert k.bucket_for(tier, family) == want, (family, tier)


def test_every_bucket_is_a_real_bucket():
    """Acceptance criterion 3, at the source: every dimension this tool can emit
    is present in the tier's generated list."""
    for tier in k.TIERS:
        buckets = set(k.generate_buckets(tier))
        for family in k.AR_FAMILIES:
            assert k.bucket_for(tier, family) in buckets


def test_family_assignment():
    assert k.assign_family(1.5) == "3:2"
    assert k.assign_family(1.0) == "1:1"
    assert k.assign_family(4.0) == "16:9"        # 21:9+ is cropped hard, on purpose
    assert k.assign_family(640 / 480) == "5:4"
    assert k.assign_family(1080 / 2340) == "9:16"


def test_panorama_demotes_on_post_crop_area():
    """Acceptance criterion 5. 2400x600 is 1.44 MP raw but 0.64 MP after the
    16:9 crop, so it belongs in 768, not 1024."""
    tier, bucket, crop = k.assign_tier(2400, 600, k.assign_family(4.0))
    assert tier == 768
    assert bucket == (1024, 576)
    assert crop == (1067, 600)


def test_small_camera_image_lands_in_512():
    """Acceptance criterion 6."""
    tier, bucket, crop = k.assign_tier(640, 480, k.assign_family(640 / 480))
    assert tier == 512
    assert bucket == (560, 464)


def test_thumbnail_is_too_small():
    """Acceptance criterion 7."""
    assert k.assign_tier(400, 300, k.assign_family(400 / 300)) is None


def test_upscale_tolerance_boundary():
    """A source exactly at the tolerance limit fits; one pixel under does not."""
    bw, bh = k.bucket_for(1024, "1:1")
    limit = (bw * bh) / k.UPSCALE_TOLERANCE ** 2  # 792,874.1
    assert 891 * 891 >= limit > 890 * 890
    assert k.assign_tier(891, 891, "1:1")[0] == 1024
    assert k.assign_tier(890, 890, "1:1")[0] == 768


def test_crop_dims_minimal():
    assert k.crop_dims(6000, 4000, 1248 / 832) == (6000, 4000)   # already 3:2
    assert k.crop_dims(2400, 600, 1024 / 576) == (1067, 600)     # trim width
    assert k.crop_dims(1000, 2000, 1.0) == (1000, 1000)          # trim height


def test_crop_box_anchoring():
    """Horizontal centred always; vertical biased to 1/3 for portrait targets."""
    left, top, right, bottom = k.crop_box(1000, 2000, 1.0)       # square target
    assert (left, right) == (0, 1000)
    assert (top, bottom) == (500, 1500)                          # centred

    left, top, right, bottom = k.crop_box(1000, 2000, 768 / 1360)  # portrait
    cw = right - left
    ch = bottom - top
    assert (cw, ch) == k.crop_dims(1000, 2000, 768 / 1360)
    assert left == (1000 - cw) // 2
    assert top == int((2000 - ch) * (1 / 3))                     # above centre

    # Never outside the source.
    for w, h in ((3, 5000), (5000, 3), (1, 1), (17, 19)):
        for family in k.AR_FAMILIES:
            bw, bh = k.bucket_for(1024, family)
            l, t, r, b = k.crop_box(w, h, bw / bh)
            assert 0 <= l < r <= w and 0 <= t < b <= h, (w, h, family)


def test_jpeg_quality_estimator():
    """An exact IJG-scaled table must round-trip to its own quality."""
    for q in (30, 50, 75, 85, 90, 95, 97):
        assert k.estimate_jpeg_quality(k._ijg_scaled_table(q)) == q
    # A wildly non-standard table is rejected rather than guessed at.
    assert k.estimate_jpeg_quality([1] * 32 + [255] * 32) is None
    assert k.estimate_jpeg_quality([16] * 63) is None            # wrong length


def test_score_bands_are_absolute():
    assert k.score_q(100) == 10 and k.score_q(95) == 9 and k.score_q(54) == 1
    assert k.score_q(None) is None
    assert k.score_b(1.00) == 10 and k.score_b(1.20) == 7 and k.score_b(3.0) == 1
    assert k.score_d(0.10) == 10 and k.score_d(0.026) == 6 and k.score_d(0.0) == 1


def test_needed_area_matches_spec_table():
    """SPEC.md section 4.1, minimum post-crop area per tier (square family)."""
    assert k.needed_area(1024, "1:1") == 792874
    assert k.needed_area(768, "1:1") == 445991
    assert k.needed_area(512, "1:1") == 198218


def main():
    tests = [v for name, v in sorted(globals().items()) if name.startswith("test_")]
    failed = 0
    for fn in tests:
        try:
            fn()
        except AssertionError as exc:
            failed += 1
            print(f"FAIL  {fn.__name__}: {exc}")
        else:
            print(f"ok    {fn.__name__}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
