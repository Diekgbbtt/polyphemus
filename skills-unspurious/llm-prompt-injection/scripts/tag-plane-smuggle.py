#!/usr/bin/env python3
"""Encode text into the Unicode tag plane, or decode a captured sample back.

The tag plane (U+E0000..U+E007F) mirrors printable ASCII at an invisible
offset, so an instruction hidden there survives visual and keyword review while
the model still consumes it. This script is a pure text transform: it reads argv
or stdin, writes the result to stdout, and touches no network and no file.

Usage:
  tag-plane-smuggle.py "text to hide"             encode, print the tagged form
  tag-plane-smuggle.py --wrap "text to hide"      also bracket with the start and end tags
  tag-plane-smuggle.py --decode "<tagged text>"   recover the hidden text
  printf '%s' "$VISIBLE" | tag-plane-smuggle.py   encode text read from stdin

Notes:
  Only printable ASCII (0x20..0x7E) has a mirrored codepoint; other input
  characters are skipped and the count is reported on stderr.
  Pair any encoded probe with an out-of-band callback or a ground-truth anchor;
  the encoding alone is not a finding.
"""

from __future__ import annotations

import argparse
import sys

TAG_BASE = 0xE0000
TAG_START = 0xE0001  # LANGUAGE TAG
TAG_END = 0xE007F  # CANCEL TAG
ASCII_LO, ASCII_HI = 0x20, 0x7E


def encode(text: str) -> tuple[str, int]:
    """Map printable ASCII to the tag plane, returning the text and a skip count."""
    out: list[str] = []
    skipped = 0
    for ch in text:
        code = ord(ch)
        if ASCII_LO <= code <= ASCII_HI:
            out.append(chr(TAG_BASE + code))
        else:
            skipped += 1
    return "".join(out), skipped


def decode(text: str) -> tuple[str, int]:
    """Map tag-plane codepoints back to printable ASCII, dropping other characters."""
    out: list[str] = []
    skipped = 0
    for ch in text:
        code = ord(ch)
        if TAG_BASE + ASCII_LO <= code <= TAG_BASE + ASCII_HI:
            out.append(chr(code - TAG_BASE))
        elif code in (TAG_START, TAG_END) or ch.isspace():
            continue  # the optional carrier brackets and plain whitespace are not payload
        else:
            skipped += 1
    return "".join(out), skipped


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Encode text into the Unicode tag plane or decode it back."
    )
    parser.add_argument("text", nargs="?", help="text to transform; stdin when omitted")
    parser.add_argument(
        "--decode", action="store_true", help="recover text from a tagged sample"
    )
    parser.add_argument(
        "--wrap",
        action="store_true",
        help="bracket the encoded form with the start and end tag codepoints",
    )
    args = parser.parse_args(argv)

    text = args.text if args.text is not None else sys.stdin.read()
    if args.decode:
        result, skipped = decode(text)
    else:
        result, skipped = encode(text)
        if args.wrap:
            result = chr(TAG_START) + result + chr(TAG_END)

    sys.stdout.write(result + "\n")
    if skipped:
        sys.stderr.write(f"skipped {skipped} character(s) with no tag-plane mapping\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
