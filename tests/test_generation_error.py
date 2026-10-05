import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from koala.desktop import dispatch, DiagnosticStream


class GenerationErrorTests(unittest.TestCase):
    def test_specific_cli_failure_reaches_desktop_dialog(self):
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d)/'project';dispatch({'action':'create','folder':str(folder)})
            def fail(args):
                print('Checking evidence…',file=sys.stderr)
                print('KOALA: Citation research is incomplete: 122 supported works; 300 required.',file=sys.stderr)
                return 2
            with patch('koala.cli.main',side_effect=fail),patch('sys.stderr',io.StringIO()):
                with self.assertRaisesRegex(ValueError,'122 supported works; 300 required'):
                    dispatch({'action':'generate','folder':str(folder)})

    def test_split_writes_forward_progress_and_capture_error(self):
        out=io.StringIO();stream=DiagnosticStream(out)
        for part in ('Progress\nKOA','LA: Underlying failure','\nLater progress\n'):stream.write(part)
        stream.flush()
        self.assertEqual(stream.error,'Underlying failure')
        self.assertIn('Later progress',out.getvalue())
