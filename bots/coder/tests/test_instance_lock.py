"""Tests for coder.instance_lock — single-instance startup guard."""

from __future__ import annotations

import os

import pytest
from coder.instance_lock import (
    AlreadyRunningError,
    acquire_instance_lock,
    release_instance_lock,
)


def test_acquire_returns_fd_and_writes_pid(tmp_path):
    lock = tmp_path / "coder.lock"
    fd = acquire_instance_lock(lock)
    try:
        assert isinstance(fd, int)
        assert lock.read_text().strip() == str(os.getpid())
    finally:
        release_instance_lock(fd)


def test_second_acquire_raises_already_running(tmp_path):
    lock = tmp_path / "coder.lock"
    fd = acquire_instance_lock(lock)
    try:
        with pytest.raises(AlreadyRunningError):
            acquire_instance_lock(lock)
    finally:
        release_instance_lock(fd)


def test_release_allows_reacquire(tmp_path):
    lock = tmp_path / "coder.lock"
    fd = acquire_instance_lock(lock)
    release_instance_lock(fd)
    # Should be able to take it again after release.
    fd2 = acquire_instance_lock(lock)
    release_instance_lock(fd2)


def test_creates_parent_directory(tmp_path):
    lock = tmp_path / "nested" / "dir" / "coder.lock"
    fd = acquire_instance_lock(lock)
    try:
        assert lock.exists()
    finally:
        release_instance_lock(fd)


def test_already_running_error_carries_pid_and_path(tmp_path):
    lock = tmp_path / "coder.lock"
    fd = acquire_instance_lock(lock)
    try:
        with pytest.raises(AlreadyRunningError) as exc:
            acquire_instance_lock(lock)
        # The holder's PID (this process) and the lock path should be reported.
        assert str(os.getpid()) in str(exc.value)
        assert str(lock) in str(exc.value)
    finally:
        release_instance_lock(fd)
