"""atomic_cache_write: readers never see a half-written cache file.

Parallel runs are separate processes sharing one cache directory, so the old
``open(cache_file, "w")`` could hand a reader a truncated file, and a fixed temp
name could be clobbered by a second writer.
"""

import os

import pytest

from tradingagents.dataflows.utils import atomic_cache_write


@pytest.mark.unit
def test_replaces_the_target_only_after_the_write_completes(tmp_path):
    target = tmp_path / "cache.json"
    target.write_text("old", encoding="utf-8")

    with atomic_cache_write(str(target)) as tmp:
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write("new")
        assert target.read_text(encoding="utf-8") == "old"  # not yet visible

    assert target.read_text(encoding="utf-8") == "new"
    assert list(tmp_path.glob("*.tmp")) == []


@pytest.mark.unit
def test_leaves_the_previous_file_intact_on_failure(tmp_path):
    target = tmp_path / "cache.json"
    target.write_text("old", encoding="utf-8")

    with pytest.raises(RuntimeError), atomic_cache_write(str(target)) as tmp:
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write("partial")
        raise RuntimeError("vendor blew up mid-write")

    assert target.read_text(encoding="utf-8") == "old"
    assert list(tmp_path.glob("*.tmp")) == []


@pytest.mark.unit
def test_temp_name_is_unique_per_writer(tmp_path):
    """Two concurrent writers must not stage into the same temp path."""
    target = str(tmp_path / "cache.json")
    with atomic_cache_write(target) as first:
        with atomic_cache_write(target) as second:
            assert first != second
            assert str(os.getpid()) in first
            open(second, "w").close()
        open(first, "w").close()

    assert list(tmp_path.glob("*.tmp")) == []
