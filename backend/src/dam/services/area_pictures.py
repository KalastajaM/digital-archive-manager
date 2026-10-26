"""The crops of picture areas: cut from a document's page-1 picture, shown to the owner,
and saved with the rules (``config/rules/areas``). Nothing is read from the archive: the
page-1 picture is in the cache."""

import base64
import re
import threading
from collections.abc import Callable, Collection
from pathlib import Path

from PIL import Image, ImageStat

from dam.codes.configfile import write_config_bytes
from dam.extract.layout import Box, check_box
from dam.extract.picture import picture_path
from dam.index.repo import FileRepo
from dam.ops.executor import Executor
from dam.ops.model import ABS_TARGET, BatchResult, Op, OpKind, Plan
from dam.rules.model import Rule
from dam.rules.picture import AREAS_DIR, PictureError, crop_file, cut_crop, png_bytes
from dam.services import check_origin
from dam.services.errors import InvalidRequest, NotFound

_NOT_NAME = re.compile(r"[^A-Za-z0-9._-]+")
MAX_PER_RULE = 99
# a smaller crop would be under 4 px at matching size and always score 0
MIN_SIDE = 0.01
# a crop whose grey levels hardly vary (standard deviation, 0 to 255) is blank paper with
# scan noise: there is nothing in it to recognise
MIN_CONTRAST = 6.0
# the name a picture gets in ##. To Delete, so it is recognisable there
QUARANTINE_PREFIX = "dam rule picture "


def file_stem(rule_id: str) -> str:
    """``rule_id`` as the start of a file name: letters, digits, dot, dash, underscore."""
    stem = _NOT_NAME.sub("-", rule_id).strip("-._")[:60]
    return stem or "rule"


class AreaPictures:
    def __init__(
        self,
        repo: FileRepo,
        cache_dir: Path,
        rules_dir: Callable[[], Path],
        want_layouts: Callable[[Collection[str]], None] | None = None,
        executor: Executor | None = None,
    ) -> None:
        self.repo = repo
        self.cache_dir = cache_dir
        self.rules_dir = rules_dir
        self._want = want_layouts
        self.executor = executor
        self._save_lock = threading.Lock()  # picking a free name and writing it are one step

    def crop(self, drive_id: str, box: list[float]) -> Image.Image:
        """The part of the document's page-1 picture inside ``box``. ``NotFound`` for an
        unknown document, ``InvalidRequest`` for a bad box or a picture not made yet."""
        try:
            area: Box = check_box(box)
        except ValueError as e:
            raise InvalidRequest(str(e)) from e
        if area[2] - area[0] < MIN_SIDE or area[3] - area[1] < MIN_SIDE:
            raise InvalidRequest(
                "That picture area is too small: draw it at least 1% of the page wide and high."
            )
        rec = self.repo.get(drive_id)
        if rec is None or rec.missing or rec.parked_at is not None:
            raise NotFound(drive_id)
        path = picture_path(self.cache_dir, drive_id, rec.sha256 or "")
        try:
            with Image.open(path) as page:
                page.load()
                crop = cut_crop(page, area)
        except (OSError, ValueError):
            if self._want is not None:
                self._want([drive_id])  # the picture pass makes it next
            raise InvalidRequest(
                "The picture of page 1 of this document is not made yet. Try again in a moment."
            ) from None
        if ImageStat.Stat(crop.convert("L")).stddev[0] < MIN_CONTRAST:
            raise InvalidRequest("There is nothing in that area: no text and no picture.")
        return crop

    @staticmethod
    def preview(crop: Image.Image) -> dict:
        """The crop as the API shows it: its size and a base64 PNG."""
        return {
            "width": crop.width,
            "height": crop.height,
            "png": base64.b64encode(png_bytes(crop)).decode("ascii"),
        }

    def save(self, rule_id: str, crop: Image.Image) -> str:
        """Keep ``crop`` as ``areas/<rule-id>-<n>.png`` (the first free number, so no
        picture a rule uses is overwritten) with the same safe write as the rule files.
        Returns the path a zone's ``image`` names."""
        stem = file_stem(rule_id)
        data = png_bytes(crop)
        # the lock covers picking the name and writing the file: two saves at once would
        # otherwise pick the same free name and the second would overwrite the first
        with self._save_lock:
            folder = Path(self.rules_dir()) / AREAS_DIR
            for n in range(1, MAX_PER_RULE + 1):
                name = f"{stem}-{n}.png"
                if not (folder / name).exists():
                    break
            else:
                raise InvalidRequest("That rule has too many picture files; remove some first.")
            image = f"{AREAS_DIR}/{name}"
            try:
                path = crop_file(self.rules_dir(), image)
            except PictureError as e:
                raise InvalidRequest(str(e)) from e

            def verify() -> bool:
                with Image.open(path) as back:
                    back.load()
                    return back.size == crop.size and path.read_bytes() == data

            try:
                write_config_bytes(path, data, verify)
            except OSError as e:
                raise InvalidRequest(f"The picture could not be saved: {e}") from e
        return image

    def file(self, name: str) -> Path:
        """The saved picture ``name`` (a file in ``areas``); ``NotFound`` if there is none."""
        try:
            path = crop_file(self.rules_dir(), f"{AREAS_DIR}/{name}")
        except PictureError:
            raise NotFound(name) from None
        if not path.is_file():
            raise NotFound(name)
        return path

    def unused(self, rules: list[Rule]) -> list[str]:
        """The picture files in ``areas`` that no loaded rule uses (a deleted rule leaves
        its pictures until they are moved to To Delete)."""
        used = {z.image for r in rules for z in r.when.zones if z.image}
        folder = Path(self.rules_dir()) / AREAS_DIR
        try:
            names = sorted(p.name for p in folder.iterdir() if p.suffix == ".png" and p.is_file())
        except OSError:
            return []
        return [n for n in names if f"{AREAS_DIR}/{n}" not in used]

    def quarantine_unused(
        self,
        names: list[str],
        rules: Callable[[], list[Rule]],
        origin: str,
        dry_run: bool = False,
    ) -> BatchResult:
        """Move the unused pictures ``names`` (files in ``areas``) into the quarantine
        folder as ``dam rule picture <name>``, through the operation layer: previewed with
        ``dry_run``, journaled, undoable. Renamed on one disk; across disks copied and verified
        before dam's own copy is removed (never an archive file). ``InvalidRequest`` (nothing
        planned) when ``names`` is empty or names a picture that a loaded rule uses, or
        that is not there. The list of unused pictures is read under the save lock, so
        no picture is being saved in between."""
        check_origin(origin)
        if self.executor is None:
            raise InvalidRequest("Pictures cannot be moved here.")
        wanted = list(dict.fromkeys(names))
        if not wanted:
            raise InvalidRequest("Pick at least one unused picture.")
        quarantine = self.executor.paths.quarantine  # the main folder's: pictures live there
        with self._save_lock:
            unused = set(self.unused(rules()))
            for name in wanted:
                if name not in unused:
                    raise InvalidRequest(
                        f"The picture {name} is used by a rule or is not in the rules'"
                        " picture folder, so it is not moved."
                    )
            folder = Path(self.rules_dir()) / AREAS_DIR
            ops = [
                Op(
                    OpKind.PICTURE_TO_QUARANTINE,
                    f"{ABS_TARGET}{folder / name}",
                    quarantine,
                    name=f"{QUARANTINE_PREFIX}{name}",
                )
                for name in wanted
            ]
            what = wanted[0] if len(wanted) == 1 else f"{len(wanted)} unused rule pictures"
            plan = Plan(ops, origin=origin, label=f"Moved {what} to To Delete")
            return self.executor.apply(plan, dry_run=dry_run)


def check_pictures_exist(rules_dir: Path, rule: Rule) -> None:
    """``InvalidRequest`` when a picture area of ``rule`` names a file that is not there."""
    for z in rule.when.zones:
        if z.image is None:
            continue
        try:
            ok = crop_file(rules_dir, z.image).is_file()
        except PictureError:
            ok = False
        if not ok:
            raise InvalidRequest(f"The picture {z.image} of an area is not there.")
