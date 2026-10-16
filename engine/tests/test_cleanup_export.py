import json
from xml.dom import minidom

import pytest
from lxml import etree

from claudebolt.cleanup.false_starts import detect_false_starts
from claudebolt.cleanup.fillers import detect_fillers
from claudebolt.cleanup.normalize import norm
from claudebolt.cleanup.proposals import run_cleanup
from claudebolt.cleanup.retakes import detect_retakes
from claudebolt.config import CleanupSettings
from claudebolt.service import Service, ServiceError
from claudebolt.timeline.model import Word
from claudebolt.transcribe.sentences import build, import_json, import_srt


def words(text: str, gap: float = 0.05, dur: float = 0.3) -> list[Word]:
    out, t = [], 0.0
    for tok in text.split():
        out.append(Word(text=tok, start=round(t, 3), end=round(t + dur, 3)))
        t += dur + gap
    return out


CFG = CleanupSettings()


def test_norm():
    assert norm("Ummm,") == "um" and norm("UHHH") == "uh" and norm("Hmmm") == "hmm"
    assert norm("don\u2019t") == "don't" and norm("you're") == "your"


def test_fillers_always_vs_context():
    w = words("so I um think like it works you know right")
    d = {(x.word_start, x.word_end): x for x in detect_fillers(w, CFG)}
    assert d[(2, 2)].confidence == 0.95  # um
    assert d[(0, 0)].confidence >= 0.6  # sentence-initial so
    assert (7, 8) in d  # "you know" phrase
    assert d[(4, 4)].confidence < 0.8  # context-dependent "like"


def test_like_with_pauses_boosted():
    w = words("it was like great")
    base = detect_fillers(w, CFG)[0].confidence
    w[2].start += 0.3
    w[2].end += 0.3
    for x in w[3:]:
        x.start += 0.6
        x.end += 0.6
    assert detect_fillers(w, CFG)[0].confidence > base


def test_false_start_repeats_and_cutoffs():
    w = words("I I think we should should go to the kno- knowledge base")
    d = detect_false_starts(w)
    ranges = {(x.word_start, x.word_end) for x in d}
    assert (0, 0) in ranges and (4, 4) in ranges
    assert any(x.note.startswith("cut-off") for x in d)
    two = words("we can we can start")
    assert (0, 1) in {(x.word_start, x.word_end) for x in detect_false_starts(two)}


def test_retake_similar_sentence():
    w = words("This is the intro to the show today friends. Uh let me try that again. "
              "This is the intro to our show today friends.")
    tr = build(w, "t", "en")
    d = detect_retakes(tr.words, tr.sentences, CFG)
    assert d and d[0].word_start == 0 and d[0].kind == "retake"


def test_retake_prefix_rule():
    w = words("Welcome to the. Welcome to the channel where we talk about editing.")
    tr = build(w, "t", "en")
    assert [x.confidence for x in detect_retakes(tr.words, tr.sentences, CFG)] == [0.75]


def test_proposals_never_reach_into_neighbours():
    tr = build(words("hello um world", gap=0.2), "t", "en")
    props = run_cleanup(tr, CFG, 5.0, ["filler"])
    assert len(props) == 1
    p = props[0]
    assert p.start >= tr.words[0].end and p.end <= tr.words[2].start
    assert p.start < tr.words[1].start and p.end > tr.words[1].end


def test_sentences_split_on_pause_and_punct():
    w = words("one two. three four", gap=0.05)
    assert build(w, "t", "en").sentences == [(0, 1), (2, 3)]
    w2 = words("one two three four")
    w2[2].start += 1.0
    w2[2].end += 1.0
    w2[3].start += 1.0
    w2[3].end += 1.0
    assert build(w2, "t", "en").sentences == [(0, 1), (2, 3)]


def test_import_transcripts(tmp_path):
    j = tmp_path / "t.json"
    j.write_text(json.dumps([{"word": "hi", "start": 0, "end": 0.5}]))
    assert len(import_json(j).words) == 1
    s = tmp_path / "t.srt"
    s.write_text("1\n00:00:01,000 --> 00:00:03,000\nhello there friend\n")
    t = import_srt(s)
    assert len(t.words) == 3 and t.words[0].start == pytest.approx(1.0)


# ---- end-to-end on a fixture with an injected transcript (no whisper needed)
@pytest.fixture
def svc_with_transcript(media):
    svc = Service()
    pid = svc.open_media([str(media / "pattern.wav")])["id"]
    w = [Word(text="Hello", start=0.1, end=0.4), Word(text="um", start=0.5, end=0.8),
         Word(text="world.", start=0.9, end=1.1), Word(text="Again", start=3.0, end=3.4),
         Word(text="there.", start=3.8, end=4.4)]
    svc.set_transcript(pid, build(w, "test", "en"))
    return svc, pid


def test_cleanup_flow_and_undo(svc_with_transcript):
    svc, pid = svc_with_transcript
    svc.detect_silence(pid)
    before = svc.project(pid).output_duration
    r = svc.run_cleanup(pid, ["filler"])
    assert r["created"] == {"filler": 1}
    props = svc.list_proposals(pid)["proposals"]
    assert props[0]["text"] == "um" and "context_before" in props[0]
    res = svc.accept_proposals(pid, selector={"kind": "filler", "min_confidence": 0.8})
    assert res["accepted"] == 1
    assert svc.project(pid).output_duration < before
    svc.undo(pid)
    assert svc.project(pid).output_duration == pytest.approx(before)
    assert svc.project(pid).proposals[0].status == "pending"


def test_cut_words_and_search(svc_with_transcript):
    svc, pid = svc_with_transcript
    m = svc.search_transcript(pid, "world")["matches"]
    assert m[0]["word_range"] == [2, 2]
    out = svc.apply_edits(pid, [{"action": "remove", "word_range": [1, 1]}], actor="agent")
    assert out["output_duration"] < 5.7
    seg = [s for s in svc.project(pid).segments if s.op == "remove"][0]
    assert seg.reason == "manual" and seg.start < 0.5 and seg.end > 0.8
    t = svc.get_transcript(pid)
    assert t["words"][1]["removed"] is True


def test_apply_edits_conflict_and_time_base(svc_with_transcript):
    svc, pid = svc_with_transcript
    v = svc.project(pid).version
    svc.apply_edits(pid, [{"action": "remove", "start": 1, "end": 2}], expected_version=v)
    c = svc.apply_edits(pid, [{"action": "remove", "start": 3, "end": 4}], expected_version=v)
    assert c["conflict"] and c["version"] == v + 1
    r = svc.apply_edits(pid, [{"action": "remove", "start": 0.0, "end": 0.5}], time_base="output")
    assert r["applied"]
    with pytest.raises(ServiceError):
        svc.apply_edits(pid, [{"action": "dance", "start": 0, "end": 1}])
    assert svc.map_time(pid, 5.0, "source")["output"] < 5.0


# ---- exports
def _service_with_cuts(media, name):
    svc = Service()
    pid = svc.open_media([str(media / name)])["id"]
    svc.detect_silence(pid)
    return svc, pid


@pytest.mark.parametrize("name", ["pattern.mp4", "pattern.wav"])
@pytest.mark.parametrize("fmt", ["fcpxml", "xmeml", "edl", "audacity", "cutlist"])
def test_exports_valid(media, name, fmt, tmp_path):
    svc, pid = _service_with_cuts(media, name)
    path = svc.export(pid, fmt, str(tmp_path / f"x.{fmt}"))["path"]
    text = open(path, encoding="utf-8").read()
    if fmt in ("fcpxml", "xmeml"):
        root = etree.fromstring(text.encode())  # well-formed
        if fmt == "fcpxml":
            assert root.get("version") == "1.11"
            clips = root.findall(".//asset-clip")
            assert len(clips) == 2
            ref = root.find(".//asset").get("id")
            assert all(c.get("ref") == ref for c in clips)
            assert root.find(".//asset").get("hasVideo") == ("1" if name.endswith("mp4") else None)
        else:
            assert root.findall(".//audio/track")
            assert bool(root.findall(".//video/track")) == name.endswith("mp4")
    elif fmt == "edl":
        assert text.startswith("TITLE:") and text.count("AX") >= 2
    elif fmt == "audacity":
        assert len(text.strip().splitlines()) == 2
    else:
        d = json.loads(text)
        assert d["segments"][1]["out_start"] == pytest.approx(d["segments"][0]["out_end"], abs=1e-3)


def test_fcpxml_frame_rational_times(media, tmp_path):
    svc, pid = _service_with_cuts(media, "pattern60.mp4")
    path = svc.export(pid, "fcpxml", str(tmp_path / "a.fcpxml"))["path"]
    root = etree.parse(path).getroot()
    assert root.find(".//format").get("frameDuration") == "1001/60000s"
    for c in root.findall(".//asset-clip"):
        n, _, d = c.get("start").rstrip("s").partition("/")
        assert int(n) % 1001 == 0 or n == "0"  # whole frames at 59.94


def test_keep_all_cuts_marks_removed_disabled(media, tmp_path):
    svc, pid = _service_with_cuts(media, "pattern.mp4")
    path = svc.export(pid, "fcpxml", str(tmp_path / "a.fcpxml"), keep_all_cuts=True)["path"]
    clips = etree.parse(path).getroot().findall(".//asset-clip")
    assert sum(c.get("enabled") == "0" for c in clips) == 2 and len(clips) == 4


def test_captions_remapped_to_output(svc_with_transcript, tmp_path):
    svc, pid = svc_with_transcript
    svc.detect_silence(pid)
    srt = open(svc.export(pid, "srt", str(tmp_path / "a.srt"))["path"], encoding="utf-8").read()
    assert "Hello um world." in srt and "-->" in srt
    p = svc.project(pid)
    # "Again there." starts at source 3.0, which must land near the end of the first kept block
    first_out = svc.map_time(pid, 3.0)["output"]
    assert first_out == pytest.approx(1.15 + (3.0 - 2.99), abs=0.1)
    assert f"00:00:0{int(first_out)}" in srt
    vtt = open(svc.export(pid, "vtt", str(tmp_path / "a.vtt"))["path"], encoding="utf-8").read()
    assert vtt.startswith("WEBVTT")
    assert p.transcript is not None


def test_srt_drops_removed_words(svc_with_transcript, tmp_path):
    svc, pid = svc_with_transcript
    svc.detect_silence(pid)
    svc.apply_edits(pid, [{"action": "remove", "word_range": [1, 1]}])
    srt = open(svc.export(pid, "srt", str(tmp_path / "a.srt"))["path"], encoding="utf-8").read()
    assert "um" not in srt.lower().replace("umm", "")


def test_sandbox_blocks_foreign_paths(media, tmp_path):
    svc = Service(sandbox=True)
    pid = svc.open_media([str(media / "pattern.wav")])["id"]
    with pytest.raises(ServiceError):
        svc.export(pid, "edl", "C:/Windows/evil.edl")
    ok = svc.export(pid, "edl", str(media / "ok.edl"))
    assert ok["path"].endswith("ok.edl")
    _ = minidom
