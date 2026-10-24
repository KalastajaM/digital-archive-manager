"""A fake archive's INDEX at the scale of a real one, for timing the rule replay.

Only a temporary database and a temporary cache are written: no archive folder, never a
real data directory. ``build`` fills the ``files``, ``file_text`` and ``file_layouts``
tables (about 11 000 indexed files, 9 000 of them PDFs and images, with short and very
long texts, about 35 % of the PDFs and images with a page-1 layout with word boxes and a
page-1 picture) and writes the page-1 pictures into a cache folder.

Run it as a timing script (it prints a table, numbers only)::

    uv run python tests/bigfake.py [--files 11000] [--budget 600]
"""

from __future__ import annotations

import argparse
import hashlib
import random
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).parent))
import synth  # noqa: E402
from dam.config import SpecialFolders  # noqa: E402
from dam.db.engine import make_engine, migrate  # noqa: E402
from dam.db.tables import file_assignments, file_layouts, file_text, files  # noqa: E402
from dam.extract.layout import Line, Page1Layout, Word  # noqa: E402
from dam.extract.picture import encode, page_picture, picture_path  # noqa: E402
from dam.index.repo import FileRepo  # noqa: E402
from dam.rules.model import Rule  # noqa: E402
from dam.rules.picture import Pictures, cut_crop, png_bytes  # noqa: E402

WORDS = (
    "lasku maksu eräpäivä kiitos tilinumero viite summa vakuutus korvaus päätös hakemus "
    "sairaus lääkäri palkka vero verotus tulot ostos kuitti takuu sopimus vuokra sähkö "
    "vesi lämmitys kiinteistö asunto osakkeet pankki laina korko tili siirto yhteensä "
    "invoice payment due amount reference account statement insurance claim decision "
    "application medical doctor salary tax income receipt warranty contract rent "
    "electricity water heating property apartment shares bank loan interest transfer total "
    "päivämäärä asiakas numero kappale hinta alv yhteystiedot osoite puhelin sähköposti"
).split()
FOLDERS = [
    "10. Financial/Banks",
    "10. Financial/Taxes",
    "11. Bills & Receipts",
    "12. Insurance/Pohjola",
    "12. Insurance/If",
    "20. Home",
    "30. Work",
    "40. Cars",
    "50. Medical/Kela",
    "50. Medical/Doctor",
    "60. Travel",
    "70. School",
]
KELA = "Kansaneläkelaitos"
BOX = synth.LOGO_BOX  # the logo (picture area)
HEADER = (0.05, 0.02, 0.45, 0.10)  # the header text area, where the sender's name sits


@dataclass
class Fake:
    root: Path
    engine: object
    cache_dir: Path
    rules_dir: Path
    repo: FileRepo
    pictures: Pictures
    special: SpecialFolders
    n_files: int
    kela_ids: list[str]
    text_bytes: int
    layouts: int


def _blobs(rnd: random.Random) -> list[str]:
    out = []
    for _ in range(6):
        out.append(" ".join(rnd.choices(WORDS, k=45000)))  # about 300 KB each
    return out


def _layout(rnd: random.Random, header: str | None) -> Page1Layout:
    lines: list[Line] = []
    y = 0.03
    if header:
        words = header.split()
        step = 0.2 / max(1, len(words))
        lines.append(
            Line(
                header,
                (0.06, 0.04, 0.06 + 0.2, 0.07),
                [
                    Word(w, (0.06 + i * step, 0.04, 0.06 + (i + 1) * step - 0.005, 0.07))
                    for i, w in enumerate(words)
                ],
            )
        )
        y = 0.12
    while y < 0.95:
        ws = rnd.choices(WORDS, k=rnd.randint(4, 9))
        x = 0.08
        wl = []
        for w in ws:
            width = 0.011 * len(w)
            wl.append(Word(w, (x, y, x + width, y + 0.012)))
            x += width + 0.012
        lines.append(Line(" ".join(ws), (0.08, y, x, y + 0.012), wl))
        y += 0.022
    return Page1Layout(lines, "text-layer")


def build(
    root: Path,
    n_files: int = 11000,
    seed: int = 7,
    *,
    long_share: float = 0.04,
    layout_share: float = 0.35,
) -> Fake:
    rnd = random.Random(seed)
    root.mkdir(parents=True, exist_ok=True)
    cache_dir, rules_dir = root / "cache", root / "rules"
    (rules_dir / "areas").mkdir(parents=True, exist_ok=True)
    engine = make_engine(root / "dam.sqlite")
    migrate(engine)
    special = SpecialFolders()
    repo = FileRepo(engine, inbox=special.inbox)

    # the pictures: a few variants of a page with the logo, a few with another one
    variants: list[bytes] = []
    for kind, n in ((0, 6), (1, 6)):
        for k in range(n):
            img = synth.noisy(
                synth.letter(kind, shift=(rnd.randint(-8, 8), rnd.randint(-6, 6)), seed=k), 3, k
            )
            variants.append(encode(page_picture(img)))
    crop = cut_crop(page_picture(synth.letter(0)), BOX)
    (rules_dir / "areas" / "bench-1.png").write_bytes(png_bytes(crop))

    blobs = _blobs(rnd)
    file_rows, text_rows, layout_rows = [], [], []
    kela_ids: list[str] = []
    text_bytes = layouts = 0
    n_media = int(n_files * 0.82)
    for i in range(n_files):
        folder = rnd.choice(FOLDERS)
        media = i < n_media
        ext = (
            rnd.choice(["pdf"] * 8 + ["jpg", "png"])
            if media
            else rnd.choice(["docx", "txt", "xlsx"])
        )
        drive_id = f"d{i}"
        sha = hashlib.sha256(drive_id.encode()).hexdigest()
        year = rnd.randint(2015, 2026)
        name = f"{year}{rnd.randint(1, 12):02d}{rnd.randint(1, 28):02d}_{rnd.choice(WORDS)}_{i}"
        path = f"{folder}/{year}/{name}.{ext}"
        file_rows.append(
            dict(
                drive_id=drive_id, path=path, path_nfc=path, name=f"{name}.{ext}", ext=ext,
                is_dir=False, is_link=False, size=1000 + i, mtime=1.7e9, sha256=sha,
                doc_date=date(year, 1, 1), index_state="indexed", missing=False,
                last_seen=1.7e9, parked_at=None, attempts=0,
            )
        )  # fmt: skip
        r = rnd.random()
        if r < long_share:
            n = rnd.randint(120_000, 260_000)  # 40 to 90 pages
        elif r < 0.30:
            n = rnd.randint(3_000, 15_000)
        else:
            n = rnd.randint(200, 1_200)
        blob = blobs[rnd.randrange(len(blobs))]
        start = rnd.randrange(0, len(blob) - n)
        body = blob[start : start + n]
        is_kela = media and folder.endswith("Kela") and rnd.random() < 0.7
        decoy = media and not is_kela and rnd.random() < 0.02  # mentions the word in the body
        head = None
        if is_kela:
            head = KELA
            kela_ids.append(drive_id)
        elif media and rnd.random() < 0.5:
            head = rnd.choice(["Pohjola Vakuutus", "If Vahinkovakuutus", "Op Pankki", "Fortum"])
        lay = None
        if media and rnd.random() < layout_share:
            lay = _layout(rnd, head)
            layouts += 1
            layout_rows.append(
                dict(
                    drive_id=drive_id, sha256=sha, lines=lay.lines_json(), source="text-layer",
                    read_at=1.7e9,
                )
            )  # fmt: skip
            variant = variants[rnd.randrange(6)] if is_kela else variants[rnd.randrange(12)]
            p = picture_path(cache_dir, drive_id, sha)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(variant)
        text = (lay.text + "\n" if lay else (head + "\n" if head else "")) + body
        if decoy:
            text += f" {KELA} "
        text_bytes += len(text)
        text_rows.append(
            dict(drive_id=drive_id, text=text, extractor="fake", ocr_used=media and r > 0.9)
        )
    with engine.begin() as conn:
        for rows, table in (
            (file_rows, files),
            (text_rows, file_text),
            (layout_rows, file_layouts),
        ):
            for k in range(0, len(rows), 1000):
                conn.execute(table.insert(), rows[k : k + 1000])
    pictures = Pictures(lambda: rules_dir, cache_dir)
    return Fake(
        root, engine, cache_dir, rules_dir, repo, pictures, special, n_files, kela_ids,
        text_bytes, layouts,
    )  # fmt: skip


def assign_sender(fake: Fake, sender: str, drive_ids: list[str]) -> None:
    with fake.engine.begin() as conn:
        conn.execute(
            file_assignments.insert(),
            [
                dict(drive_id=d, sender=sender, person=None, set_by="owner", set_at=1.7e9)
                for d in drive_ids
            ],
        )


def rules() -> dict[str, Rule]:
    then = {"folder": "50. Medical/Kela", "name": "{doc_date:%Y%m%d}_Kela"}
    word = {"text_contains": ["kansaneläkelaitos"]}
    text_zone = {"box": list(HEADER), "text_contains": ["kansaneläkelaitos"]}
    pic_zone = {"box": list(BOX), "image": "areas/bench-1.png"}
    defs = {
        "a_word": {"id": "kela", "when": word, "then": then},
        "b_picture": {"id": "kela", "when": {"zones": [pic_zone]}, "then": then},
        "c_text_picture": {"id": "kela", "when": {"zones": [text_zone, pic_zone]}, "then": then},
        "d_text_area": {"id": "kela", "when": {"zones": [text_zone]}, "then": then},
    }
    return {k: Rule.model_validate(v) for k, v in defs.items()}


def main() -> None:
    from dam.rules.replay import ReplayRun

    ap = argparse.ArgumentParser()
    ap.add_argument("--files", type=int, default=11000)
    ap.add_argument("--budget", type=float, default=600.0)
    args = ap.parse_args()
    with tempfile.TemporaryDirectory(prefix="dam-bigfake-") as tmp:
        t0 = time.perf_counter()
        fake = build(Path(tmp), args.files)
        print(
            f"built {fake.n_files} files, {fake.layouts} layouts, "
            f"{fake.text_bytes / 1e6:.0f} MB text in {time.perf_counter() - t0:.1f} s"
        )
        for name, rule in rules().items():
            t = time.perf_counter()
            run = ReplayRun(
                fake.engine, rule, [rule], fake.special,
                layouts_for=fake.repo.layouts_for, pictures=fake.pictures,
            )  # fmt: skip
            run.advance(args.budget)
            total = time.perf_counter() - t
            r = run.snapshot()
            print(
                f"{name:15s} {total:6.2f} s  checked {r.checked}/{r.total} matched {r.matched} "
                f"not_checked {len(r.not_checked)}"
            )
            print("    " + run.timings.summary(total))
        fake.engine.dispose()


if __name__ == "__main__":
    Image.MAX_IMAGE_PIXELS = None
    main()
