# yt — YouTube transcripts on the command line

`yt` reads the captions YouTube already holds for a video and prints them as
plain text. It is built for **coding agents** first and humans second: one
command, no API key, no config file, and `yt --help` is the whole manual.

```console
$ yt aircAruvnKk
But what is a neural network? | Deep learning chapter 1  --  3Blue1Brown
length 18:25  |  3,357 words  |  English [en], captions
https://www.youtube.com/watch?v=aircAruvnKk

This is a 3. It's sloppily written and rendered at an extremely low resolution
of 28x28 pixels, but your brain has no trouble recognizing it as a 3. ...
```

It is read-only and network-light. It does **not** download video or audio, does
not run speech-to-text, and does not search YouTube. If a video has captions
disabled, `yt` says so and exits non-zero rather than pretending.

## Install

Needs Python 3.9+. Either line puts a `yt` command on your PATH:

```bash
uv tool install git+https://github.com/alexr314/yt-captions     # recommended
pipx install git+https://github.com/alexr314/yt-captions
```

Or run it without installing anything:

```bash
uvx --from git+https://github.com/alexr314/yt-captions yt aircAruvnKk
```

A PyPI release is coming; after that, `uv tool install yt-captions` (or
`pipx install yt-captions`, or `pip install yt-captions`) will be the short way.

The command is `yt`. If that name is already taken on your machine, alias it
instead of installing:
`alias ytt='uvx --from git+https://github.com/alexr314/yt-captions yt'`.

## Quickstart

```bash
yt aircAruvnKk                       # transcript as clean paragraphs, with a header
yt "https://youtu.be/aircAruvnKk"    # url or bare id, both fine -- quote urls in zsh
yt info <video>                      # title, channel, length, caption languages
yt <video> --grep "sigmoid"          # where is this discussed? -> timestamped cues
yt <video> --from 17:15 --to 17:45   # read just that stretch
yt <video> --timestamps              # one cue per line, [mm:ss] prefixed
yt <video> --lang es                 # pick a caption track
yt <video> --json                    # structured output
yt a1 a2 a3                          # several videos in one call
```

The intended loop for anything long: `yt info` to size it up, `--grep` to find
the moment, `--from/--to` to read around it. Pulling a three-hour podcast into
context whole costs ~50k tokens and is almost never what you wanted.

## Using it with a coding agent

`yt` is designed so that an agent that has never seen it gets the right answer
on the first guess. The only setup is telling your agent the tool exists. Paste
this into the project's agent instructions file — `CLAUDE.md`, `AGENTS.md`,
`.cursorrules`, a system prompt, whatever your tool reads:

```markdown
## Reading YouTube videos

`yt` reads a YouTube video's captions as text. `yt <url-or-id>` prints the
transcript; `yt info <video>` reports length and available caption tracks;
`yt <video> --grep PATTERN` finds where a topic is discussed and prints
timestamped cues; `yt <video> --from 12:30 --to 14:00` reads one stretch.
For a long video, size it up with `info`, locate the part with `--grep`, then
read that part with `--from/--to` — do not pull a multi-hour transcript into
context whole. `yt --help` is the full manual.
```

That's it. No MCP server, no tool schema, no wrapper — it is a normal CLI, so
any agent with shell access can already use it. `--json` is there for when you
want to parse rather than read.

## Why the interface is shaped this way

Every flag below exists because a **zero-context agent** was handed a real task
and only the tool's name, and the transcript of where it went wrong was turned
into a fix. Two blind runs are on record: the first (against an otherwise
finished tool) found three traps; the second answered a real question in four
commands with no dead ends.

- **The video is a positional argument, not a flag.** The first thing an agent
  has in hand is a URL it was pasted. `yt <url>` has to work on the first guess,
  so a bare invocation with a video is the transcript — the safe,
  non-destructive default — and the URL forms are all accepted interchangeably
  (`watch?v=`, `youtu.be`, `/shorts/`, `/embed/`, `/live/`, `/v/`, bare 11-char
  id). Extra `&list=`/`&t=` params are ignored rather than rejected, because
  pasted links carry them.
- **A playlist or channel URL is a named error, not a guess.** Those are the two
  things most likely to be pasted by mistake; both say what to pass instead.
- **A flag-shaped value is a mistyped flag, not a value.** A blind test agent
  reached for `--grep -i transformer` out of plain-`grep` habit. `-i` was taken
  as the pattern and `transformer` — which is, unhelpfully, exactly 11
  characters — became a second video id, so the failure surfaced as "video
  transformer is unavailable". Now any value beginning with `-` is refused by
  name, the message says `--grep` is already case-insensitive, and `--grep=-i`
  remains available for a literal match.
- **Quote your URLs — and the docs say so.** The same agent hit zsh's
  `no matches found` on an unquoted `watch?v=...`, because `?` globs. The tool's
  own examples had taught it the broken form; they are quoted now.
- **`yt info` separates written from auto tracks, and names the default.** One
  merged caption list made English appear twice, and the agent could not tell
  that a human *and* an auto track both existed until it read the transcript
  header. `info` now prints `written` / `auto` on their own lines plus a
  `default` line saying which track a bare `yt <video>` will actually use.
- **`-t` was removed.** It was a shorthand for `--timestamps`, but in YouTube
  URLs `-t` means a time offset, so `-t 12:30` would have silently turned on
  timestamps and then treated `12:30` as a second video. A stray time in a
  positional slot now says so and points at `--from`.
- **Everything `yt` prints, `yt` takes back.** Timestamps print as `[mm:ss]` or
  `[h:mm:ss]`, and `--from`/`--to` accept exactly that — brackets included —
  plus `1:02:30`, plain seconds, and `12m30s`. A flag that rejects the tool's
  own output is a classic trap: an agent that greps and then wants to read
  around a hit must be able to paste the timestamp it just read.
- **Cues are re-joined into paragraphs by default.** Captions arrive as
  ~3-second fragments. One per line is unreadable and spends tokens on line
  breaks, so the default output breaks on real pauses and at sentence ends, and
  only splits blind at 170 words (auto-captions have no punctuation and
  sometimes no pauses). `--timestamps` keeps the original cue boundaries for
  when position matters.
- **The header states the cost before the text.** Length, word count, caption
  language, and whether the track is auto-generated — so the reader can see it
  is about to read 39,506 words and reach for `--grep` instead. When a slice or
  grep is in effect the header reports the selection (`102 words of 3,357`,
  `26 matching cues`) rather than silently describing the whole video.
- **Auto-generated tracks are labelled every time.** They have no punctuation,
  no capitalisation, and mis-hear proper nouns. Fine to summarise from, risky to
  quote from — so the distinction is in the header and in `yt info`, never
  hidden.
- **Errors are recovery instructions.** Captions disabled, video unavailable,
  rate-limited network, and unknown `--lang` each name the fix (and the last one
  lists the tracks that do exist). All failures exit non-zero.

## Sharp edges

- `--grep` matches a single cue — about three seconds of speech — so a phrase
  straddling a cue boundary will not match. Grep one distinctive word, then
  widen with `--from`/`--to`.
- Language default order: English, then any human-written track, then
  auto-generated. `--lang pt` will match `pt-BR` if that is all there is.
- Transcripts and metadata are cached under `~/.cache/yt` (override with
  `YT_CACHE_DIR`). Captions effectively never change, so the cache has no TTL;
  `--refresh` bypasses it. A warm read costs ~70ms and no network.
- YouTube rate-limits caption requests per IP, and blocks datacenter ranges
  fairly aggressively — `yt` works best from a normal residential connection.
  The failure is explicit and the fix is to wait and rerun; there is no proxy
  configuration. If you need one, the underlying library
  ([`youtube-transcript-api`](https://github.com/jdepoix/youtube-transcript-api))
  supports proxies and you can drive it directly.

## Implementation

A single-file CLI over
[`youtube-transcript-api`](https://github.com/jdepoix/youtube-transcript-api)
for captions, plus YouTube's public oEmbed endpoint for title and channel. No
API key anywhere, no credentials, no browser automation.

## Development

```bash
git clone https://github.com/alexr314/yt-captions
cd yt-captions
uv sync
uv run pytest        # offline tests: addressing, times, slicing, paragraphing, parsing
uv run yt --help
```

## License

MIT
