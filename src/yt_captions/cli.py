#!/usr/bin/env python3
"""yt - read YouTube video transcripts from the command line.

For agents and humans. Reads the captions YouTube already has for a video and
prints them as plain text. Nothing is downloaded, nothing is transcribed: if a
video has no captions, there is nothing for yt to read.

Usage:
  yt <video>                   print the transcript as clean paragraphs
  yt <video> --timestamps      one line per caption cue, prefixed [mm:ss]
  yt <video> --from T --to T   only the part between two times
  yt <video> --grep PATTERN    just the cues matching PATTERN, with timestamps
                               (one pattern, already case-insensitive)
  yt info <video>              title, channel, length, available languages
  yt <video> [<video> ...]     several videos in one call, each with a header
  yt ... --json                structured JSON instead of formatted text
  yt help

Naming a video:
  <video> is a full URL or a bare id -- all of these work:
    "https://www.youtube.com/watch?v=aircAruvnKk" (extra &list=/&t= params are ignored)
    "https://youtu.be/aircAruvnKk"
    "https://www.youtube.com/shorts/aircAruvnKk"  (also /embed/, /live/, /v/)
    aircAruvnKk
  Quote urls. In zsh an unquoted ?v=... is a glob pattern and the shell, not yt,
  will reject it ("no matches found"). A bare id needs no quoting.
  A playlist or channel URL is not a video; yt names the video id it needs and
  stops rather than guessing which entry you meant.

Times:
  --from/--to accept anything yt itself prints, plus the obvious variants:
    12:30   [12:30]   1:02:30   750   12m30s   90s
  Bare numbers are seconds. --from with no --to runs to the end, and vice versa.

Language:
  --lang CODE      pick a caption track (e.g. --lang es, --lang pt-BR)
  Without --lang, yt prefers English, then any human-written track, then an
  auto-generated one, and says in the header which it used. `yt info` lists
  every track available. Auto-generated captions have no punctuation or
  capitalisation and mis-hear proper nouns -- fine to summarise from, risky to
  quote from verbatim.

Other options:
  --refresh        re-fetch instead of using the local cache (~/.cache/yt)
  --no-header      omit the title/channel/length block (bare transcript text)
  --version        print the installed version

Sharp edges worth knowing:
  - Transcripts are long. A one-hour talk is roughly 9,000 words, and the header
    prints the word count before the text so you can see what you are about to
    read. Prefer --grep to locate a topic, then --from/--to to read that part,
    instead of pulling a three-hour podcast into context whole.
  - Captions are cues, not sentences. The default output re-joins cues into
    paragraphs on pauses; --timestamps keeps the original cue boundaries.
  - --grep matches one cue at a time -- about three seconds of speech -- so a
    phrase straddling a cue boundary will not match. Grep for one distinctive
    word, then widen with --from/--to around the timestamps it reports.
  - yt reads captions only. It does not download video or audio, does not run
    speech-to-text, and does not search YouTube -- if a video has captions
    disabled, no flag will produce a transcript.
"""
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

CACHE_DIR = os.path.expanduser(os.environ.get("YT_CACHE_DIR", "~/.cache/yt"))
OEMBED = "https://www.youtube.com/oembed"
ID_RE = re.compile(r"^[0-9A-Za-z_-]{11}$")
URL_ID_RE = re.compile(
    r"(?:youtu\.be/|/embed/|/shorts/|/live/|/v/|[?&]v=)([0-9A-Za-z_-]{11})"
)
# English first, then the main variants, so `yt <talk>` does the obvious thing.
ENGLISH = ("en", "en-US", "en-GB", "en-orig")


# ----------------------------------------------------------------- addressing


def video_id(arg):
    """Turn a URL or bare id into a video id, or exit explaining what is wrong."""
    arg = arg.strip().strip("<>").strip()
    if ID_RE.match(arg):
        return arg
    m = URL_ID_RE.search(arg)
    if m:
        return m.group(1)
    if "list=" in arg or "/playlist" in arg:
        sys.exit(
            f"error: that is a playlist, not a video: {arg}\n"
            "hint: yt reads one video at a time. Open the playlist and pass the\n"
            "      watch?v=... url (or id) of the entry you want. Several videos\n"
            "      in one call is fine: yt <id1> <id2>"
        )
    if "youtube.com/@" in arg or "/channel/" in arg or "/c/" in arg:
        sys.exit(
            f"error: that is a channel, not a video: {arg}\n"
            "hint: pass a watch?v=... url or an 11-character video id."
        )
    if re.fullmatch(r"\[?\d{1,2}(:\d{2}){1,2}\]?|\d+[hms][\dhms]*", arg):
        sys.exit(
            f"error: {arg} is a time, not a video\n"
            "hint: times belong to a flag: yt <video> --from {0} --to ...".format(arg)
        )
    sys.exit(
        f"error: could not find a video id in: {arg}\n"
        "hint: pass a youtube url (watch?v=..., youtu.be/..., /shorts/...) or a\n"
        "      bare 11-character id like aircAruvnKk."
    )


def parse_time(text, flag):
    """Accept 12:30, [12:30], 1:02:30, 750, 12m30s, 90s -- anything yt prints."""
    s = str(text).strip().strip("[]").strip()
    if not s:
        sys.exit(f"error: {flag} needs a time, e.g. {flag} 12:30")
    if ":" in s:
        parts = s.split(":")
        if len(parts) > 3 or not all(p.strip() for p in parts):
            sys.exit(f"error: could not read {flag} {text!r}; try mm:ss or h:mm:ss")
        try:
            nums = [float(p) for p in parts]
        except ValueError:
            sys.exit(f"error: could not read {flag} {text!r}; try mm:ss or h:mm:ss")
        total = 0.0
        for n in nums:
            total = total * 60 + n
        return total
    m = re.fullmatch(r"(?:(\d+(?:\.\d+)?)h)?(?:(\d+(?:\.\d+)?)m)?(?:(\d+(?:\.\d+)?)s)?", s)
    if m and any(m.groups()):
        h, mi, sec = (float(g) if g else 0.0 for g in m.groups())
        return h * 3600 + mi * 60 + sec
    try:
        return float(s)
    except ValueError:
        sys.exit(
            f"error: could not read {flag} {text!r}\n"
            "hint: use mm:ss, h:mm:ss, plain seconds, or 12m30s."
        )


def clock(seconds, force_hours=False):
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h or force_hours:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


# -------------------------------------------------------------------- fetching


def oembed(vid):
    """Title and channel, cheaply. Never fatal -- a header is nice, not required."""
    cached = read_cache(vid, "meta")
    if cached:
        return cached
    url = OEMBED + "?" + urllib.parse.urlencode(
        {"url": f"https://www.youtube.com/watch?v={vid}", "format": "json"}
    )
    try:
        with urllib.request.urlopen(url, timeout=8) as r:
            data = json.load(r)
    except Exception:
        return {"title": None, "channel": None}
    meta = {"title": data.get("title"), "channel": data.get("author_name")}
    if meta["title"]:
        write_cache(vid, "meta", meta)
    return meta


def cache_path(vid, lang):
    return os.path.join(CACHE_DIR, f"{vid}.{lang or 'auto'}.json")


def read_cache(vid, lang):
    try:
        with open(cache_path(vid, lang)) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def write_cache(vid, lang, payload):
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        tmp = cache_path(vid, lang) + ".tmp"
        with open(tmp, "w") as f:
            json.dump(payload, f)
        os.replace(tmp, cache_path(vid, lang))
    except OSError:
        pass  # a cache that cannot be written is not a reason to fail the read


def pick_track(tracks, lang):
    """Choose a caption track: asked-for language, else English, else written, else auto."""
    if lang:
        want = lang.lower()
        for t in tracks:
            if t.language_code.lower() == want:
                return t
        for t in tracks:  # --lang pt matching pt-BR is what people mean
            if t.language_code.lower().split("-")[0] == want.split("-")[0]:
                return t
        have = ", ".join(sorted({t.language_code for t in tracks})) or "none"
        sys.exit(
            f"error: no '{lang}' captions on this video\n"
            f"hint: available tracks: {have}\n"
            "      run `yt info <video>` to see them with names."
        )
    for code in ENGLISH:
        for t in tracks:
            if t.language_code.lower() == code.lower() and not t.is_generated:
                return t
    for code in ENGLISH:
        for t in tracks:
            if t.language_code.lower() == code.lower():
                return t
    for t in tracks:
        if not t.is_generated:
            return t
    return tracks[0]


def fetch(vid, lang=None, refresh=False):
    """Return {language, language_code, is_generated, segments:[{start,duration,text}]}."""
    if not refresh:
        hit = read_cache(vid, lang)
        if hit:
            return hit
    import youtube_transcript_api as err  # exceptions live on the top-level namespace
    from youtube_transcript_api import YouTubeTranscriptApi

    api = YouTubeTranscriptApi()
    try:
        tracks = list(api.list(vid))
    except err.TranscriptsDisabled:
        sys.exit(
            f"error: captions are turned off for {vid}\n"
            "hint: there is no transcript to read. yt reads captions only -- it\n"
            "      does not transcribe audio."
        )
    except err.VideoUnavailable:
        sys.exit(
            f"error: video {vid} is unavailable (private, deleted, or region-blocked)\n"
            "hint: check the id/url opens in a browser."
        )
    except (err.IpBlocked, err.RequestBlocked):
        sys.exit(
            "error: YouTube is blocking transcript requests from this network\n"
            "hint: this is usually rate limiting -- wait a minute and run it again."
        )
    except err.CouldNotRetrieveTranscript as e:
        sys.exit(f"error: could not retrieve captions for {vid}: {e}")
    except urllib.error.URLError as e:
        sys.exit(f"error: network failure reaching YouTube: {e}\nhint: check the connection and retry.")
    if not tracks:
        sys.exit(
            f"error: {vid} has no caption tracks\n"
            "hint: nothing to read. yt reads captions only; it does not transcribe audio."
        )
    track = pick_track(tracks, lang)
    try:
        fetched = track.fetch()
    except err.CouldNotRetrieveTranscript as e:
        sys.exit(f"error: could not fetch the '{track.language_code}' captions: {e}")
    segments, previous = [], None
    for sn in fetched:
        text = " ".join(str(sn.text).split())
        if not text or text == previous:  # rolling captions repeat cues verbatim
            continue
        previous = text
        segments.append(
            {"start": float(sn.start), "duration": float(sn.duration or 0), "text": text}
        )
    payload = {
        "language": track.language,
        "language_code": track.language_code,
        "is_generated": bool(track.is_generated),
        "segments": segments,
    }
    write_cache(vid, lang, payload)
    return payload


def list_tracks(vid):
    import youtube_transcript_api as err  # exceptions live on the top-level namespace
    from youtube_transcript_api import YouTubeTranscriptApi

    try:
        return list(YouTubeTranscriptApi().list(vid))
    except err.TranscriptsDisabled:
        return []
    except err.VideoUnavailable:
        sys.exit(f"error: video {vid} is unavailable (private, deleted, or region-blocked)")
    except err.CouldNotRetrieveTranscript as e:
        sys.exit(f"error: could not list captions for {vid}: {e}")


# --------------------------------------------------------------- presentation


def slice_segments(segments, start, end):
    out = []
    for s in segments:
        if start is not None and s["start"] + s["duration"] < start:
            continue
        if end is not None and s["start"] > end:
            continue
        out.append(s)
    return out


def paragraphs(segments, gap=1.4, target=85, hard=170):
    """Re-join caption cues into readable paragraphs.

    Cues are ~3 seconds of speech each, so printing one per line is unreadable
    and wastes tokens on line breaks. Break on a real pause once the paragraph
    has some substance; past the target length, break at the next pause or
    sentence end rather than mid-clause, and only split blind at `hard` words
    (captions with no punctuation and no pauses have nowhere better to break).
    """
    out, buf, words, prev_end = [], [], 0, None
    for s in segments:
        if buf and prev_end is not None:
            pause = s["start"] - prev_end
            settled = buf[-1].rstrip().endswith((".", "?", "!", '."', '?"', '!"'))
            if (
                words >= hard
                or (words >= target and (pause >= 0.4 or settled))
                or (pause >= gap and words >= 25)
            ):
                out.append(" ".join(buf))
                buf, words = [], 0
        buf.append(s["text"])
        words += len(s["text"].split())
        prev_end = s["start"] + s["duration"]
    if buf:
        out.append(" ".join(buf))
    return out


def word_count(segments):
    return sum(len(s["text"].split()) for s in segments)


def header(vid, meta, data, segments, full, matched=None):
    title = meta.get("title") or f"video {vid}"
    lines = [title]
    if meta.get("channel"):
        lines[0] = f"{title}  --  {meta['channel']}"
    end = max((s["start"] + s["duration"] for s in full), default=0)
    kind = "auto-generated" if data["is_generated"] else "captions"
    if matched is not None:
        counted = f"{matched:,} matching cue{'' if matched == 1 else 's'}"
    else:
        counted = f"{word_count(segments):,} words"
        if len(segments) != len(full):
            counted += f" of {word_count(full):,}"
    bits = [f"length {clock(end)}", counted,
            f"{data['language']} [{data['language_code']}], {kind}"]
    lines.append("  |  ".join(bits))
    lines.append(f"https://www.youtube.com/watch?v={vid}")
    return "\n".join(lines)


def print_transcript(vid, opts, first):
    data = fetch(vid, opts["lang"], opts["refresh"])
    full = data["segments"]
    segments = slice_segments(full, opts["start"], opts["end"])
    meta = oembed(vid) if not opts["no_header"] or opts["json"] else {}
    hours = max((s["start"] + s["duration"] for s in full), default=0) >= 3600

    if opts["grep"]:
        try:
            pattern = re.compile(opts["grep"], re.IGNORECASE)
        except re.error as e:
            sys.exit(f"error: bad --grep pattern {opts['grep']!r}: {e}")
        segments = [s for s in segments if pattern.search(s["text"])]

    if opts["json"]:
        end = max((s["start"] + s["duration"] for s in full), default=0)
        return {
            "video_id": vid,
            "url": f"https://www.youtube.com/watch?v={vid}",
            "title": meta.get("title"),
            "channel": meta.get("channel"),
            "language": data["language"],
            "language_code": data["language_code"],
            "is_generated": data["is_generated"],
            "length_seconds": round(end, 2),
            "word_count": word_count(segments),
            "segments": [
                {"start": round(s["start"], 2), "timestamp": clock(s["start"], hours),
                 "duration": round(s["duration"], 2), "text": s["text"]}
                for s in segments
            ],
        }

    if not first:
        print()
    if not opts["no_header"]:
        matched = len(segments) if opts["grep"] else None
        print(header(vid, meta, data, segments, full, matched))
        print()
    if not segments:
        if opts["grep"]:
            print(f"(no cues matching {opts['grep']!r})")
        else:
            print("(no captions in that range)")
        return None
    if opts["timestamps"] or opts["grep"]:
        for s in segments:
            print(f"[{clock(s['start'], hours)}] {s['text']}")
    else:
        print("\n\n".join(paragraphs(segments)))
    return None


def print_info(vid, as_json, first):
    meta = oembed(vid)
    tracks = list_tracks(vid)
    written = [t for t in tracks if not t.is_generated]
    auto = [t for t in tracks if t.is_generated]
    length = None
    if tracks:
        data = fetch(vid, None, False)
        length = max((s["start"] + s["duration"] for s in data["segments"]), default=0)
    if as_json:
        return {
            "video_id": vid,
            "url": f"https://www.youtube.com/watch?v={vid}",
            "title": meta.get("title"),
            "channel": meta.get("channel"),
            "length_seconds": round(length, 2) if length is not None else None,
            "tracks": [
                {"language": t.language, "language_code": t.language_code,
                 "is_generated": t.is_generated} for t in tracks
            ],
        }
    if not first:
        print()
    print(meta.get("title") or f"video {vid}")
    if meta.get("channel"):
        print(f"channel   {meta['channel']}")
    if length:
        print(f"length    {clock(length)}")
    print(f"url       https://www.youtube.com/watch?v={vid}")
    if not tracks:
        print("captions  none -- this video has captions turned off, so there is "
              "no transcript to read")
        return None
    # Separate the two kinds explicitly: the same language often has both a
    # human track and an auto one, and a single merged list makes that look
    # like a duplicate rather than a real choice.
    if written:
        print("written   " + ", ".join(f"{t.language_code} ({t.language})" for t in written))
    if auto:
        print("auto      " + ", ".join(f"{t.language_code} ({t.language})" for t in auto[:12])
              + (f", +{len(auto) - 12} more" if len(auto) > 12 else ""))
    chosen = pick_track(tracks, None)
    print(f"default   {chosen.language_code} ({chosen.language}), "
          f"{'auto-generated' if chosen.is_generated else 'written'}"
          "  <- what `yt <video>` prints; override with --lang")
    return None


# --------------------------------------------------------------------- parsing


def parse_args(argv):
    opts = {"lang": None, "start": None, "end": None, "grep": None, "json": False,
            "timestamps": False, "refresh": False, "no_header": False}
    verb, targets, i = None, [], 0
    takes_value = {"--lang": "lang", "--from": "start", "--to": "end", "--grep": "grep"}
    flags = {"--json": "json", "--timestamps": "timestamps", "--refresh": "refresh",
             "--no-header": "no_header"}
    while i < len(argv):
        a = argv[i]
        if a in ("help", "-h", "--help", "--usage"):
            return a, [], opts
        if a in ("--version", "-V"):
            return "version", [], opts
        if a in takes_value:
            if i + 1 >= len(argv):
                sys.exit(f"error: {a} needs a value")
            value = argv[i + 1]
            if value.startswith("-") and not re.match(r"^-?\d", value):
                sys.exit(
                    f"error: {a} takes a value, but got the flag {value}\n"
                    f"hint: {a} accepts exactly one value and yt has no {value} flag."
                    + ("\n      --grep is already case-insensitive; just pass the pattern."
                       if a == "--grep" else "")
                    + f"\n      To search for a literal {value}, write {a}={value}."
                )
            key = takes_value[a]
            opts[key] = parse_time(value, a) if key in ("start", "end") else value
            i += 2
            continue
        if "=" in a and a.split("=", 1)[0] in takes_value:
            name, value = a.split("=", 1)
            key = takes_value[name]
            opts[key] = parse_time(value, name) if key in ("start", "end") else value
            i += 1
            continue
        if a in flags:
            opts[flags[a]] = True
            i += 1
            continue
        if a.startswith("-") and a not in ("-",):
            sys.exit(f"error: unknown option {a}\nhint: run `yt help` for the flag list.")
        if verb is None and not targets and a == "info":
            verb = a
            i += 1
            continue
        targets.append(a)
        i += 1
    if opts["start"] is not None and opts["end"] is not None and opts["start"] > opts["end"]:
        sys.exit("error: --from is after --to")
    return verb, targets, opts


def version():
    from importlib.metadata import PackageNotFoundError, version as _v

    try:
        return _v("yt-captions")
    except PackageNotFoundError:  # running from a source checkout
        return "0+unknown"


def main(argv):
    verb, targets, opts = parse_args(argv)
    if verb == "version":
        print(f"yt {version()}")
        return 0
    if verb in ("help", "-h", "--help", "--usage") or (verb is None and not targets):
        print(__doc__.strip())
        return 0
    if not targets:
        sys.exit("error: name a video -- a youtube url or an 11-character id.\n"
                 "hint: run `yt help` for the addressing rules.")
    ids = [video_id(t) for t in targets]
    results = []
    for n, vid in enumerate(ids):
        if verb == "info":
            out = print_info(vid, opts["json"], first=(n == 0))
        else:
            out = print_transcript(vid, opts, first=(n == 0))
        if out is not None:
            results.append(out)
    if opts["json"]:
        print(json.dumps(results[0] if len(results) == 1 else results, indent=2,
                         ensure_ascii=False))
    return 0


def run():
    """Console-script entry point (`yt`)."""
    try:
        sys.exit(main(sys.argv[1:]))
    except KeyboardInterrupt:
        sys.exit(130)
    except BrokenPipeError:
        os._exit(0)  # `yt <id> | head` is a normal thing to do


if __name__ == "__main__":
    run()
