"""Tests for mto install-shims / uninstall-shims."""

from pathlib import Path
import stat

from machine_shell_token_optimizer.shims import (
    DEFAULT_COMMANDS,
    install_shims,
    uninstall_shims,
    get_shims_env,
)


def test_install_creates_executable_shims(tmp_path):
    created = install_shims(commands=["git", "docker"], shim_dir=tmp_path)
    assert len(created) == 2
    for p in created:
        assert p.exists()
        assert p.stat().st_mode & stat.S_IXUSR
        content = p.read_text()
        assert "mto proxy" in content
        assert "_mto_find_real" in content


def test_shim_skips_own_dir_on_path(tmp_path):
    install_shims(commands=["git"], shim_dir=tmp_path)
    content = (tmp_path / "git").read_text()
    assert 'shim_dir="$(cd "$(dirname "$0")" && pwd)"' in content
    assert '"$dir" == "$shim_dir"' in content


def test_shim_passthrough_write_commands(tmp_path):
    install_shims(commands=["git"], shim_dir=tmp_path)
    content = (tmp_path / "git").read_text()
    assert "push|pull|fetch|merge|rebase" in content


def test_shim_requires_active_env(tmp_path):
    """Shims only activate when MTO_SHIMS_ACTIVE=1."""
    install_shims(commands=["ls"], shim_dir=tmp_path)
    content = (tmp_path / "ls").read_text()
    assert "MTO_SHIMS_ACTIVE" in content
    # Default is to pass through (not compress)
    assert 'MTO_SHIMS_ACTIVE:-0}" != "1"' in content


def test_shim_respects_disabled_env(tmp_path):
    install_shims(commands=["ls"], shim_dir=tmp_path)
    content = (tmp_path / "ls").read_text()
    assert "MTO_DISABLED" in content


def test_uninstall_removes_shims(tmp_path):
    install_shims(commands=["git", "cargo"], shim_dir=tmp_path)
    assert len(list(tmp_path.iterdir())) == 2
    removed = uninstall_shims(shim_dir=tmp_path)
    assert len(removed) == 2
    assert not tmp_path.exists()


def test_uninstall_empty_dir(tmp_path):
    removed = uninstall_shims(shim_dir=tmp_path / "nonexistent")
    assert removed == []


def test_install_default_commands(tmp_path):
    created = install_shims(shim_dir=tmp_path)
    assert len(created) == len(DEFAULT_COMMANDS)


def test_get_shims_env(tmp_path):
    result = get_shims_env(tmp_path)
    assert str(tmp_path) in result
    assert "export PATH=" in result
    assert "MTO_SHIMS_ACTIVE=1" in result


def test_no_rc_file_modification(tmp_path):
    """install-shims must NEVER touch shell rc files."""
    rc = tmp_path / ".zshrc"
    rc.write_text("# user config\n")
    install_shims(commands=["git"], shim_dir=tmp_path / "shims")
    assert rc.read_text() == "# user config\n"


def test_cli_install_shims(tmp_path):
    from machine_shell_token_optimizer.cli import main
    rc = main(["install-shims", "--dir", str(tmp_path)])
    assert rc == 0
    assert (tmp_path / "git").exists()


def test_cli_uninstall_shims(tmp_path):
    from machine_shell_token_optimizer.cli import main
    main(["install-shims", "--dir", str(tmp_path)])
    rc = main(["uninstall-shims", "--dir", str(tmp_path)])
    assert rc == 0


def test_cli_shims_env(tmp_path, capsys):
    from machine_shell_token_optimizer.cli import main
    rc = main(["shims-env", "--dir", str(tmp_path)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "MTO_SHIMS_ACTIVE=1" in out
    assert str(tmp_path) in out
