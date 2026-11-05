"""Tests for transcripts.py: what is redacted before a transcript reaches the shared drive."""
import io
import json
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

_SCRIPT_PATH = Path(__file__).resolve().parents[1] / 'alice' / 'transcripts.py'
_spec = spec_from_file_location('transcripts', _SCRIPT_PATH)
transcripts = module_from_spec(_spec)
_spec.loader.exec_module(transcripts)


def test_credentials_are_redacted_as_a_transcript_line_stores_them():
    """A tool result is stored JSON-escaped, so a secret holding a quote or a backslash, an
    environment password and a private key block are all replaced by their names."""
    secrets = {'alice/database-read-login': 'pa"ss\\word123',
               'TEST_LOGIN_PASSWORD': 'hunter2hunter2'}
    line = json.dumps({'content': 'pw=pa"ss\\word123, hunter2hunter2, '
                       '-----BEGIN PRIVATE KEY-----\nAAAA\n-----END PRIVATE KEY----- done'})
    redacted = transcripts.redact(line, secrets)
    assert 'word123' not in redacted and 'hunter2' not in redacted and 'AAAA' not in redacted
    assert json.loads(redacted)['content'] == (
        'pw=[redacted alice/database-read-login], [redacted TEST_LOGIN_PASSWORD],'
        ' [redacted private key] done')


def test_redaction_keeps_the_line_valid_json_whatever_the_secret_holds():
    """A secret starting with a quote or ending with a backslash, printed by a tool as JSON and
    stored escaped once more, is redacted and the line still parses."""
    secret = '"edge\\'
    printed = json.dumps({'value': secret})
    line = json.dumps({'content': f'result: {printed}'})
    redacted = transcripts.redact(line, {'alice/x': secret})
    assert 'edge' not in redacted
    json.loads(redacted)


def test_a_password_in_a_connection_uri_is_redacted():
    """Connection-URI values carry their password inside the URI."""
    line = json.dumps({'content': 'db://reader:s3cr3t-pw@db.example:5432/app'})
    assert 's3cr3t' not in transcripts.redact(line, {})


def test_unicode_line_separators_and_lone_surrogates_survive_redaction():
    """JSON.stringify leaves U+2028 raw inside a string and escapes a lone surrogate (a cut
    emoji): the line stays one valid line, and the result encodes as UTF-8."""
    line = '{"content": "a\u2028b", "cut": "\\ud83d"}'
    redacted = transcripts.redact(line, {})
    assert redacted.count('\n') == 1
    assert json.loads(redacted)['content'] == 'a\u2028b'
    redacted.encode('utf-8')


def _write_session(tmp_path, events):
    path = tmp_path / 'session-abc.jsonl'
    path.write_text('\n'.join(json.dumps(event) for event in events) + '\n', encoding='utf-8')
    return path


def _user(time, text):
    return {'type': 'user', 'timestamp': time, 'message': {'content': text}}


def _call(time, command, result, is_error=False):
    return [
        {'type': 'assistant', 'timestamp': time, 'message': {'content': [
            {'type': 'tool_use', 'name': 'Bash', 'input': {'command': command}}]}},
        {'type': 'user', 'timestamp': time, 'message': {'content': [
            {'type': 'tool_result', 'content': result, 'is_error': is_error}]}},
    ]


def test_extract_keeps_failures_whole_and_cuts_other_results(tmp_path):
    """A reader sees every error in full, and a long successful result only at its two ends."""
    session = _write_session(tmp_path, [
        _user('2026-11-02T10:00:00Z', 'Work issue #1'),
        *_call('2026-11-02T10:01:00Z', 'pytest', 'F' * 3000 + 'END-OF-FAILURE', is_error=True),
        *_call('2026-11-02T10:02:00Z', 'cat big.py', 'HEAD' + 'x' * 5000 + 'TAIL'),
    ])
    [part] = transcripts.extract(session, tmp_path / 'out', None)
    text = (tmp_path / 'out' / 'session-abc.part1.txt').read_text(encoding='utf-8')
    assert 'END-OF-FAILURE' in text
    assert 'HEAD' in text and 'TAIL' in text and 'characters cut' in text
    assert part['characters'] < 5000
    assert max(len(line) for line in text.split('\n')) <= transcripts.LINE_WIDTH + 2


def test_extract_breaks_parts_between_rounds_and_opens_each_with_the_first_request(
        tmp_path, monkeypatch):
    """Rounds that do not fit one reader go to separate parts, each part after the first
    carrying the session's opening request, and --since leaves out rounds that ended before."""
    monkeypatch.setattr(transcripts, 'READER_BUDGET', 600)
    session = _write_session(tmp_path, [
        _user('2026-10-20T10:00:00Z', 'Work issue #1'),
        *_call('2026-10-20T10:01:00Z', 'ls', 'a' * 300),
        _user('2026-11-02T10:00:00Z', 'Round two: the review asks for a test'),
        *_call('2026-11-02T10:01:00Z', 'pytest', 'b' * 300),
        _user('2026-11-03T10:00:00Z', 'Round three: merge'),
        *_call('2026-11-03T10:01:00Z', 'gh pr merge', 'c' * 300),
    ])
    parts = transcripts.extract(session, tmp_path / 'all', None)
    texts = [Path(part['file']).read_text(encoding='utf-8') for part in parts]
    assert len(parts) == 3
    assert all('Work issue #1' in text for text in texts)
    assert 'Round two' in texts[1] and 'Round three' not in texts[1]

    recent = transcripts.extract(session, tmp_path / 'week', '2026-11-01')
    assert [Path(part['file']).read_text(encoding='utf-8').count('Round two') for part in recent] \
        == [1, 0]


def test_a_round_larger_than_one_reader_is_split_between_entries(tmp_path, monkeypatch):
    """A single long round still yields parts within the budget, cut only between entries."""
    monkeypatch.setattr(transcripts, 'READER_BUDGET', 2000)
    session = _write_session(tmp_path, [
        _user('2026-11-02T10:00:00Z', 'Work issue #1'),
        *[event for minute in range(10)
          for event in _call(f'2026-11-02T10:{minute:02d}:00Z', f'step {minute}', 'r' * 400)],
    ])
    parts = transcripts.extract(session, tmp_path / 'out', None)
    texts = [Path(part['file']).read_text(encoding='utf-8') for part in parts]
    assert len(parts) > 1
    assert all(text.count('step ') == text.count('TOOL Bash') for text in texts)
    assert ''.join(texts).count('TOOL Bash') == 10


def test_a_secret_with_non_ascii_text_is_redacted_as_json_stringify_prints_it():
    """JSON.stringify keeps non-ASCII characters but escapes a quote, a form neither the raw
    value nor Python's ASCII-escaped JSON matches."""
    secret = 'pässwörd"42'
    printed = json.dumps({'token': secret}, ensure_ascii=False)
    line = json.dumps({'content': f'result: {printed}'})
    assert 'sswör' not in json.loads(transcripts.redact(line, {'alice/x': secret}))['content']


def test_the_hook_skips_the_upload_when_a_secret_cannot_be_read(tmp_path, monkeypatch, capsys):
    """A hook that exits non-zero shows an error on her turn, so an unreadable secret skips the
    upload and the hook still returns normally."""
    transcript = tmp_path / 'session.jsonl'
    transcript.write_text('{"type": "user"}\n', encoding='utf-8')
    monkeypatch.setattr(transcripts.subprocess, 'run', lambda *args, **kwargs: type(
        'Completed', (), {'returncode': 255, 'stderr': 'access denied', 'stdout': ''})())
    monkeypatch.setattr(transcripts.sys, 'stdin', io.StringIO(json.dumps(
        {'session_id': 'abc', 'transcript_path': str(transcript)})))
    transcripts.hook()
    assert 'transcript upload skipped' in capsys.readouterr().err
