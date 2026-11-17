"""Postman cURLs may continue at column zero; indentation is not syntax."""
import json

import pytest

from curl_mcp.curl import parse_command
from curl_mcp.curl_auth import load_curl
from curl_mcp.generate import generate_project, parse_curl


@pytest.mark.parametrize('newline', ['\n', '\r\n'])
@pytest.mark.parametrize('indent', ['', '  ', '\t'])
def test_postman_business_and_auth_continuations(tmp_path, newline, indent):
    def lines(parts):
        return (' \\' + newline + indent).join(parts)

    body = {'agentNo': 'example-agent', 'clientMainIdSet': ['example-a', 'example-b']}
    command = lines([
        "curl --location --request POST 'https://api.example/customer-search/detail-info'",
        "--header 'token: ${token}'",
        "--header 'Content-Type: application/json'",
        "--data-raw '" + json.dumps(body, indent=2) + "'",
    ])
    assert parse_curl(command) == ('https://api.example/customer-search/detail-info', body)
    curls = tmp_path / 'curls'
    curls.mkdir()
    (curls / 'customer_detail.txt').write_bytes(command.encode('utf-8'))
    auth = tmp_path / 'auth_curls'
    auth.mkdir()
    (auth / 'customer_detail.txt').write_bytes(lines([
        "curl --request POST 'https://auth.example/token'",
        "--url-query 'client_id=${env.CLIENT_ID}'",
        "--url-query 'client_secret=${env.CLIENT_SECRET}'",
    ]).encode('utf-8'))
    spec, config = generate_project(curls, token_path='/access_token')
    operation = config['operations']['customer_detail']
    assert operation['headers'] == {'token': '${token}'}
    assert operation['auth'] == {'curl': 'auth_curls/customer_detail.txt', 'token_path': '/access_token'}
    assert spec['paths']['/customer-search/detail-info']['post']['operationId'] == 'customer_detail'
    provider = load_curl(tmp_path, operation['auth']['curl'], '/access_token',
                         {'CLIENT_ID': 'example', 'CLIENT_SECRET': 'test-only'})
    assert 'client_id=example' in provider.url


def test_single_quoted_backslash_newline_and_json_escapes_are_not_rewritten():
    value = "first\\\nsecond"
    args = parse_command("curl https://api.example/query --data-raw '" + value + "'")
    assert args.body == [value]
    body = {'path': 'C:\\folder\\file', 'text': 'first\nsecond', 'quote': '"'}
    assert parse_curl("curl https://api.example/query --json '" + json.dumps(body) + "'")[1] == body


def test_double_quoted_and_mid_option_continuations_follow_shell_rules():
    command = 'curl "https://api.example/\\\nquery" --he\\\nader "Content-Type: application/json" --json \'{}\''
    assert parse_curl(command) == ('https://api.example/query', {})


def test_quoted_newline_is_not_silently_discarded():
    assert parse_command("curl https://api.example/query --data-raw '\n'").body == ['\n']
