"""Allow `python -m yt_captions` as well as the installed `yt` command."""

from .cli import run

if __name__ == "__main__":
    run()
