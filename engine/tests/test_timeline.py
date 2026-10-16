import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from claudebolt.config import DetectionSettings
from claudebolt.timeline import refine
from claudebolt.timeline.model import (
    Project,
    Segment,
    Source,
    Track,
    normalize,
    output_to_source,
    source_to_output,
)
from claudebolt.timeline.ops import Conflict, Editor, Lock, SetRange


def project(dur=10.0) -> Project:
    s = Source(id="s0", path="x.wav", kind="audio", duration=dur)
    return Project(sources=[s], tracks=[Track(id="t0", source_id="s0")],
                   segments=[Segment(start=0, end=dur)])


# ---- refine steps (table tests)
def test_runs():
    a = np.array([0, 1, 1, 0, 0, 1, 0, 1, 1], bool)
    assert refine.runs(a, 1.0) == [(1.0, 3.0), (5.0, 6.0), (7.0, 9.0)]


@pytest.mark.parametrize("g,exp", [(0.5, [(0, 3)]), (0.4, [(0, 1), (1.5, 3)]), (0, [(0, 1), (1.5, 3)])])
def test_grace(g, exp):
    assert refine.grace([(0, 1), (1.5, 3)], g) == [tuple(map(float, x)) for x in exp]


def test_pad_clamps():
    got = refine.pad([(0.0, 1.0), (4.9, 5.0)], 0.1, 0.2, 5.0)
    assert [x for iv in got for x in iv] == pytest.approx([0.0, 1.2, 4.8, 5.0])


def test_merge_and_min_keep():
    assert refine.merge([(0, 1), (0.5, 2), (3, 4)]) == [(0, 2), (3, 4)]
    assert refine.min_keep([(0, 0.5), (1, 2)], 0.75) == [(1, 2)]


def test_complete_tiles():
    cfg = DetectionSettings()
    segs = refine.complete([(1, 2), (3, 4)], 5.0, cfg)
    assert [(s.op, s.start, s.end) for s in segs] == [
        ("remove", 0, 1), ("keep", 1, 2), ("remove", 2, 3), ("keep", 3, 4), ("remove", 4, 5)]


def test_speed_action():
    cfg = DetectionSettings(silence_action="speed", speed_rate=3.0)
    segs = refine.complete([(1, 2)], 3.0, cfg)
    assert segs[0].op == "speed" and segs[0].speed == 3.0


def test_refine_all_silent_keeps_everything():
    segs = refine.refine(np.zeros(100, bool), 4.0, DetectionSettings())
    assert len(segs) == 1 and segs[0].op == "keep"


# ---- normalize
def test_normalize_fills_gaps_and_merges():
    segs = normalize([Segment(start=1, end=2, op="remove", reason="manual"),
                      Segment(start=2, end=3, op="remove", reason="manual")], 5.0)
    assert [(s.op, s.start, s.end) for s in segs] == [
        ("keep", 0, 1), ("remove", 1, 3), ("keep", 3, 5)]


@given(st.lists(st.tuples(st.floats(0, 10), st.floats(0, 10), st.sampled_from(["keep", "remove"])),
                max_size=8))
def test_normalize_idempotent_and_tiles(items):
    segs = [Segment(start=min(a, b), end=max(a, b), op=o) for a, b, o in items]
    n1 = normalize(segs, 10.0)
    n2 = normalize(n1, 10.0)
    assert [(s.start, s.end, s.op) for s in n1] == [(s.start, s.end, s.op) for s in n2]
    assert n1[0].start == 0 and n1[-1].end == 10.0
    assert all(a.end == b.start for a, b in zip(n1, n1[1:]))


# ---- ops / undo
@settings(max_examples=60, deadline=None)
@given(st.lists(st.tuples(st.floats(0, 10), st.floats(0, 10),
                          st.sampled_from(["keep", "remove", "speed"])), min_size=1, max_size=6))
def test_undo_restores_exactly(items):
    p = project()
    ed = Editor(p)
    snap = [s.model_dump() for s in p.segments]
    n = 0
    for a, b, op in items:
        lo, hi = min(a, b), max(a, b)
        if hi - lo < 0.01:
            continue
        ed.apply([SetRange(start=lo, end=hi, op=op, speed=2.0)])
        n += 1
    for _ in range(n):
        ed.undo()
    assert [s.model_dump() for s in p.segments] == snap


def test_redo_and_version():
    p = project()
    ed = Editor(p)
    ed.apply([SetRange(start=1, end=2, op="remove")])
    assert p.version == 1 and p.output_duration == 9.0
    ed.undo()
    assert p.output_duration == 10.0
    ed.redo()
    assert p.output_duration == 9.0


def test_version_conflict():
    p = project()
    ed = Editor(p)
    ed.apply([SetRange(start=1, end=2, op="remove")])
    with pytest.raises(Conflict) as c:
        ed.apply([SetRange(start=3, end=4, op="remove")], expected_version=0)
    assert c.value.version == 1


def test_locked_ranges_survive_edits():
    p = project()
    ed = Editor(p)
    ed.apply([SetRange(start=2, end=4, op="keep"), Lock(start=2, end=4)])
    ed.apply([SetRange(start=0, end=10, op="remove")])
    assert p.output_duration == pytest.approx(2.0)


# ---- time mapping
def test_time_mapping_roundtrip():
    segs = [Segment(start=0, end=2), Segment(start=2, end=4, op="remove"),
            Segment(start=4, end=6, op="speed", speed=2.0), Segment(start=6, end=8)]
    assert source_to_output(segs, 1) == 1
    assert source_to_output(segs, 3) == 2  # removed collapses
    assert source_to_output(segs, 5) == 2.5
    assert source_to_output(segs, 7) == 4
    assert output_to_source(segs, 2.5) == pytest.approx(5.0)
    assert output_to_source(segs, 3.5) == pytest.approx(6.5)
