"""repo-ops/script/deploy runs against a throwaway repo with a fake `uv` shim.

No real `uv tool install` ever runs: the shim records each invocation and
emulates only the subcommands the script calls.
"""

import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="POSIX sh script")

SCRIPT_SRC = Path(__file__).resolve().parent.parent / "repo-ops" / "script" / "deploy"

UV_SHIM = """#!/bin/sh
printf '%s\\n' "$*" >> "$FAKE_UV_LOG"
case "$*" in
    "tool dir --bin") printf '%s\\n' "$FAKE_BIN_DIR" ;;
    "tool dir") printf '%s\\n' "$FAKE_TOOL_DIR" ;;
    "tool install --force --reinstall "*)
        for last in "$@"; do :; done
        url="${FAKE_INSTALL_URL:-file://$last}"
        printf '{"url": "%s", "dir_info": {%s}}' "$url" "${FAKE_DIR_INFO:-}" \\
            > "$FAKE_SITE_DIR/claude_swap-0.0.dist-info/direct_url.json"
        ;;
    *) echo "unexpected uv call: $*" >&2; exit 99 ;;
esac
"""

CSWAP_SHIM = """#!/bin/sh
printf 'cswap %s\\n' "$*" >> "$FAKE_UV_LOG"
exit "${FAKE_CSWAP_RC:-0}"
"""

TOOL_PYTHON_SHIM = """#!/bin/sh
PYTHONPATH="$FAKE_SITE_DIR" exec python3 "$@"
"""


def _write_exec(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


class Env:
    def __init__(self, tmp_path: Path):
        self.root = tmp_path / "repo"
        self.shim_dir = tmp_path / "shim"
        self.bin_dir = tmp_path / "uvbin"
        self.tool_dir = tmp_path / "uvtools"
        self.site_dir = tmp_path / "site"
        self.log = tmp_path / "uv.log"
        self.log.write_text("")
        self.git_env = {
            **os.environ,
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_CONFIG_SYSTEM": "/dev/null",
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@example.com",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@example.com",
        }

        _write_exec(self.shim_dir / "uv", UV_SHIM)
        _write_exec(self.bin_dir / "cswap", CSWAP_SHIM)
        _write_exec(self.tool_dir / "claude-swap" / "bin" / "python", TOOL_PYTHON_SHIM)
        dist = self.site_dir / "claude_swap-0.0.dist-info"
        dist.mkdir(parents=True)
        (dist / "METADATA").write_text("Metadata-Version: 2.1\nName: claude-swap\nVersion: 0.0\n")

        self.root.mkdir()
        self.git("init", "-q", "-b", "main")
        script = self.root / "repo-ops" / "script" / "deploy"
        script.parent.mkdir(parents=True)
        shutil.copy2(SCRIPT_SRC, script)
        (self.root / "tracked.txt").write_text("one\n")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "init")
        self.head = self.git("rev-parse", "HEAD").strip()
        self.resolved_root = self.root.resolve()

    def git(self, *args: str) -> str:
        return subprocess.run(
            ["git", "-C", str(self.root), *args],
            env=self.git_env, check=True, capture_output=True, text=True,
        ).stdout

    def run(self, *, drop=(), cwd=None, extra=None, **overrides):
        env = {
            **self.git_env,
            "PATH": f"{self.shim_dir}{os.pathsep}{os.environ['PATH']}",
            "FAKE_UV_LOG": str(self.log),
            "FAKE_BIN_DIR": str(self.bin_dir),
            "FAKE_TOOL_DIR": str(self.tool_dir),
            "FAKE_SITE_DIR": str(self.site_dir),
            "REPO_OPS_TARGET_SHA": self.head,
            "REPO_OPS_TARGET_BASE": "main",
            "REPO_OPS_REPO_ROOT": str(self.resolved_root),
        }
        env.update(overrides)
        env.update(extra or {})
        for key in drop:
            env.pop(key, None)
        return subprocess.run(
            [str(self.root / "repo-ops" / "script" / "deploy")],
            cwd=cwd or self.resolved_root, env=env,
            capture_output=True, text=True, timeout=60,
        )

    @property
    def calls(self) -> list[str]:
        return self.log.read_text().splitlines()

    @property
    def installs(self) -> list[str]:
        return [c for c in self.calls if c.startswith("tool install")]


@pytest.fixture
def env(tmp_path):
    return Env(tmp_path)


def test_script_is_executable_and_names_lock_literal():
    assert os.access(SCRIPT_SRC, os.X_OK)
    assert b".worktrees/.repo-ops-deploy.lock" in SCRIPT_SRC.read_bytes()


def test_success_installs_non_editable_and_reads_back(env):
    result = env.run()

    assert result.returncode == 0, result.stderr
    assert result.stdout == (
        f"repo-ops deploy ok: base=main target={env.head}\n"
    )
    assert env.installs == [f"tool install --force --reinstall {env.resolved_root}"]
    assert "cswap session --help" in env.calls
    assert (env.root / ".worktrees" / ".repo-ops-deploy.lock").exists()


@pytest.mark.parametrize(
    "name", ["REPO_OPS_TARGET_SHA", "REPO_OPS_TARGET_BASE", "REPO_OPS_REPO_ROOT"]
)
def test_missing_required_env_fails(env, name):
    result = env.run(drop=(name,))

    assert result.returncode != 0
    assert name in result.stderr
    assert env.installs == []


@pytest.mark.parametrize("sha", ["ABCDEF" + "0" * 34, "abc123", "g" * 40])
def test_malformed_target_sha_fails(env, sha):
    result = env.run(REPO_OPS_TARGET_SHA=sha)

    assert result.returncode != 0
    assert env.installs == []


def test_cwd_differs_from_repo_root_fails(env, tmp_path):
    result = env.run(cwd=tmp_path)

    assert result.returncode != 0
    assert "cwd must equal" in result.stderr
    assert env.installs == []


def test_start_head_differs_from_target_fails(env):
    result = env.run(REPO_OPS_TARGET_SHA="0" * 40)

    assert result.returncode != 0
    assert "start HEAD" in result.stderr
    assert env.installs == []


def test_dirty_tracked_tree_fails(env):
    (env.root / "tracked.txt").write_text("changed\n")

    result = env.run()

    assert result.returncode != 0
    assert "dirty" in result.stderr
    assert env.installs == []


def test_untracked_file_does_not_block_deploy(env):
    (env.root / "scratch.txt").write_text("x\n")

    result = env.run()

    assert result.returncode == 0, result.stderr
    assert len(env.installs) == 1


def test_installed_cswap_help_failure_fails(env):
    result = env.run(FAKE_CSWAP_RC="1")

    assert result.returncode != 0
    assert "session --help" in result.stderr
    assert "ok:" not in result.stdout


def test_install_source_not_this_checkout_fails(env, tmp_path):
    result = env.run(FAKE_INSTALL_URL=f"file://{tmp_path / 'elsewhere'}")

    assert result.returncode != 0
    assert "install source" in result.stderr
    assert "ok:" not in result.stdout


def test_editable_install_fails(env):
    result = env.run(FAKE_DIR_INFO='"editable": true')

    assert result.returncode != 0
    assert "install source" in result.stderr
