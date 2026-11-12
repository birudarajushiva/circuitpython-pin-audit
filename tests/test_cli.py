import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from pin_audit.cli import main, render
from pin_audit import Diagnostic, Report


GOOD = 'import board, digitalio\na = digitalio.DigitalInOut(board.D0)\n'
BAD = GOOD + 'b = digitalio.DigitalInOut(board.D0)\n'


class CLITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def file(self, name, source):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding='utf-8')
        return str(path)

    def run_cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            result = main(list(args))
        return result, out.getvalue(), err.getvalue()

    def test_conflict_json_and_exit_status(self):
        status, out, _ = self.run_cli(self.file('bad.py', BAD), '--format', 'json')
        self.assertEqual(status, 1)
        report = json.loads(out)
        self.assertEqual(report['schema_version'], 1)
        self.assertEqual(report['files'][0]['diagnostics'][0]['related_line'], 2)

    def test_clean_exit_status_and_no_false_safety_claim(self):
        status, out, _ = self.run_cli(self.file('good.py', GOOD))
        self.assertEqual(status, 0)
        self.assertIn('does not establish hardware safety', out)

    def test_syntax_error_is_operational_failure(self):
        status, out, _ = self.run_cli(self.file('broken.py', 'if ('))
        self.assertEqual(status, 2)
        self.assertIn('PA900', out)

    def test_missing_input(self):
        status, _, err = self.run_cli(str(self.root / 'missing.py'))
        self.assertEqual(status, 2)
        self.assertIn('does not exist', err)

    def test_empty_directory_is_not_success(self):
        self.assertEqual(self.run_cli(str(self.root))[0], 2)

    def test_each_file_is_independent(self):
        self.file('one.py', GOOD)
        self.file('two.py', GOOD)
        status, out, _ = self.run_cli(str(self.root), '--format', 'json')
        self.assertEqual(status, 0)
        self.assertEqual(len(json.loads(out)['files']), 2)

    def test_exclude_and_default_environment_skips(self):
        self.file('good.py', GOOD)
        self.file('fixtures/bad.py', BAD)
        self.file('.venv/bad.py', BAD)
        status, out, _ = self.run_cli(str(self.root), '--exclude', 'fixtures', '--format', 'json')
        self.assertEqual(status, 0)
        self.assertEqual(len(json.loads(out)['files']), 1)

    def test_repeated_inputs_are_deduplicated(self):
        path = self.file('good.py', GOOD)
        status, out, _ = self.run_cli(path, str(self.root), '--format', 'json')
        self.assertEqual(status, 0)
        self.assertEqual(len(json.loads(out)['files']), 1)

    def test_strict_coverage_gaps(self):
        path = self.file('unknown.py', 'import board\nbus = board.I2C()')
        self.assertEqual(self.run_cli(path)[0], 0)
        self.assertEqual(self.run_cli(path, '--strict')[0], 1)

    def test_strict_rejects_stale_alias_after_augmented_list_mutation(self):
        path = self.file('mutated.py', '''import board, keypad
pins = [board.D0]
alias = pins
pins += [board.D1]
keys = keypad.Keys(alias, value_when_pressed=False)
''')
        status, out, _ = self.run_cli(path, '--strict', '--format', 'json')
        self.assertEqual(status, 1)
        self.assertTrue(json.loads(out)['files'][0]['incomplete'])

    def test_explicit_alias_file(self):
        path = self.file('alias.py', GOOD + 'b = digitalio.DigitalInOut(board.LED)\n')
        config = self.file('pins.json', '{"aliases": [["D0", "LED"]]}')
        self.assertEqual(self.run_cli(path)[0], 0)
        self.assertEqual(self.run_cli(path, '--aliases', config)[0], 1)

    def test_malformed_alias_file(self):
        path = self.file('good.py', GOOD)
        for content in ['{', '[]', '{"aliases": "D0"}', '{"aliases": [["D0", 1]]}', '{"aliases": [["board.D0", "LED"]]}']:
            config = self.file('aliases.json', content)
            self.assertEqual(self.run_cli(path, '--aliases', config)[0], 2)

    def test_github_output_escapes_filename_and_message(self):
        report = Report('bad,colon:%\n.py', [Diagnostic('PA001', 'error', 1, 1, 'first\nsecond%')])
        out = render([report], 'github')
        self.assertEqual(len(out.splitlines()), 1)
        self.assertIn('%2Ccolon%3A%25%0A', out)
        self.assertIn('first%0Asecond%25', out)
        self.assertTrue(out.startswith('::error '))

    def test_symlink_input_is_rejected(self):
        target = Path(self.file('good.py', GOOD))
        link = self.root / 'link.py'
        try:
            link.symlink_to(target)
        except OSError:
            self.skipTest('symlinks are unavailable')
        self.assertEqual(self.run_cli(str(link))[0], 2)

    def test_encoding_cookie(self):
        path = self.root / 'latin.py'
        path.write_bytes(b'# coding: latin-1\n# caf\xe9\n' + GOOD.encode())
        self.assertEqual(self.run_cli(str(path))[0], 0)

    def test_firmware_side_effects_are_never_executed(self):
        sentinel = self.root / 'must-not-exist'
        path = self.file('side_effect.py', f'open({str(sentinel)!r}, "w").write("oops")\n' + GOOD)
        self.assertEqual(self.run_cli(path)[0], 0)
        self.assertFalse(sentinel.exists())

    def test_oversized_file_is_error(self):
        path = self.file('big.py', '#' * (2 * 1024 * 1024 + 1))
        self.assertEqual(self.run_cli(path)[0], 2)


if __name__ == '__main__':
    unittest.main()
