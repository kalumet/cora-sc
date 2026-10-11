"""Install the StarStrings LIVE release and check for updates at Cora startup."""

from datetime import datetime, timezone
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import re
import tempfile
import threading
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from zipfile import ZipFile


REPOSITORY = "MrKraken/StarStrings"
RELEASE_URL = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
ASSET_NAME = "StarStrings-LIVE.zip"
GLOBAL_PATH = ("data", "Localization", "english", "global.ini")
MAX_DOWNLOAD = 16 * 1024 * 1024
MAX_GLOBAL = 32 * 1024 * 1024


def configured_game_directory(config):
    options = config.get("sc-keybind-mappings", {})
    root = str(options.get("sc_installation_dir", "C:/Program Files/Roberts Space Industries/StarCitizen"))
    drive = re.match(r"^([A-Za-z]):[/\\](.*)", root)
    if drive and Path("/mnt").is_dir():
        root = f"/mnt/{drive[1].lower()}/{drive[2].replace(chr(92), '/')}"
    return Path(root) / options.get("sc_active_channel", "LIVE")


def english_user_config(content):
    """Preserve existing settings, comments, encoding and line endings."""
    prefix = b""
    if content.startswith((b"\xff\xfe", b"\xfe\xff")):
        prefix, content = content[:2], content[2:]
        encoding = "utf-16-le" if prefix == b"\xff\xfe" else "utf-16-be"
    elif content.startswith(b"\xef\xbb\xbf"):
        encoding = "utf-8-sig"
    else:
        try:
            content.decode("utf-8")
            encoding = "utf-8"
        except UnicodeDecodeError:
            encoding = "latin-1"
    text = content.decode(encoding)
    pattern = re.compile(r"^([ \t]*g_language[ \t]*=[ \t]*)([^\r\n]*)(\r?\n|\r|$)", re.I)
    found, lines = False, []
    for line in text.splitlines(keepends=True):
        match = pattern.fullmatch(line)
        if match:
            found = True
            suffix = re.search(r"[ \t]*(?:--|//|#|;).*|[ \t]*$", match[2])[0]
            line = match[1] + "english" + suffix + match[3]
        lines.append(line)
    if not found:
        newline = "\r\n" if "\r\n" in text else "\n"
        if text and not text.endswith(("\n", "\r")):
            lines.append(newline)
        lines.append("g_language = english" + newline)
    return prefix + "".join(lines).encode(encoding)


def atomic_write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    staging = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".cora-starstrings-", delete=False) as stream:
            staging = Path(stream.name)
            stream.write(content)
        os.replace(staging, path)
    finally:
        if staging and staging.exists():
            staging.unlink()


class StarStringsUpdater:
    def __init__(self, game_dir, state_dir, *, fetch=None, report=None, timeout=15):
        self.game_dir, self.state_dir = Path(game_dir), Path(state_dir)
        self.state_path = self.state_dir / f"installed_{self.game_dir.name}.json"
        self.fetch = fetch or self._fetch
        self.report = report or (lambda result: None)
        self.timeout = max(1, min(float(timeout), 30))
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._thread = None
        self.last_result = None

    def _fetch(self, url, limit):
        request = Request(url, headers={"User-Agent": "Cora-StarStrings-Updater",
                                       "Accept": "application/vnd.github+json" if url == RELEASE_URL else "application/octet-stream"})
        with urlopen(request, timeout=self.timeout) as response:
            data = response.read(limit + 1)
        if len(data) > limit:
            raise ValueError("StarStrings download exceeds size limit")
        return data

    def _check_cancelled(self):
        if self._stop.is_set():
            raise InterruptedError("StarStrings update cancelled")

    def _load_state(self):
        try:
            state = json.loads(self.state_path.read_text(encoding="utf-8"))
            return state if isinstance(state, dict) else {}
        except (OSError, ValueError):
            return {}

    def _backup(self, path, content):
        if content is None:
            return
        digest = hashlib.sha256(content).hexdigest()
        backup = self.state_dir / "backups" / self.game_dir.name / f"{path.name}.{digest}.bak"
        if not backup.exists():
            atomic_write(backup, content)

    @staticmethod
    def _global_bytes(archive):
        with ZipFile(BytesIO(archive)) as pack:
            entries = [entry for entry in pack.infolist()
                       if entry.filename.replace("\\", "/").casefold() == "/".join(GLOBAL_PATH).casefold()]
            if len(entries) != 1 or not 0 < entries[0].file_size <= MAX_GLOBAL:
                raise ValueError("StarStrings archive must contain one valid english/global.ini")
            # Read only the language file; never extract arbitrary archive paths.
            data = pack.read(entries[0])
        text = data.decode("utf-8-sig")
        if "\x00" in text or not any("=" in line for line in text.splitlines()):
            raise ValueError("Invalid StarStrings global.ini")
        return data

    def check_and_install(self):
        """One bounded check; failures leave the existing installation usable."""
        with self._lock:
            try:
                result = self._install()
            except InterruptedError:
                result = {"status": "cancelled"}
            except Exception as error:
                result = {"status": "failed", "error": f"{type(error).__name__}: {error}"}
            self.last_result = result
            self.report(result)
            return result

    def _install(self):
        self._check_cancelled()
        if self.game_dir.name.casefold() != "live":
            return {"status": "skipped", "reason": "StarStrings releases target LIVE", "channel": self.game_dir.name}
        if not self.game_dir.is_dir():
            return {"status": "skipped", "reason": "Star Citizen LIVE directory not found", "path": str(self.game_dir)}
        metadata = self.fetch(RELEASE_URL, 1024 * 1024)
        self._check_cancelled()
        release = json.loads(metadata)
        if not isinstance(release, dict) or release.get("draft") or release.get("prerelease"):
            raise ValueError("No stable StarStrings release")
        assets = [a for a in release.get("assets", []) if isinstance(a, dict)
                  and a.get("name") == ASSET_NAME and a.get("state") == "uploaded"]
        if len(assets) != 1:
            raise ValueError(f"Release must contain exactly one {ASSET_NAME}")
        asset = assets[0]
        url = asset.get("browser_download_url", "")
        parsed = urlparse(url)
        if (parsed.scheme != "https" or parsed.netloc != "github.com"
                or not parsed.path.startswith(f"/{REPOSITORY}/releases/download/")):
            raise ValueError("Unexpected StarStrings download URL")
        if not isinstance(asset.get("size"), int) or not 0 < asset["size"] <= MAX_DOWNLOAD:
            raise ValueError("Invalid StarStrings asset size")
        fingerprint = {"release_id": release.get("id"), "name": release.get("name"),
                       "tag": release.get("tag_name"), "published_at": release.get("published_at"),
                       "asset_id": asset.get("id"), "asset_updated_at": asset.get("updated_at"),
                       "asset_size": asset["size"], "asset_digest": asset.get("digest")}
        previous = self._load_state()
        global_file = self._case_path(self.game_dir, GLOBAL_PATH)
        cfg_file = self._case_path(self.game_dir, ("user.cfg",))
        before_cfg = cfg_file.read_bytes() if cfg_file.exists() else None
        after_cfg = english_user_config(before_cfg or b"")
        current = previous.get("fingerprint") == fingerprint and global_file.is_file()
        if current:
            self._check_cancelled()
            if after_cfg != before_cfg:
                self._backup(cfg_file, before_cfg)
                atomic_write(cfg_file, after_cfg)
            return {"status": "current", "release": fingerprint["name"], "config_updated": after_cfg != before_cfg}
        archive = self.fetch(url, MAX_DOWNLOAD)
        self._check_cancelled()
        if len(archive) != asset["size"]:
            raise ValueError("Incomplete StarStrings download")
        if asset.get("digest") and asset["digest"] != "sha256:" + hashlib.sha256(archive).hexdigest():
            raise ValueError("StarStrings SHA-256 mismatch")
        after_global = self._global_bytes(archive)
        before_global = global_file.read_bytes() if global_file.exists() else None
        self._backup(global_file, before_global)
        self._backup(cfg_file, before_cfg)
        saved = {"repository": REPOSITORY, "fingerprint": fingerprint,
                 "installed_at": datetime.now(timezone.utc).isoformat(),
                 "global_sha256": hashlib.sha256(after_global).hexdigest()}
        changed = []
        try:
            for path, before, after in ((global_file, before_global, after_global), (cfg_file, before_cfg, after_cfg)):
                self._check_cancelled()
                if before != after:
                    atomic_write(path, after)
                    changed.append((path, before))
            self._check_cancelled()
            atomic_write(self.state_path, json.dumps(saved, ensure_ascii=False, indent=2).encode("utf-8"))
        except Exception:
            for path, before in reversed(changed):
                if before is None:
                    path.unlink(missing_ok=True)
                else:
                    atomic_write(path, before)
            raise
        return {"status": "updated" if previous else "installed", "release": fingerprint["name"],
                "path": str(global_file)}

    @staticmethod
    def _case_path(root, parts):
        # Preserve existing Data/USER.cfg casing, including when testing on Linux.
        path = root
        for name in parts:
            matches = [p for p in path.iterdir() if p.name.casefold() == name.casefold()] if path.is_dir() else []
            if len(matches) > 1:
                raise ValueError(f"Ambiguous installation path: {path / name}")
            path = matches[0] if matches else path / name
        return path

    def start(self):
        self._stop.clear()
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self.check_and_install, name="SC-StarStrings", daemon=True)
        self._thread.start()

    def close(self):
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1)
