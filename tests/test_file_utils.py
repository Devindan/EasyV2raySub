import os
import stat
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from file_utils import atomic_write_text


class AtomicWriteTextTests(unittest.TestCase):
    def test_new_destination_uses_regular_file_permissions_from_umask(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "new.txt"
            previous_umask = os.umask(0o222)
            try:
                atomic_write_text(output, "content")
            finally:
                os.umask(previous_umask)

            self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o444)

    def test_new_destination_calculates_mode_from_current_umask(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "new.txt"

            with patch("file_utils.os.umask", side_effect=[0o027, 0]), patch(
                "file_utils.os.chmod", wraps=os.chmod
            ) as chmod:
                atomic_write_text(output, "content")

            self.assertIn(0o640, [call.args[1] for call in chmod.call_args_list])

    def test_replacement_applies_the_existing_destination_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "existing.txt"
            output.write_text("old", encoding="utf-8")
            fake_stat = SimpleNamespace(st_mode=0o100604)

            with patch.object(Path, "stat", return_value=fake_stat), patch(
                "file_utils.os.chmod", wraps=os.chmod
            ) as chmod:
                atomic_write_text(output, "new")

            self.assertIn(0o604, [call.args[1] for call in chmod.call_args_list])
            self.assertEqual(output.read_text(encoding="utf-8"), "new")


@unittest.skipUnless(os.name == "posix", "POSIX permission semantics required")
class PosixAtomicWriteTextTests(unittest.TestCase):
    def test_new_destination_uses_permissions_derived_from_current_umask(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "new.txt"
            previous_umask = os.umask(0o027)
            try:
                atomic_write_text(output, "content")
            finally:
                os.umask(previous_umask)

            self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o640)

    def test_replacement_preserves_existing_non_default_permissions(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "existing.txt"
            output.write_text("old", encoding="utf-8")
            output.chmod(0o604)

            atomic_write_text(output, "new")

            self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o604)


if __name__ == "__main__":
    unittest.main()
