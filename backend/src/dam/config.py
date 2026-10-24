"""Application settings and data-directory paths."""

import json
import os
import re
import shutil
from pathlib import Path
from typing import Literal

import yaml
from platformdirs import user_data_dir
from pydantic import BaseModel, Field, field_validator

DEFAULTS_DIR = Path(__file__).parents[3] / "defaults"


# macOS: ~/Library/Application Support/DigitalArchiveManager; Windows: %LOCALAPPDATA%;
# Linux: $XDG_DATA_HOME or ~/.local/share
def default_data_dir() -> Path:
    """The platform's per-user app data folder (on macOS ~/Library/Application Support/…)."""
    return Path(user_data_dir("DigitalArchiveManager", appauthor=False))


DEFAULT_DATA_DIR = default_data_dir()


class SpecialFolders(BaseModel):
    inbox: str = "##. Organize"
    ongoing: str = "##. Ongoing"
    important: str = "##. Important"
    quarantine: str = "##. To Delete"


# one plain ASCII address: no display name, list, angle brackets or whitespace
_ADDRESS = re.compile(
    r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)+",
    re.ASCII,
)


class EmailSettings(BaseModel):
    """E-mail to self: one message per run, From = To = ``to``. The password is in the
    macOS Keychain (``dam remind --set-email-password``), never in this file.

    The login always goes over TLS: ``smtp_port: 465`` means implicit TLS, any other
    port uses STARTTLS (``starttls: false`` there means nothing is sent)."""

    to: str
    smtp_host: str = Field(min_length=1)
    smtp_port: int = Field(default=587, ge=1, le=65535)
    smtp_user: str = Field(min_length=1)
    starttls: bool = True

    @field_validator("to")
    @classmethod
    def _one_address(cls, value: str) -> str:
        if not _ADDRESS.fullmatch(value):
            raise ValueError("expected one e-mail address like me@example.org")
        return value

    @field_validator("smtp_host", "smtp_user")
    @classmethod
    def _one_line(cls, value: str) -> str:
        # these go into SMTP commands: no CR/LF or other control characters
        if not value.isprintable() or value != value.strip():
            raise ValueError("must be printable text on one line")
        return value


class RemindersSettings(BaseModel):
    hour: int = Field(default=8, ge=0, le=23)  # local time reminders fire on their day
    mac: bool = True
    email: EmailSettings | None = None


class AIModels(BaseModel):
    small: str = "claude-haiku-5-5"  # filing suggestions, summaries
    large: str = "claude-sonnet-5-5"  # questions


class AIPrice(BaseModel):
    """USD per million tokens (Anthropic's price list, 2026-10-21)."""

    input_usd_per_mtok: float = Field(ge=0)
    output_usd_per_mtok: float = Field(ge=0)


def _default_prices() -> dict[str, AIPrice]:
    return {
        "claude-haiku-5-5": AIPrice(input_usd_per_mtok=0.10, output_usd_per_mtok=0.50),
        "claude-sonnet-5-5": AIPrice(input_usd_per_mtok=2, output_usd_per_mtok=10),
    }


def _default_max_tokens() -> dict[str, int]:
    # thinking (even at ``effort: low``) counts against max_tokens: room for it plus
    # the answer, so a short answer is not cut off
    return {
        "suggest-filing": 2500,
        "summarize-document": 1500,
        "summarize-collection": 3000,
        "ask-archive": 3000,
    }


class AISettings(BaseModel):
    """Phase 3 AI (spec §2 and §7). The API key is in the Keychain (``dam ai --set-key``),
    never here; the on/off switch is ``<data dir>/ai-state.json`` (``dam ai --on/--off``)."""

    enabled: bool = True
    language: str = "en"
    # how much the model thinks before answering (output_config.effort); our tasks are
    # short extractions, so low keeps the output tokens (and the cost) down
    effort: Literal["low", "medium", "high"] = "low"
    models: AIModels = Field(default_factory=AIModels)
    prices: dict[str, AIPrice] = Field(default_factory=_default_prices)
    usd_to_eur: float = Field(default=0.92, gt=0)
    monthly_budget_eur: float = Field(default=5, ge=0)
    # never sent, in any task (folded: case and NFC variants are caught too)
    exclude_folders: list[str] = Field(
        default_factory=lambda: ["50. Medical", "70. Work", "90. Other People"]
    )
    # per task: the output is priced at this worst case before sending
    max_tokens: dict[str, int] = Field(default_factory=_default_max_tokens)


class Settings(BaseModel):
    # unset until first-run setup (``dam init`` or the app's first-run screen) writes it
    archive_root: Path | None = None
    special_folders: SpecialFolders = Field(default_factory=SpecialFolders)
    protected_paths: list[str] = Field(default_factory=lambda: ["##. Important"])
    indexer_reads_per_minute: int = 30
    # read where the text sits on page 1 of the documents indexed before positions were
    # kept (inbox files are always read); off pauses that backfill
    page1_backfill: bool = True
    ops_throttle_ms: int = 250
    server_port: int = 8765
    ocr_languages: list[str] = Field(default_factory=lambda: ["en-US"])
    reminders: RemindersSettings = Field(default_factory=RemindersSettings)
    ai: AISettings = Field(default_factory=AISettings)

    @field_validator("archive_root", mode="before")
    @classmethod
    def _blank_is_unset(cls, value: object) -> object:
        return None if isinstance(value, str) and not value.strip() else value

    @property
    def configured(self) -> bool:
        return self.archive_root is not None


class AppPaths:
    def __init__(self, data_dir: Path | None = None) -> None:
        if data_dir is None:
            env = os.environ.get("DAM_DATA_DIR")
            data_dir = Path(env) if env else default_data_dir()
        self._data_dir = Path(data_dir)

    @property
    def data_dir(self) -> Path:
        return self._data_dir

    @property
    def db_path(self) -> Path:
        return self._data_dir / "dam.sqlite"

    @property
    def config_dir(self) -> Path:
        return self._data_dir / "config"

    @property
    def cache_dir(self) -> Path:
        return self._data_dir / "cache"

    @property
    def logs_dir(self) -> Path:
        return self._data_dir / "logs"

    def ensure(self) -> None:
        """Create the data directories and seed config from defaults if missing."""
        for d in (self.data_dir, self.cache_dir, self.logs_dir, self.config_dir):
            d.mkdir(parents=True, exist_ok=True)
        if not os.path.lexists(self.config_dir / "settings.yaml"):
            _seed(DEFAULTS_DIR, self.config_dir)
        # Trays came after the first install: seed them into an existing config once
        # (only while the folder is absent, so removed tray files stay removed).
        if not os.path.lexists(self.config_dir / "trays"):
            _seed(DEFAULTS_DIR / "trays", self.config_dir / "trays")
        self._seed_new_default_trays()
        # The code table: seeded only while the file is absent (a saved empty table stays).
        _copy_new(DEFAULTS_DIR / "filing_codes.yaml", self.filing_codes_path)

    @property
    def filing_codes_path(self) -> Path:
        return self.config_dir / "filing_codes.yaml"

    @property
    def seeded_trays_path(self) -> Path:
        return self._data_dir / "tray-defaults-seeded.json"

    def _seed_new_default_trays(self) -> None:
        """Copy a default tray file this install has not been offered before. The names
        already handled are kept in ``tray-defaults-seeded.json``: a file the user
        removed stays removed, and a newer default file (``40-follow-up.yaml``) arrives
        once, unless a tray with the same id is already there under another name."""
        trays_dir = self.config_dir / "trays"
        defaults = sorted(p.name for p in (DEFAULTS_DIR / "trays").glob("*.yaml"))
        try:
            known = json.loads(self.seeded_trays_path.read_text(encoding="utf-8"))
            if not isinstance(known, list):
                raise ValueError
        except FileNotFoundError:
            # first run of this check: the trays that shipped before it were already
            # offered (and may have been removed on purpose)
            known = [n for n in defaults if n in _SHIPPED_BEFORE_SEEDING]
        except (OSError, ValueError):
            return  # unreadable record: seed nothing rather than guess
        taken = {
            m.group(1)
            for p in trays_dir.glob("*.y*ml")
            if p.is_file()
            for m in [
                re.search(r"^id:\s*([\w-]+)", p.read_text(encoding="utf-8", errors="replace"), re.M)
            ]
            if m
        }
        for name in defaults:
            if name in known:
                continue
            source = DEFAULTS_DIR / "trays" / name
            m = re.search(r"^id:\s*([\w-]+)", source.read_text(encoding="utf-8"), re.M)
            if m and m.group(1) in taken:
                known.append(name)  # the user has this tray already
                continue
            _copy_new(source, trays_dir / name)
            known.append(name)
        record = sorted(set(known))
        if not self.seeded_trays_path.exists() or record != sorted(
            set(json.loads(self.seeded_trays_path.read_text(encoding="utf-8")))
        ):
            self.seeded_trays_path.write_text(json.dumps(record), encoding="utf-8")


_SHIPPED_BEFORE_SEEDING = ("10-to-pay.yaml", "20-to-action.yaml", "30-to-read.yaml")


def _copy_new(path: Path, target: Path) -> None:
    """Copy ``path`` to ``target`` unless something (even a dangling symlink) is there."""
    if os.path.lexists(target):
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        # "x": exclusive create, also refuses to follow a symlink planted meanwhile
        with path.open("rb") as source, target.open("xb") as copy:
            shutil.copyfileobj(source, copy)
    except FileExistsError:
        pass


def _seed(src: Path, dst: Path) -> None:
    """Copy the files of ``src`` into ``dst``; an existing entry (even a dangling
    symlink) is never overwritten."""
    for path in sorted(src.rglob("*")):
        if path.is_file():
            _copy_new(path, dst / path.relative_to(src))


def load_settings(app_paths: AppPaths) -> Settings:
    raw = yaml.safe_load((app_paths.config_dir / "settings.yaml").read_text(encoding="utf-8")) or {}
    settings = Settings.model_validate(raw)
    if settings.archive_root is not None:
        settings.archive_root = settings.archive_root.expanduser()
    return settings
