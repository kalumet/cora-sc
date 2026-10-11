"""Release replacement, startup lifecycle and preservation of existing game files."""

from io import BytesIO
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch
from zipfile import ZipFile

from services.star_citizen_starstrings import (
    ASSET_NAME, GLOBAL_PATH, RELEASE_URL, StarStringsUpdater, atomic_write, configured_game_directory, english_user_config,
)
from test_instant_command_cache import load_class


def archive(text=b"name=FullForce\nmission=Blueprint reward\n", extra=None):
    stream = BytesIO()
    with ZipFile(stream, "w") as pack:
        pack.writestr("Data/Localization/english/global.ini", text)
        pack.writestr("USER.cfg", "g_language = english")
        for name, data in extra or []:
            pack.writestr(name, data)
    return stream.getvalue()


def release(data, version=1):
    return {"id": 100, "tag_name": "latest", "name": f"SC LIVE Build {version}",
            "published_at": f"2026-10-{version:02d}T00:00:00Z", "draft": False, "prerelease": False,
            "assets": [{"id": version, "name": ASSET_NAME, "state": "uploaded", "size": len(data),
                        "updated_at": f"2026-10-{version:02d}T00:00:00Z",
                        "digest": "sha256:" + hashlib.sha256(data).hexdigest(),
                        "browser_download_url": f"https://github.com/MrKraken/StarStrings/releases/download/latest/{ASSET_NAME}"}]}


class UserConfigTests(unittest.TestCase):
    def test_add_preserves_every_existing_setting_and_crlf(self):
        content = b"-- keep this\r\nsys_maxFPS = 140\r\nr_displayInfo = 1"
        self.assertEqual(english_user_config(content), content + b"\r\ng_language = english\r\n")

    def test_change_only_language_preserve_comments_and_duplicate_overrides(self):
        content = b'g_language = "german" -- language\r\n;g_language=spanish\r\nr_displayInfo=1\r\nG_LANGUAGE= french # comment\r\n'
        self.assertEqual(english_user_config(content), b'g_language = english -- language\r\n;g_language=spanish\r\nr_displayInfo=1\r\nG_LANGUAGE= english # comment\r\n')

    def test_existing_english_setting_is_idempotent(self):
        content = b"sys_maxFPS=140\ng_language = english\n"
        self.assertEqual(english_user_config(content), content)

    def test_bom_and_windows_comment_encodings_survive(self):
        for encoding in ("utf-8-sig", "utf-16", "latin-1"):
            with self.subTest(encoding=encoding):
                content = "-- für mich\r\ng_language = german\r\n".encode(encoding)
                expected = "-- für mich\r\ng_language = english\r\n".encode(encoding)
                self.assertEqual(english_user_config(content), expected)
        content = b"\xfe\xff" + "g_language=german\r\n".encode("utf-16-be")
        self.assertEqual(english_user_config(content), b"\xfe\xff" + "g_language=english\r\n".encode("utf-16-be"))


class UpdaterTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.game = self.root / "StarCitizen/LIVE"
        self.game.mkdir(parents=True)
        self.pack = archive()
        self.release = release(self.pack)
        self.fetch = Mock(side_effect=lambda url, limit: json.dumps(self.release).encode() if url == RELEASE_URL else self.pack)
        self.report = Mock()
        self.updater = StarStringsUpdater(self.game, self.root / "state", fetch=self.fetch, report=self.report)
        self.global_file = self.game.joinpath(*GLOBAL_PATH)
        self.cfg = self.game / "user.cfg"

    def test_initial_install_sets_language_and_saves_release_marker(self):
        self.cfg.write_bytes(b"sys_maxFPS = 140\r\n")
        result = self.updater.check_and_install()
        self.assertEqual(result["status"], "installed")
        self.assertEqual(self.global_file.read_bytes(), b"name=FullForce\nmission=Blueprint reward\n")
        self.assertEqual(self.cfg.read_bytes(), b"sys_maxFPS = 140\r\ng_language = english\r\n")
        marker = json.loads(self.updater.state_path.read_text())
        self.assertEqual(marker["fingerprint"]["asset_id"], 1)
        self.assertEqual(len(list((self.root / "state/backups/LIVE").glob("user.cfg.*.bak"))), 1)

    def test_restart_checks_metadata_but_does_not_download_same_release(self):
        self.updater.check_and_install()
        self.fetch.reset_mock()
        restarted = StarStringsUpdater(self.game, self.root / "state", fetch=self.fetch)
        self.assertEqual(restarted.check_and_install()["status"], "current")
        self.fetch.assert_called_once_with(RELEASE_URL, 1024 * 1024)

    def test_mutable_latest_tag_updates_when_asset_changes(self):
        self.updater.check_and_install()
        self.pack = archive(b"mission=New rewards\n")
        self.release = release(self.pack, 2)
        self.assertEqual(self.updater.check_and_install()["status"], "updated")
        self.assertEqual(self.global_file.read_bytes(), b"mission=New rewards\n")
        self.assertEqual(json.loads(self.updater.state_path.read_text())["fingerprint"]["asset_id"], 2)
        self.assertTrue(any(p.read_bytes() == b"name=FullForce\nmission=Blueprint reward\n"
                            for p in (self.root / "state/backups/LIVE").glob("global.ini.*.bak")))

    def test_asset_modified_under_same_id_is_also_detected(self):
        self.updater.check_and_install()
        self.pack = archive(b"new=Strings\n")
        self.release = release(self.pack)
        self.assertEqual(self.updater.check_and_install()["status"], "updated")
        self.assertEqual(self.global_file.read_bytes(), b"new=Strings\n")

    def test_missing_pack_is_reinstalled_and_cfg_repaired_without_other_changes(self):
        self.updater.check_and_install()
        self.global_file.unlink()
        self.cfg.write_bytes(b"sys_maxFPS=90\ng_language=german\n")
        self.assertEqual(self.updater.check_and_install()["status"], "updated")
        self.assertEqual(self.cfg.read_bytes(), b"sys_maxFPS=90\ng_language=english\n")

    def test_config_repair_on_same_release_avoids_zip_download(self):
        self.updater.check_and_install()
        self.cfg.write_bytes(b"r_displayInfo=2\n")
        self.fetch.reset_mock()
        result = self.updater.check_and_install()
        self.assertEqual(result["status"], "current")
        self.assertTrue(result["config_updated"])
        self.fetch.assert_called_once()
        self.assertIn(b"r_displayInfo=2", self.cfg.read_bytes())

    def test_case_preservation_avoids_second_data_directory_or_user_cfg(self):
        target = self.game / "Data/Localization/English/global.ini"
        target.parent.mkdir(parents=True)
        target.write_bytes(b"old=Strings\n")
        cfg = self.game / "USER.cfg"
        cfg.write_bytes(b"sys_maxFPS=140\n")
        self.assertEqual(self.updater.check_and_install()["status"], "installed")
        self.assertFalse(self.cfg.exists())
        self.assertFalse((self.game / "data").exists())
        self.assertIn(b"g_language = english", cfg.read_bytes())
        self.assertIn(b"name=FullForce", target.read_bytes())

    def test_offline_start_keeps_previous_pack_config_and_marker(self):
        self.updater.check_and_install()
        before = [p.read_bytes() for p in (self.global_file, self.cfg, self.updater.state_path)]
        self.fetch.side_effect = TimeoutError("offline")
        self.assertEqual(self.updater.check_and_install()["status"], "failed")
        self.assertEqual(before, [p.read_bytes() for p in (self.global_file, self.cfg, self.updater.state_path)])

    def test_bad_digest_incomplete_or_invalid_zip_never_replaces_files(self):
        self.updater.check_and_install()
        before = [p.read_bytes() for p in (self.global_file, self.cfg, self.updater.state_path)]
        valid_pack, original_release = self.pack, self.release
        for problem in ("digest", "size", "archive"):
            with self.subTest(problem=problem):
                self.pack = valid_pack if problem != "archive" else b"not a ZIP file"
                self.release = release(self.pack, 2)
                if problem == "digest":
                    self.release["assets"][0]["digest"] = "sha256:wrong"
                if problem == "size":
                    self.release["assets"][0]["size"] += 1
                self.assertEqual(self.updater.check_and_install()["status"], "failed")
                self.assertEqual(before, [p.read_bytes() for p in (self.global_file, self.cfg, self.updater.state_path)])

    def test_no_arbitrary_zip_paths_are_written(self):
        self.pack = archive(extra=[("../../outside.txt", b"bad"), ("evil.cfg", "destroy all settings")])
        self.release = release(self.pack)
        self.assertEqual(self.updater.check_and_install()["status"], "installed")
        self.assertFalse((self.root / "outside.txt").exists())
        self.assertEqual(self.cfg.read_bytes(), b"g_language = english\n")

    def test_rollback_when_config_write_fails_keeps_previous_pack(self):
        self.updater.check_and_install()
        before_global = self.global_file.read_bytes()
        before_marker = self.updater.state_path.read_bytes()
        self.cfg.write_bytes(b"r_displayInfo=2\n")
        self.pack = archive(b"new=Strings\n")
        self.release = release(self.pack, 2)
        def write(path, content):
            if path == self.cfg:
                raise PermissionError("config is read-only")
            atomic_write(path, content)
        with patch("services.star_citizen_starstrings.atomic_write", side_effect=write):
            self.assertEqual(self.updater.check_and_install()["status"], "failed")
        self.assertEqual(self.global_file.read_bytes(), before_global)
        self.assertEqual(self.cfg.read_bytes(), b"r_displayInfo=2\n")
        self.assertEqual(self.updater.state_path.read_bytes(), before_marker)

    def test_unknown_asset_host_is_rejected_before_download(self):
        self.release["assets"][0]["browser_download_url"] = "https://example.com/malicious.zip"
        self.assertEqual(self.updater.check_and_install()["status"], "failed")
        self.fetch.assert_called_once()
        self.assertFalse(self.global_file.exists())

    def test_missing_install_and_non_live_channels_do_not_download_or_create_game_directory(self):
        for directory in (self.root / "missing/LIVE", self.root / "PTU"):
            updater = StarStringsUpdater(directory, self.root / "state", fetch=self.fetch)
            self.assertEqual(updater.check_and_install()["status"], "skipped")
            self.fetch.assert_not_called()
            self.assertFalse(directory.exists())

    def test_cancelled_download_does_not_install_files(self):
        def fetch(url, limit):
            if url != RELEASE_URL:
                self.updater.close()
            return json.dumps(self.release).encode() if url == RELEASE_URL else self.pack
        self.updater.fetch = fetch
        self.assertEqual(self.updater.check_and_install()["status"], "cancelled")
        self.assertFalse(self.global_file.exists())
        self.assertFalse(self.cfg.exists())

    def test_background_start_and_close(self):
        self.updater.start()
        self.updater._thread.join(timeout=2)
        self.assertFalse(self.updater._thread.is_alive())
        self.assertEqual(self.updater.last_result["status"], "installed")
        self.updater.close()


class ManagerTests(unittest.TestCase):
    def test_configured_install_directory_works_without_game_log_module(self):
        self.assertEqual(configured_game_directory({"sc-keybind-mappings": {
            "sc_installation_dir": "/games/StarCitizen", "sc_active_channel": "LIVE"}}), Path("/games/StarCitizen/LIVE"))
        with patch("services.star_citizen_starstrings.Path.is_dir", return_value=True):
            self.assertEqual(configured_game_directory({"sc-keybind-mappings": {
                "sc_installation_dir": "D:\\Games\\StarCitizen", "sc_active_channel": "PTU"}}), Path("/mnt/d/Games/StarCitizen/PTU"))

    def test_new_manager_is_enabled_by_default_and_can_be_disabled(self):
        import ast
        tree = ast.parse(Path("wingmen/star_citizen_services/functions/starstrings_services/starstrings_manager.py").read_text())
        cls = next(node for node in tree.body if isinstance(node, ast.ClassDef))
        default = next(ast.literal_eval(node.value) for node in cls.body if isinstance(node, ast.Assign)
                       and any(isinstance(target, ast.Name) and target.id == "DEFAULT_ENABLED" for target in node.targets))
        owner_cls = load_class("wingmen/star_citizen_services/function_manager.py", "StarCitizensAiFunctionsManager",
                               {"_resolve_feature_enabled"}, {})
        owner = owner_cls()
        owner.manager_classes = {"StarStringsManager": type("DefaultManager", (), {"DEFAULT_ENABLED": default})}
        owner.config = {"features": {}}
        self.assertTrue(owner._resolve_feature_enabled("StarStringsManager"))
        owner.config = {"features": {"StarStringsManager": {"enabled": False}}}
        self.assertFalse(owner._resolve_feature_enabled("StarStringsManager"))

    def test_manager_activation_and_app_close_use_updater_lifecycle(self):
        cls = load_class("wingmen/star_citizen_services/functions/starstrings_services/starstrings_manager.py",
            "StarStringsManager", {"on_manager_enabled", "on_manager_disabled", "close_speech_sessions",
                                  "register_functions", "get_function_tools", "get_function_prompt"}, {})
        manager = cls()
        manager.updater = Mock()
        manager.on_manager_enabled("config")
        manager.updater.start.assert_called_once()
        manager.on_manager_disabled()
        manager.close_speech_sessions()
        self.assertEqual(manager.updater.close.call_count, 2)
        registry = {}
        manager.register_functions(registry)
        self.assertEqual(registry, {})
        self.assertEqual(manager.get_function_tools(), [])
        self.assertEqual(manager.get_function_prompt(), "")


if __name__ == "__main__":
    unittest.main()
