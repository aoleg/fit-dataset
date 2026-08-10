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


# ---------------------------------------------------------------------------
# Bucket merging
# ---------------------------------------------------------------------------

def _mk(name, w, h):
    """A Result placed in its natural bucket, as analyse() would leave it."""
    from pathlib import Path
    res = k.Result(path=Path(name), name=name)
    res.src_w, res.src_h, res.src_ar = w, h, w / h
    res.family = k.assign_family(res.src_ar)
    fit = k.assign_tier(w, h, res.family)
    assert fit is not None, (name, w, h)
    k.place(res, fit[0], fit[1])
    res.status = k.ST_ACCEPTED
    return res


def test_orientation_is_never_flipped():
    portrait, square, landscape = (912, 1136), (1024, 1024), (1136, 912)
    assert k.orientation_ok(0.75, portrait)
    assert k.orientation_ok(0.75, square)
    assert not k.orientation_ok(0.75, landscape)
    assert k.orientation_ok(1.5, landscape)
    assert k.orientation_ok(1.5, square)
    assert not k.orientation_ok(1.5, portrait)
    assert k.orientation_ok(1.0, portrait) and k.orientation_ok(1.0, landscape)


def test_ar_distance_is_symmetric_in_log_space():
    """0.8 -> 1:1 and 1.25 -> 1:1 are the same move mirrored, so they must
    measure the same. Linear ratio distance gets this wrong (0.20 vs 0.25)."""
    square = (1024, 1024)
    assert abs(k.ar_distance(0.8, square) - k.ar_distance(1.25, square)) < 1e-9
    assert abs(0.8 - 1.0) != abs(1.25 - 1.0)          # the flaw being avoided


def test_crop_cap_refuses_a_brutal_move():
    tall = _mk("phone.png", 1080, 2340)             # 9:16, AR 0.46
    ok, why = k.can_accept(tall, k.bucket_for(1024, "4:5"))
    assert not ok and why == "crop", why
    ok, _ = k.can_accept(tall, k.bucket_for(1024, "2:3"))
    assert ok                                        # 31%, under the cap


def test_rescue_merges_an_orphan_512_tier():
    """The 5/3/1/1/1 shape that has no healthy bucket to aim at."""
    images = ([_mk(f"sq_{i}.jpg", 600, 600) for i in range(5)] +
              [_mk(f"cam_{i}.jpg", 640, 480) for i in range(3)] +
              [_mk("tall_916.jpg", 400, 700),
               _mk("tall_23.jpg", 480, 720),
               _mk("tall_45.jpg", 450, 580)])
    assert all(r.tier == 512 for r in images)
    assert max(k.bucket_counts(images).values()) == 5      # nothing healthy

    moves, unmerged, _before, after = k.plan_merge(images)

    assert after[(512, (512, 512))] == 10
    assert after[(512, (384, 672))] == 1                   # 43% crop, left alone
    assert len(moves) == 5
    assert [r.name for r, _why in unmerged] == ["tall_916.jpg"]


def test_merge_never_flips_orientation():
    images = ([_mk(f"port_{i}.jpg", 3024, 4032) for i in range(3)] +
              [_mk(f"land_{i}.jpg", 4032, 3024) for i in range(9)])
    k.plan_merge(images)
    for r in images:
        assert k.orientation_ok(r.src_ar, r.bucket), r.name


def test_healthy_buckets_are_left_alone():
    images = [_mk(f"land_{i}.jpg", 4032, 3024) for i in range(12)]
    before = k.bucket_counts(images)
    moves, unmerged, _b, after = k.plan_merge(images)
    assert not moves and not unmerged
    assert dict(before) == after


def test_too_few_images_cannot_be_rescued():
    """Five images cannot make a bucket of eight, so nothing is cropped for
    nothing."""
    images = [_mk("sq.jpg", 600, 600), _mk("cam.jpg", 640, 480),
              _mk("t1.jpg", 480, 720), _mk("t2.jpg", 450, 580),
              _mk("t3.jpg", 400, 700)]
    moves, unmerged, _b, _a = k.plan_merge(images)
    assert not moves
    assert len(unmerged) == 5


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
