"""Parse cURL text without invoking a shell or performing any I/O."""
import argparse
import shlex
from pathlib import Path


class CurlParser(argparse.ArgumentParser):
    def error(self, message):
        # argparse's usual message echoes raw arguments, possibly including credentials.
        raise ValueError("Unsupported or incomplete cURL arguments; see README for supported options")


def parse_command(command: str):
    # No shell evaluation, file indirection, environment expansion, or HTTP request.
    try:
        tokens = shlex.split(command.replace("\r\n", "\n"), posix=True)
        # shlex retains an unquoted backslash-newline separator as a newline token.
        # Remove that separator, without rewriting backslashes inside quoted JSON.
        tokens = [token for token in tokens if token != "\n"]
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
