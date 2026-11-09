"""Offline tests: addressing, time parsing, slicing, paragraphing, arg parsing.

Nothing here touches the network — the fetch path is covered by `yt info` runs
against a real video, which is not a unit test's job.
"""
import pytest

from yt_captions import cli


# ---------------------------------------------------------------- addressing

@pytest.mark.parametrize("arg", [
    "aircAruvnKk",
    "https://www.youtube.com/watch?v=aircAruvnKk",
    "https://www.youtube.com/watch?v=aircAruvnKk&list=PLabc&index=2",
    "https://youtu.be/aircAruvnKk",
    "https://youtu.be/aircAruvnKk?t=42",
    "https://www.youtube.com/shorts/aircAruvnKk",
    "https://www.youtube.com/embed/aircAruvnKk",
    "https://www.youtube.com/live/aircAruvnKk",
    "https://www.youtube.com/v/aircAruvnKk",
    "<https://youtu.be/aircAruvnKk>",
    "  aircAruvnKk  ",
])
def test_video_id_accepts_every_url_shape(arg):
    assert cli.video_id(arg) == "aircAruvnKk"


@pytest.mark.parametrize("arg,needle", [
    ("https://www.youtube.com/playlist?list=PLabc", "playlist"),
    ("https://www.youtube.com/@3blue1brown", "channel"),
    ("https://www.youtube.com/channel/UCabc", "channel"),
    ("12:30", "is a time"),
    ("[12:30]", "is a time"),
    ("90s", "is a time"),
    ("not a video", "could not find a video id"),
])
def test_video_id_names_the_mistake(arg, needle):
    with pytest.raises(SystemExit) as exc:
        cli.video_id(arg)
    assert needle in str(exc.value)


# --------------------------------------------------------------------- times

@pytest.mark.parametrize("text,seconds", [
    ("12:30", 750),
    ("[12:30]", 750),          # yt prints brackets, so yt must take them back
    ("1:02:30", 3750),
    ("750", 750),
    ("12m30s", 750),
    ("90s", 90),
    ("2h", 7200),
    ("0:00", 0),
])
def test_parse_time_round_trips_everything_yt_prints(text, seconds):
    assert cli.parse_time(text, "--from") == seconds


@pytest.mark.parametrize("text", ["", "banana", "1:2:3:4", "::"])
def test_parse_time_rejects_nonsense(text):
    with pytest.raises(SystemExit):
        cli.parse_time(text, "--to")


@pytest.mark.parametrize("seconds,out", [(0, "0:00"), (9, "0:09"), (750, "12:30"),
                                         (3750, "1:02:30"), (-5, "0:00")])
def test_clock(seconds, out):
    assert cli.clock(seconds) == out


def test_clock_can_be_forced_to_hours():
    assert cli.clock(750, force_hours=True) == "0:12:30"


# ------------------------------------------------------------------ segments

def seg(start, duration, text):
    return {"start": start, "duration": duration, "text": text}


SEGMENTS = [seg(0, 3, "first cue"), seg(3, 3, "second cue"),
            seg(10, 3, "third cue"), seg(20, 3, "fourth cue")]


def test_slice_keeps_cues_overlapping_the_window():
    picked = cli.slice_segments(SEGMENTS, 4, 12)
    assert [s["text"] for s in picked] == ["second cue", "third cue"]


def test_slice_open_ended_both_ways():
    assert len(cli.slice_segments(SEGMENTS, 10, None)) == 2
    assert len(cli.slice_segments(SEGMENTS, None, 5)) == 2
    assert cli.slice_segments(SEGMENTS, None, None) == SEGMENTS


def test_paragraphs_break_on_real_pauses():
    cues = [seg(i * 3, 3, "word " * 10) for i in range(4)]
    cues.append(seg(40, 3, "after a long silence"))  # 28s gap
    out = cli.paragraphs(cues)
    assert len(out) == 2
    assert out[1] == "after a long silence"


def test_paragraphs_split_blind_on_unpunctuated_captions():
    cues = [seg(i * 3, 3, "word " * 10) for i in range(60)]  # 600 words, no gaps
    out = cli.paragraphs(cues)
    assert len(out) > 1
    assert all(len(p.split()) <= 180 for p in out)


def test_word_count():
    assert cli.word_count(SEGMENTS) == 8


# ------------------------------------------------------------------- parsing

def test_parse_args_defaults():
    verb, targets, opts = cli.parse_args(["aircAruvnKk"])
    assert verb is None and targets == ["aircAruvnKk"]
    assert not any(opts[k] for k in opts)


def test_parse_args_info_verb_and_flags():
    verb, targets, opts = cli.parse_args(
        ["info", "aircAruvnKk", "--json", "--lang", "es"])
    assert verb == "info" and targets == ["aircAruvnKk"]
    assert opts["json"] is True and opts["lang"] == "es"


def test_parse_args_times_and_equals_form():
    _, _, opts = cli.parse_args(["x", "--from=12:30", "--to", "[13:00]"])
    assert opts["start"] == 750 and opts["end"] == 780


def test_parse_args_several_videos():
    _, targets, _ = cli.parse_args(["a", "b", "c"])
    assert targets == ["a", "b", "c"]


@pytest.mark.parametrize("argv", [["--help"], ["-h"], ["help"], ["--usage"]])
def test_help_short_circuits(argv):
    verb, targets, _ = cli.parse_args(argv)
    assert verb in ("help", "-h", "--help", "--usage") and targets == []


@pytest.mark.parametrize("argv", [["--version"], ["-V"]])
def test_version_short_circuits(argv):
    verb, _, _ = cli.parse_args(argv)
    assert verb == "version"


def test_grep_refuses_a_flag_shaped_value():
    """The original desire-path trap: `--grep -i transformer` must not silently
    take `-i` as the pattern and `transformer` as a second video id."""
    with pytest.raises(SystemExit) as exc:
        cli.parse_args(["aircAruvnKk", "--grep", "-i", "transformer"])
    assert "case-insensitive" in str(exc.value)


def test_grep_can_still_match_a_literal_dash():
    _, _, opts = cli.parse_args(["x", "--grep=-i"])
    assert opts["grep"] == "-i"


def test_negative_numbers_are_values_not_flags():
    _, _, opts = cli.parse_args(["x", "--from", "-0"])
    assert opts["start"] == 0


def test_unknown_option_is_named():
    with pytest.raises(SystemExit) as exc:
        cli.parse_args(["x", "--tim"])
    assert "unknown option --tim" in str(exc.value)


def test_missing_value_is_named():
    with pytest.raises(SystemExit) as exc:
        cli.parse_args(["x", "--lang"])
    assert "--lang needs a value" in str(exc.value)


def test_from_after_to_is_refused():
    with pytest.raises(SystemExit) as exc:
        cli.parse_args(["x", "--from", "10:00", "--to", "2:00"])
    assert "--from is after --to" in str(exc.value)


def test_bare_invocation_prints_help(capsys):
    assert cli.main([]) == 0
    assert "read YouTube video transcripts" in capsys.readouterr().out
