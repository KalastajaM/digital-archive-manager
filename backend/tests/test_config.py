import json
from pathlib import Path

from dam.config import DEFAULTS_DIR, AppPaths, load_settings


def test_appaths_uses_env(tmp_path, monkeypatch):
    monkeypatch.setenv("DAM_DATA_DIR", str(tmp_path))
    assert AppPaths().db_path == tmp_path / "dam.sqlite"


def test_ensure_seeds_defaults(tmp_path):
    AppPaths(tmp_path).ensure()
    assert (tmp_path / "config" / "settings.yaml").exists()
    assert (tmp_path / "config" / "rules" / "00-examples.yaml").exists()


def test_load_settings_defaults(tmp_path):
    paths = AppPaths(tmp_path)
    paths.ensure()
    (paths.config_dir / "settings.yaml").write_text("archive_root: ~/x\n", encoding="utf-8")
    s = load_settings(paths)
    assert s.archive_root == Path.home() / "x"
    assert s.special_folders.quarantine == "##. To Delete"
    assert s.protected_paths == ["##. Important"]


def test_ensure_does_not_overwrite_user_config(tmp_path):
    paths = AppPaths(tmp_path)
    paths.ensure()
    settings_file = paths.config_dir / "settings.yaml"
    settings_file.write_text("archive_root: /custom\n", encoding="utf-8")
    paths.ensure()
    assert settings_file.read_text(encoding="utf-8") == "archive_root: /custom\n"


def test_ensure_seeds_trays(tmp_path):
    AppPaths(tmp_path).ensure()
    trays = tmp_path / "config" / "trays"
    assert sorted(p.name for p in trays.iterdir()) == [
        "10-to-pay.yaml",
        "20-to-action.yaml",
        "30-to-read.yaml",
        "40-follow-up.yaml",
        "50-renew.yaml",
    ]
    # a new install has been offered every default tray
    assert "40-follow-up.yaml" in json.loads(
        (tmp_path / "tray-defaults-seeded.json").read_text(encoding="utf-8")
    )


def test_ensure_adds_trays_to_existing_config_without_touching_it(tmp_path):
    paths = AppPaths(tmp_path)
    paths.config_dir.mkdir(parents=True)
    (paths.config_dir / "settings.yaml").write_text("archive_root: /custom\n", encoding="utf-8")
    paths.ensure()
    assert (paths.config_dir / "trays" / "10-to-pay.yaml").exists()
    assert not (paths.config_dir / "rules").exists()
    assert (paths.config_dir / "settings.yaml").read_text(
        encoding="utf-8"
    ) == "archive_root: /custom\n"
    # a tray file the user removed stays removed
    (paths.config_dir / "trays" / "30-to-read.yaml").unlink()
    paths.ensure()
    assert not (paths.config_dir / "trays" / "30-to-read.yaml").exists()


def test_ensure_never_overwrites_files_when_settings_missing(tmp_path):
    paths = AppPaths(tmp_path)
    paths.ensure()
    tray = paths.config_dir / "trays" / "10-to-pay.yaml"
    rule = paths.config_dir / "rules" / "00-examples.yaml"
    tray.write_text("id: to-pay\nname: Bills\norder: 1\n", encoding="utf-8")
    rule.write_text("- id: mine\n", encoding="utf-8")
    (paths.config_dir / "trays" / "20-to-action.yaml").unlink()
    (paths.config_dir / "settings.yaml").unlink()
    paths.ensure()
    assert tray.read_text(encoding="utf-8") == "id: to-pay\nname: Bills\norder: 1\n"
    assert rule.read_text(encoding="utf-8") == "- id: mine\n"
    assert (paths.config_dir / "settings.yaml").exists()
    assert (paths.config_dir / "trays" / "20-to-action.yaml").exists()


def test_ensure_keeps_a_dangling_symlink(tmp_path):
    paths = AppPaths(tmp_path)
    (paths.config_dir / "trays").mkdir(parents=True)
    link = paths.config_dir / "trays" / "10-to-pay.yaml"
    link.symlink_to(tmp_path / "nowhere.yaml")
    paths.ensure()
    assert link.is_symlink() and not (tmp_path / "nowhere.yaml").exists()


def test_ensure_offers_a_new_default_tray_once_to_an_existing_install(tmp_path):
    paths = AppPaths(tmp_path)
    trays = paths.config_dir / "trays"
    trays.mkdir(parents=True)
    (paths.config_dir / "settings.yaml").write_text("archive_root: /custom\n", encoding="utf-8")
    (trays / "10-to-pay.yaml").write_text(
        (DEFAULTS_DIR / "trays" / "10-to-pay.yaml").read_text(encoding="utf-8"), encoding="utf-8"
    )  # to-action and to-read were removed on purpose
    paths.ensure()
    assert (trays / "40-follow-up.yaml").exists()
    assert (trays / "50-renew.yaml").exists()
    assert not (trays / "20-to-action.yaml").exists()
    assert not (trays / "30-to-read.yaml").exists()
    # removed again: it is not offered a second time
    (trays / "40-follow-up.yaml").unlink()
    (trays / "50-renew.yaml").unlink()
    paths.ensure()
    assert not (trays / "40-follow-up.yaml").exists()
    assert not (trays / "50-renew.yaml").exists()


def test_ensure_skips_a_default_tray_whose_id_the_user_already_has(tmp_path):
    paths = AppPaths(tmp_path)
    trays = paths.config_dir / "trays"
    trays.mkdir(parents=True)
    (paths.config_dir / "settings.yaml").write_text("archive_root: /custom\n", encoding="utf-8")
    (trays / "my-waiting.yaml").write_text(
        "id: follow-up\nname: Waiting\norder: 9\n", encoding="utf-8"
    )
    paths.ensure()
    assert not (trays / "40-follow-up.yaml").exists()


def test_extra_folders_round_trip_and_expand_user(tmp_path):
    paths = AppPaths(tmp_path)
    paths.ensure()
    (paths.config_dir / "settings.yaml").write_text(
        "archive_root: ~/x\nextra_folders:\n"
        "  - {label: Old years, path: ~/disk/old}\n"
        "  - {label: Spare, path: /spare, attached: false}\n",
        encoding="utf-8",
    )
    s = load_settings(paths)
    assert [(f.label, f.path, f.attached) for f in s.extra_folders] == [
        ("Old years", Path.home() / "disk" / "old", True),
        ("Spare", Path("/spare"), False),
    ]
    assert load_settings(paths).extra_folders == s.extra_folders
