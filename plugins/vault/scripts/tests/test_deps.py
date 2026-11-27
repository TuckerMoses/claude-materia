"""A script run by a python3 without PyYAML or jsonschema must say so plainly, not die in a traceback."""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[2]
SCRIPTS = [
    PLUGIN / 'scripts' / 'label-bank',
    PLUGIN / 'scripts' / 'label-proposals',
    PLUGIN / 'scripts' / 'relabel-notes',
    PLUGIN / 'skills' / 'ingest' / 'scripts' / 'commit-run',
    PLUGIN / 'skills' / 'ingest' / 'scripts' / 'dispatch-targets',
    PLUGIN / 'skills' / 'ingest' / 'scripts' / 'ingest-status',
    PLUGIN / 'skills' / 'ingest' / 'scripts' / 'source-delta',
    PLUGIN / 'skills' / 'ingest' / 'scripts' / 'note-outcome',
]


class MissingModules(unittest.TestCase):
    def test_plain_message_names_interpreter_and_module(self):
        with tempfile.TemporaryDirectory() as vault:
            for script in SCRIPTS:
                with self.subTest(script=script.name):
                    # -S: no site-packages, so the third-party modules cannot be found.
                    r = subprocess.run([sys.executable, '-S', str(script), '--recover', vault],
                                       capture_output=True, text=True, timeout=60)
                    self.assertNotEqual(r.returncode, 0)
                    self.assertNotIn('Traceback', r.stderr)
                    self.assertIn('has no module', r.stderr)
                    self.assertIn('PyYAML', r.stderr)
                    self.assertIn(sys.executable, r.stderr)


if __name__ == '__main__':
    unittest.main()
