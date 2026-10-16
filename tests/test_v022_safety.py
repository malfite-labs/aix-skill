from __future__ import annotations

import hashlib
import json
import pathlib
import subprocess
import sys

import pytest

SKILL_DIR = pathlib.Path(__file__).resolve().parents[1] / "skills" / "aix"
sys.path.insert(0, str(SKILL_DIR))
from aix_client import AixClient, AixError  # noqa: E402
from aix_installation import installation_status  # noqa: E402


def test_failed_delivery_export_does_not_remove_existing_user_files(tmp_path):
    destination = tmp_path / "exports"
    destination.mkdir()
    sentinel = destination / "keep.txt"
    sentinel.write_text("user data", encoding="utf-8")
    client = object.__new__(AixClient)
    client.read_delivery = lambda assignment_id: {
        "result_submitted": True,
        "results": [{"delivery": {"structured_output": "# Actual delivery"}}],
    }
    client.list_files = lambda assignment_id: {
        "files": [{"file_id": "file-1", "sha256": "0" * 64}],
    }

    def fail_download(*args, **kwargs):
        raise AixError(502, {"code": "TEST_DOWNLOAD_FAILURE"})

    client.download_file = fail_download
    with pytest.raises(AixError):
        client.download_delivery("assignment-1", str(destination))

    assert sentinel.read_text(encoding="utf-8") == "user data"
    assert list(destination.iterdir()) == [sentinel]


def test_installation_diagnostics_are_read_only(tmp_path):
    existing_skill = tmp_path / "existing-skill"
    existing_skill.mkdir()
    sentinel = existing_skill / "user.md"
    sentinel.write_text("keep me", encoding="utf-8")

    installation_status(existing_skill)

    assert sentinel.read_text(encoding="utf-8") == "keep me"
    assert list(existing_skill.iterdir()) == [sentinel]


def test_v022_provenance_pins_the_source_snapshot_and_package_files():
    repo = pathlib.Path(__file__).resolve().parents[1]
    provenance = json.loads((repo / "V0_2_2_PROVENANCE.json").read_text(encoding="utf-8"))
    source_commit = provenance["public_source_commit"]
    assert len(source_commit) == 40
    assert provenance["public_source_repository"] == "https://github.com/malfite-labs/aix-skill"
    assert source_commit in provenance["source_commit_url"]
    subprocess.run(["git", "cat-file", "-e", f"{source_commit}^{{commit}}"], cwd=repo, check=True)
    assert provenance["artifact_sha256"] == "a3fc1dfdd1c95b2d91e435ef2d80909da33c055cc3ef697eb429ca6fffa031e0"
    assert provenance["source_file_sha256"]
    for name, expected in provenance["source_file_sha256"].items():
        path = repo / "skills" / "aix" / pathlib.PurePosixPath(name)
        assert path.is_file()
        assert hashlib.sha256(path.read_bytes()).hexdigest() == expected
