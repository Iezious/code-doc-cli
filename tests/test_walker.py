"""Tests for the file walker.

One test per rule in ``docs/architecture/architecture.md``'s "Indexer
walking" section, exercised against fixture trees laid out under
``tests/fixtures/walker/`` (the encoding fixture, which needs raw non-UTF-8
bytes) or built in ``tmp_path`` (everything else — keeps binary blobs and
symlinks out of the checked-in tree).
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from code_index.config import CodeIndexConfig
from code_index.walker import MAX_FILE_SIZE, WalkedFile, walk

FIXTURES = Path(__file__).parent / "fixtures" / "walker"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _config(
    *,
    ignores: list[str] | None = None,
    languages: list[str] | None = None,
    extra_languages: list[str] | None = None,
) -> CodeIndexConfig:
    """Build a minimal resolved config sufficient to drive the walker.

    Only the fields the walker reads (``ignores``, ``languages``,
    ``extra_languages``) carry meaningful values; the rest are filled with
    the documented defaults so the dataclass validates.
    """
    return CodeIndexConfig(
        version=">=0.1,<1.0",
        project="walker-test",
        roots=["."],
        ignores=ignores if ignores is not None else [],
        languages=languages if languages is not None else ["python"],
        extra_languages=extra_languages if extra_languages is not None else [],
        embed_backend="fastembed",
        embed_model="jinaai/jina-embeddings-v2-base-code",
        embed_batch_size=32,
    )


def _rels(results: list[WalkedFile]) -> set[str]:
    """POSIX-style relative paths of yielded files, as a set for membership asserts."""
    return {r.rel_path.as_posix() for r in results}


def _can_symlink(tmp_path: Path) -> bool:
    """Probe whether the running user can create symlinks here.

    On Windows symlink creation requires Developer Mode or admin; CI may run
    without either. The probe creates and immediately removes a symlink so
    skipped tests are accurate without polluting the tree.
    """
    probe_target = tmp_path / "_sym_probe_target"
    probe_link = tmp_path / "_sym_probe_link"
    probe_target.write_text("x", encoding="utf-8")
    try:
        os.symlink(probe_target, probe_link)
    except (OSError, NotImplementedError):
        probe_target.unlink(missing_ok=True)
        return False
    probe_link.unlink()
    probe_target.unlink()
    return True


# ---------------------------------------------------------------------------
# .gitignore handling
# ---------------------------------------------------------------------------


def test_gitignore_honored_when_dot_git_present(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / ".gitignore").write_text("ignored.py\n", encoding="utf-8")
    (tmp_path / "kept.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "ignored.py").write_text("y = 2\n", encoding="utf-8")

    results = list(walk(tmp_path, _config()))
    rels = _rels(results)
    assert "kept.py" in rels
    assert "ignored.py" not in rels


def test_gitignore_inactive_when_dot_git_absent(tmp_path: Path) -> None:
    # Same shape as the previous test, minus the `.git/` marker.
    (tmp_path / ".gitignore").write_text("ignored.py\n", encoding="utf-8")
    (tmp_path / "kept.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "ignored.py").write_text("y = 2\n", encoding="utf-8")

    results = list(walk(tmp_path, _config()))
    rels = _rels(results)
    assert "kept.py" in rels
    # No `.git/`: `.gitignore` is silently inactive, so `ignored.py` surfaces.
    assert "ignored.py" in rels


def test_gitignore_nested_subdir(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / ".gitignore").write_text("# root has no rules\n", encoding="utf-8")
    sub = tmp_path / "sub"
    sub.mkdir()
    # Nested .gitignore only governs its own subtree.
    (sub / ".gitignore").write_text("local.py\n", encoding="utf-8")
    (sub / "local.py").write_text("z = 3\n", encoding="utf-8")
    (sub / "kept.py").write_text("z = 4\n", encoding="utf-8")
    (tmp_path / "local.py").write_text("a = 1\n", encoding="utf-8")

    results = list(walk(tmp_path, _config()))
    rels = _rels(results)
    assert "sub/kept.py" in rels
    assert "sub/local.py" not in rels
    # Root-level `local.py` is not under `sub/`, so the nested rule does not
    # reach it.
    assert "local.py" in rels


# ---------------------------------------------------------------------------
# Built-in default excludes
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "excluded_dir",
    [
        "node_modules",
        ".venv",
        "__pycache__",
        ".git",
        "dist",
        "build",
        ".idea",
        ".vscode",
    ],
)
def test_default_excludes_skip_top_level_dirs(tmp_path: Path, excluded_dir: str) -> None:
    target = tmp_path / excluded_dir
    target.mkdir()
    (target / "buried.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "kept.py").write_text("x = 1\n", encoding="utf-8")

    results = list(walk(tmp_path, _config()))
    rels = _rels(results)
    assert "kept.py" in rels
    assert f"{excluded_dir}/buried.py" not in rels


def test_default_excludes_skip_docs_helpers(tmp_path: Path) -> None:
    helpers = tmp_path / "docs" / ".helpers"
    helpers.mkdir(parents=True)
    (helpers / "config.toml").write_text("x = 1\n", encoding="utf-8")
    (helpers / "index.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "kept.py").write_text("x = 1\n", encoding="utf-8")

    results = list(walk(tmp_path, _config()))
    rels = _rels(results)
    assert "kept.py" in rels
    assert "docs/.helpers/index.py" not in rels


# ---------------------------------------------------------------------------
# config.ignores
# ---------------------------------------------------------------------------


def test_config_ignores_additive_with_defaults(tmp_path: Path) -> None:
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "buried.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "vendored").mkdir()
    (tmp_path / "vendored" / "gen.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "kept.py").write_text("x = 1\n", encoding="utf-8")

    cfg = _config(ignores=["vendored/"])
    results = list(walk(tmp_path, cfg))
    rels = _rels(results)
    assert "kept.py" in rels
    # config.ignores excludes the new path.
    assert "vendored/gen.py" not in rels
    # And the built-in default still applies.
    assert "node_modules/buried.py" not in rels


# ---------------------------------------------------------------------------
# Extension filter
# ---------------------------------------------------------------------------


def test_extension_filter_drops_unregistered(tmp_path: Path) -> None:
    (tmp_path / "kept.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "drop.txt").write_text("hello\n", encoding="utf-8")
    (tmp_path / "drop.foo").write_text("hello\n", encoding="utf-8")

    results = list(walk(tmp_path, _config()))
    rels = _rels(results)
    assert "kept.py" in rels
    assert "drop.txt" not in rels
    assert "drop.foo" not in rels


def test_extension_filter_respects_active_languages(tmp_path: Path) -> None:
    # Only python is active; .go file must be dropped even though the `go`
    # plugin is registered with `from_builtins`.
    (tmp_path / "kept.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "drop.go").write_text("package main\n", encoding="utf-8")

    results = list(walk(tmp_path, _config(languages=["python"])))
    rels = _rels(results)
    assert "kept.py" in rels
    assert "drop.go" not in rels


# ---------------------------------------------------------------------------
# Size cap
# ---------------------------------------------------------------------------


def test_oversize_file_is_skipped_with_warning(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    big = tmp_path / "big.py"
    # MAX_FILE_SIZE + 1 byte. ASCII so no decode trouble if it were processed.
    big.write_bytes(b"a" * (MAX_FILE_SIZE + 1))
    (tmp_path / "small.py").write_text("x = 1\n", encoding="utf-8")

    results = list(walk(tmp_path, _config()))
    rels = _rels(results)
    assert "small.py" in rels
    assert "big.py" not in rels
    err = capsys.readouterr().err
    assert "oversize" in err
    assert "big.py" in err


# ---------------------------------------------------------------------------
# Binary probe
# ---------------------------------------------------------------------------


def test_nul_byte_skips_plugin_registered_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # `.py` is plugin-registered; a NUL byte in the first 8 KiB must still
    # skip the file (belt-and-suspenders binary check).
    bad = tmp_path / "blob.py"
    bad.write_bytes(b"x = 1\n\x00binary stuff here\n")
    (tmp_path / "ok.py").write_text("x = 1\n", encoding="utf-8")

    results = list(walk(tmp_path, _config()))
    rels = _rels(results)
    assert "ok.py" in rels
    assert "blob.py" not in rels
    err = capsys.readouterr().err
    assert "binary" in err
    assert "blob.py" in err


def test_unknown_extension_skipped_regardless_of_nul(tmp_path: Path) -> None:
    # A .bin file is dropped by the extension filter — the NUL probe never
    # runs and the file is silently absent (no per-file warning).
    (tmp_path / "data.bin").write_bytes(b"\x00\x01\x02")
    (tmp_path / "kept.py").write_text("x = 1\n", encoding="utf-8")

    results = list(walk(tmp_path, _config()))
    rels = _rels(results)
    assert "kept.py" in rels
    assert "data.bin" not in rels


# ---------------------------------------------------------------------------
# Encoding fallback
# ---------------------------------------------------------------------------


def test_encoding_fallback_warns_and_yields(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bad = tmp_path / "latin1.py"
    # `\xff` is invalid as a standalone UTF-8 byte; forces UnicodeDecodeError.
    bad.write_bytes(b"x = '\xff'\n")
    (tmp_path / "ok.py").write_text("x = 1\n", encoding="utf-8")

    results = list(walk(tmp_path, _config()))
    by_rel = {r.rel_path.as_posix(): r for r in results}
    assert "latin1.py" in by_rel
    assert by_rel["latin1.py"].decode_warning is True
    # Replacement character must be present so the chunker sees real text.
    assert "�" in by_rel["latin1.py"].content
    assert "ok.py" in by_rel
    assert by_rel["ok.py"].decode_warning is False

    err = capsys.readouterr().err
    assert "latin1.py" in err
    assert "non-UTF-8" in err


# ---------------------------------------------------------------------------
# Symlinks
# ---------------------------------------------------------------------------


def test_file_symlink_is_followed(tmp_path: Path) -> None:
    if not _can_symlink(tmp_path):
        pytest.skip("symlink creation not permitted on this host")
    target = tmp_path / "real.py"
    target.write_text("x = 1\n", encoding="utf-8")
    link = tmp_path / "link.py"
    os.symlink(target, link)

    results = list(walk(tmp_path, _config()))
    rels = _rels(results)
    # Both the real file and the link are yielded — the link path, not the
    # resolved target — so a caller can dedupe by content if desired.
    assert "real.py" in rels
    assert "link.py" in rels


def test_directory_symlink_is_not_followed(tmp_path: Path) -> None:
    if not _can_symlink(tmp_path):
        pytest.skip("symlink creation not permitted on this host")
    real_dir = tmp_path / "real_dir"
    real_dir.mkdir()
    (real_dir / "inside.py").write_text("x = 1\n", encoding="utf-8")
    link_dir = tmp_path / "link_dir"
    os.symlink(real_dir, link_dir, target_is_directory=True)

    results = list(walk(tmp_path, _config()))
    rels = _rels(results)
    assert "real_dir/inside.py" in rels
    # The walker does not descend into symlinked directories.
    assert "link_dir/inside.py" not in rels


def test_broken_symlink_warns_and_skips(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    if not _can_symlink(tmp_path):
        pytest.skip("symlink creation not permitted on this host")
    missing = tmp_path / "nope.py"
    link = tmp_path / "dangling.py"
    os.symlink(missing, link)
    (tmp_path / "ok.py").write_text("x = 1\n", encoding="utf-8")

    results = list(walk(tmp_path, _config()))
    rels = _rels(results)
    assert "ok.py" in rels
    assert "dangling.py" not in rels
    err = capsys.readouterr().err
    assert "broken symlink" in err
    assert "dangling.py" in err


# ---------------------------------------------------------------------------
# Output record shape
# ---------------------------------------------------------------------------


def test_walkedfile_fields_are_populated(tmp_path: Path) -> None:
    src = tmp_path / "pkg" / "mod.py"
    src.parent.mkdir()
    # write_bytes to keep the line ending stable across platforms — the
    # walker reads raw bytes and decodes, so a `write_text` here would
    # surface as `\r\n` on Windows.
    src.write_bytes(b"x = 1\n")

    results = list(walk(tmp_path, _config()))
    assert len(results) == 1
    record = results[0]
    assert record.path == src.resolve()
    assert record.rel_path == Path("pkg") / "mod.py"
    assert record.content == "x = 1\n"
    assert record.extension == ".py"
    assert record.decode_warning is False


# ---------------------------------------------------------------------------
# Checked-in encoding fixture sanity
# ---------------------------------------------------------------------------


def test_checked_in_encoding_fixture(tmp_path: Path) -> None:
    """The checked-in `encoding/latin1.py` fixture is decode-warned.

    Mirrors the on-the-fly encoding test, but uses the suggested fixture
    layout so the fixture directory is exercised in CI and survives a tree
    refactor. Copied into ``tmp_path`` so the walker sees a clean root.
    """
    src_dir = FIXTURES / "encoding"
    if not src_dir.is_dir():
        pytest.skip("encoding fixture directory not present")

    dest = tmp_path / "encoding"
    dest.mkdir()
    for entry in src_dir.iterdir():
        if entry.is_file():
            (dest / entry.name).write_bytes(entry.read_bytes())

    results = list(walk(tmp_path, _config()))
    by_rel = {r.rel_path.as_posix(): r for r in results}
    assert "encoding/latin1.py" in by_rel
    assert by_rel["encoding/latin1.py"].decode_warning is True
