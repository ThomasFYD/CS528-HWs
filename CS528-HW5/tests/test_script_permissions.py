"""Regression check that deployment archives preserve executable scripts."""
import io
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

import infra


class ArchivePermissionsTests(unittest.TestCase):
    def test_executable_entrypoints_survive_source_packaging(self):
        names=("config.py", "web_server.py", "hw4_service.py", "reporter.py", "request_data.py",
               "database.py", "setup_schema.py", "requirements.txt", "requirements-reporter.txt", "startup.sh")
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            for name in names:
                path=root/name;path.write_text("fixture\n")
                path.chmod(0o755 if name in ("startup.sh","setup_schema.py") else 0o644)
            with patch.object(infra,"ROOT",root),patch.object(infra,"cloud"):
                digest,uri=infra.archive_source()
            payload=(root/"build"/f"source-{digest}.tar.gz").read_bytes()
            with tarfile.open(fileobj=io.BytesIO(payload),mode="r:gz") as archive:
                self.assertEqual(archive.getmember("startup.sh").mode,0o755)
                self.assertEqual(archive.getmember("setup_schema.py").mode,0o755)
                self.assertEqual(archive.getmember("config.py").mode,0o644)


if __name__=="__main__": unittest.main()
