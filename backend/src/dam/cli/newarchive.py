"""The "start a new archive here" part of ``dam init``: choose and edit a layout."""

from pathlib import Path

import typer

from dam import layouts
from dam import setup as dam_setup
from dam.config import DEFAULTS_DIR, SpecialFolders
from dam.services.errors import InvalidRequest
from dam.services.layout import layout_label, spec_from_input


def _say(text: str = "") -> None:
    typer.echo(text)


def show_folders(spec: layouts.Spec, existing: set[str]) -> list[layouts.Folder]:
    """Print the folders the layout wants; ``existing`` (folded names already in the
    folder) are marked as left alone. Raises ``InvalidRequest`` for a bad name."""
    try:
        folders = layouts.build_folders(spec)
    except layouts.LayoutError as e:
        raise InvalidRequest(str(e)) from None
    for f in folders:
        mark = "  (exists, left as it is)" if layouts.nfc(f.path).casefold() in existing else ""
        _say(f"  {f.path}{mark}")
    return folders


def _edit_rows(rows: list[layouts.Row]) -> list[layouts.Row]:
    _say("\nEdit the list: 'r 3 New name' renames no. 3, 'd 3' removes it, 'a Name' adds one.")
    _say("Press Enter when it is right.")
    while True:
        for i, row in enumerate(rows, 1):
            _say(f"  {i}. {row.name}")
        line = typer.prompt("Edit", default="", show_default=False).strip()
        if not line:
            return rows
        cmd, _, rest = line.partition(" ")
        rest = rest.strip()
        try:
            if cmd == "a" and rest:
                rows = [*rows, layouts.Row(None, rest)]
            elif cmd == "d":
                n = int(rest)
                rows = [r for i, r in enumerate(rows, 1) if i != n]
            elif cmd == "r":
                num, _, name = rest.partition(" ")
                n = int(num)
                if not name.strip() or not 1 <= n <= len(rows):
                    raise ValueError
                rows = [
                    layouts.Row(r.key, name.strip()) if i == n else r for i, r in enumerate(rows, 1)
                ]
            else:
                raise ValueError
        except ValueError:
            typer.echo("Use: r NUMBER NEW NAME, d NUMBER or a NAME.", err=True)


def _ask_special() -> SpecialFolders:
    names = SpecialFolders()
    _say("\nThe app also uses four special folders (they are made too):")
    for item in dam_setup.special_folders(names):
        _say(f"  {item['name']}  {item['title']}: {item['purpose']}")
    if not typer.confirm("Change their names?", default=False):
        return names
    values = {}
    for item in dam_setup.special_folders(names):
        values[item["role"]] = typer.prompt(item["title"], default=item["name"]).strip()
    return SpecialFolders(**values)


def choose_layout(
    chosen: Path,
    template_id: str | None,
    numbered: bool,
    yes: bool,
    defaults_dir: Path = DEFAULTS_DIR,
) -> layouts.Spec | None:
    """The layout for the archive at ``chosen``, or None for "use as is".

    ``template_id`` (``--layout``) skips the questions about whether and which layout
    (``none`` means no layout). Otherwise, unless ``yes``: an empty
    folder is offered "Start a new archive here" (default yes); a folder with content
    defaults to "use as is" and only adds a layout if asked."""
    templates = layouts.load_templates(defaults_dir)
    if template_id == "none":
        return None
    if template_id is None:
        if yes:
            return None
        empty = dam_setup.is_empty_folder(chosen)
        if empty:
            _say(f"\n{chosen} is empty.")
            if not typer.confirm("Start a new archive here?", default=True):
                return None
        else:
            count = len(dam_setup.visible_entries(chosen))
            _say(f"\n{chosen} already holds {count} item(s); it will be used as it is.")
            if not typer.confirm(
                "Add a folder layout anyway? (only folders that do not exist yet are made)",
                default=False,
            ):
                return None
        titles = [f"{t.title}: {t.description}" for t in templates]
        template_id = templates[_index(titles)].id
    template = layouts.find_template(template_id, templates)
    if template is None:
        known = ", ".join(t.id for t in templates)
        raise InvalidRequest(f"Unknown layout {template_id!r}. Choose one of: {known}, none.")
    interactive = not yes
    if interactive:
        numbered = typer.confirm(
            "Number the folders (10. Finance, 11. Bills & Receipts, ...)? This keeps them in "
            "your order.",
            default=numbered,
        )
    rows = list(template.folders)
    special = _ask_special() if interactive else SpecialFolders()
    if interactive:
        rows = _edit_rows(rows)
    return spec_from_input(
        templates, template.id, numbered, [(r.key, r.name) for r in rows], special
    )


def _index(options: list[str]) -> int:
    typer.echo("Choose a starter layout:")
    for i, label in enumerate(options, 1):
        typer.echo(f"  {i}. {label}")
    while True:
        answer = typer.prompt("Number", default="", show_default=False).strip()
        if answer.isdigit() and 1 <= int(answer) <= len(options):
            return int(answer) - 1
        typer.echo(f"Enter a number from 1 to {len(options)}.", err=True)


def preview_text(spec: layouts.Spec, chosen: Path) -> list[layouts.Folder]:
    """Print the preview of the layout at ``chosen`` and return its folders."""
    existing = layouts.existing_names(chosen if chosen.is_dir() else None)
    _say("\nThese folders will be made inside the archive:")
    folders = show_folders(spec, existing)
    missing = sum(1 for f in folders if layouts.nfc(f.path).casefold() not in existing)
    _say(f"\n{layout_label(missing)}")
    return folders
