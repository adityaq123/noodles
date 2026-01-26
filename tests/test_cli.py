import hashlib
import json
from pathlib import Path

import pytest

from unslop import cli


@pytest.fixture(autouse=True)
def disable_overlay(monkeypatch):
    monkeypatch.setenv("UNSLOP_DISABLE_OVERLAY", "1")


def test_cli_run_records_filtered_files_and_reports_new(tmp_path, monkeypatch, capsys):
    """Ensure hidden/ignored files are skipped and new files are reported."""
    (tmp_path / "alpha.txt").write_text("alpha", encoding="utf-8")
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / "data.bin").write_bytes(b"\x00\x01")

    (tmp_path / ".secret.txt").write_text("secret", encoding="utf-8")
    hidden_dir = tmp_path / ".cache"
    hidden_dir.mkdir()
    (hidden_dir / "ignored.txt").write_text("cache", encoding="utf-8")

    (tmp_path / ".gitignore").write_text("ignored.log\nlogs/\n", encoding="utf-8")
    (tmp_path / "ignored.log").write_text("ignore me", encoding="utf-8")
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "nested.txt").write_text("ignore me", encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    cli.main(["run"])
    output = capsys.readouterr().out

    assert "New files:" in output
    assert "+ added file: alpha.txt" in output
    assert "+ added file: nested/data.bin" in output

    manifest_file = _latest_manifest(tmp_path / ".unslop" / "manifest")
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))

    files = manifest["files"]
    assert sorted(files) == ["alpha.txt", "nested/data.bin"]
    assert files["alpha.txt"]["size"] == len("alpha")
    assert files["alpha.txt"]["hash"] == hashlib.sha256(b"alpha").hexdigest()
    assert files["nested/data.bin"]["size"] == 2
    assert "mtime" in files["alpha.txt"]


def test_cli_reports_changes_and_skips_unchanged_runs(tmp_path, monkeypatch, capsys):
    """Run twice and ensure only changes produce manifests."""
    original = tmp_path / "file.txt"
    original.write_text("hello", encoding="utf-8")
    extra = tmp_path / "extra.txt"
    extra.write_text("extra", encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    cli.main(["run"])
    capsys.readouterr()  # clear initial output
    first_manifest_count = _manifest_count(tmp_path)

    # Modify, delete, and add files.
    original.write_text("hello world", encoding="utf-8")
    extra.unlink()
    (tmp_path / "new.txt").write_text("brand new", encoding="utf-8")

    cli.main(["run"])
    output = capsys.readouterr().out

    assert "Modified files:" in output
    assert "~ modified file: file.txt" in output
    assert "Deleted files:" in output
    assert "- deleted file: extra.txt" in output
    assert "New files:" in output
    assert "+ added file: new.txt" in output
    assert _manifest_count(tmp_path) == first_manifest_count + 1

    # Running again without changes should produce no manifest.
    cli.main(["run"])
    output = capsys.readouterr().out
    assert output.strip() == "No change detected."
    assert _manifest_count(tmp_path) == first_manifest_count + 1


def test_run_converts_existing_marker_file(tmp_path, monkeypatch, capsys):
    """If a legacy .unslop file exists, it becomes a directory."""
    marker = tmp_path / ".unslop"
    marker.write_text("legacy marker", encoding="utf-8")
    (tmp_path / "file.txt").write_text("content", encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    cli.main(["run"])
    output = capsys.readouterr().out
    assert "Wrote manifest:" in output

    workspace = tmp_path / ".unslop" / "manifest"
    assert workspace.is_dir()
    manifest_file = _latest_manifest(workspace)
    assert manifest_file.is_file()


def _latest_manifest(workspace: Path) -> Path:
    manifests = sorted(workspace.glob("manifest-*.json"))
    assert manifests, "expected at least one manifest file"
    return manifests[-1]


def _manifest_count(root: Path) -> int:
    workspace = root / ".unslop" / "manifest"
    if not workspace.exists():
        return 0
    return len(list(workspace.glob("manifest-*.json")))
