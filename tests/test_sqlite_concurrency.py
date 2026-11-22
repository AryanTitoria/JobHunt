import os
from pathlib import Path
import subprocess
import sys
import tempfile
from urllib.parse import quote
from django.test import SimpleTestCase


class SQLiteConcurrencyRegression(SimpleTestCase):
    def test_upload_and_discovery_use_short_file_backed_transactions(self):
        with tempfile.TemporaryDirectory() as directory:
            env = os.environ.copy()
            env['DATABASE_URL'] = 'sqlite:///' + quote((Path(directory) / 'concurrency.sqlite3').as_posix(), safe='/:')
            env['DATA_DIR'] = directory
            env['DEBUG'] = 'true'
            env['DEMO_MODE'] = 'false'
            result = subprocess.run([sys.executable, str(Path(__file__).with_name('sqlite_concurrency_scenario.py'))],
                env=env, capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('no lock errors', result.stdout)
