"""status's marked-then-modified net must compare a day-file with the LATEST run that marked it.

A re-drain (remove the marker, drain again) leaves the older run's record in the log. Judged against
that older run, the file would be flagged forever and the documented fix could never clear it."""
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

STATUS = Path(__file__).resolve().parents[1] / 'ingest-status'


def vault(runs, mtime):
    root = Path(tempfile.mkdtemp())
    (root / 'notes').mkdir()
    (root / 'journal').mkdir()
    (root / '_machine' / 'logs' / 'ingest').mkdir(parents=True)
    (root / '_machine' / 'labels.yml').write_text('labels: {}\n')
    (root / '_machine' / 'routing.yml').write_text('targets:\n  notes:\n    adapter: notes\nrules:\n  - match: ["*"]\n    to: [notes]\n')
    (root / '_machine' / 'ingest_paths.yml').write_text('sources: []\n')
    day = root / 'journal' / '2020-01-01.md'
    day.write_text('---\ningested: true\n---\nA thought.\n')
    os.utime(day, (mtime, mtime))
    for name, ts in runs:
        d = root / '_machine' / 'logs' / 'ingest' / name
        d.mkdir()
        (d / 'run.json').write_text(json.dumps({'ts': ts, 'marked': ['journal/2020-01-01.md']}))
    return root


def status(root):
    env = {k: v for k, v in os.environ.items() if k != 'AGENT_LIB'}
    return subprocess.run([sys.executable, str(STATUS), str(root)], capture_output=True, text=True, timeout=120, env=env).stdout


class Remarked(unittest.TestCase):
    def test_edit_after_the_only_marking_run_is_flagged(self):
        now = int(time.time())
        out = status(vault([('2020-01-02-1', now - 5000)], now - 1000))
        self.assertIn('modified AFTER ingest', out)
        self.assertIn('journal/2020-01-01.md', out)

    def test_a_later_run_that_re_marked_the_file_clears_the_flag(self):
        now = int(time.time())
        out = status(vault([('2020-01-02-1', now - 5000), ('2020-01-05-1', now - 900)], now - 1000))
        self.assertNotIn('modified AFTER ingest', out)

    def test_an_edit_after_the_latest_marking_run_is_still_flagged(self):
        now = int(time.time())
        out = status(vault([('2020-01-02-1', now - 5000), ('2020-01-05-1', now - 2000)], now - 1000))
        self.assertIn('modified AFTER ingest', out)


if __name__ == '__main__':
    unittest.main()
