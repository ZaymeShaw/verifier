"""Parse cURL text without invoking a shell or performing any I/O."""
import argparse
import shlex
from pathlib import Path


class CurlParser(argparse.ArgumentParser):
    def error(self, message):
        # argparse's usual message echoes raw arguments, possibly including credentials.
        raise ValueError("Unsupported or incomplete cURL arguments; see README for supported options")


def join_continuations(command: str) -> str:
    """Remove shell backslash-newlines, preserving single-quoted data verbatim.

    shlex does not implement this shell rule: an unindented continuation
    otherwise becomes part of the next option token, e.g. '\\n--header'.
    """
    result = []
    quote = None
    index = 0
    while index < len(command):
        char = command[index]
        if char == "\\" and quote != "'" and index + 1 < len(command):
            following = command[index + 1]
            if following != "\n":
                # Preserve escapes for shlex, without interpreting escaped quotes here.
                result.extend((char, following))
            index += 2
            continue
        if char in ("'", '"'):
            if quote is None:
                quote = char
            elif quote == char:
                quote = None
        result.append(char)
        index += 1
    return "".join(result)


def parse_command(command: str):
    # No shell evaluation, file indirection, environment expansion, or HTTP request.
    try:
        tokens = shlex.split(join_continuations(command.replace("\r\n", "\n")), posix=True)
    except ValueError:
        raise ValueError("Invalid shell quoting in cURL text") from None
    if not tokens or Path(tokens[0]).name != "curl":
        raise ValueError("Input must contain one Bash-style curl command")
    parser = CurlParser(add_help=False, allow_abbrev=False)
    parser.add_argument("url", nargs="?")
    parser.add_argument("--url", dest="option_urls", action="append", default=[])
    parser.add_argument("-X", "--request")
    parser.add_argument("-H", "--header", action="append", default=[])
    data = parser.add_mutually_exclusive_group()
    data.add_argument("-d", "--data", "--data-raw", "--data-binary", action="append", dest="body")
    data.add_argument("--json", action="append")
    data.add_argument("--data-urlencode", action="append", default=[])
    parser.add_argument("--url-query", action="append", default=[])
    # Recognize these copied request options, but don't put them in the tool schema.
    for short, long in [("-b", "--cookie"), ("-u", "--user"), ("-A", "--user-agent"),
                        ("-m", "--max-time")]:
        parser.add_argument(short, long)
    parser.add_argument("--connect-timeout")
    for flags in [("-L", "--location"), ("-k", "--insecure"), ("-s", "--silent"),
                  ("-S", "--show-error"), ("-i", "--include"), ("-v", "--verbose"),
                  ("--compressed",), ("--globoff",)]:
        parser.add_argument(*flags, action="store_true")
    args = parser.parse_args(tokens[1:])
    urls = ([args.url] if args.url else []) + args.option_urls
    if len(urls) != 1:
        raise ValueError("Provide exactly one HTTP(S) URL")
    args.url = urls[0]
    return args
