"""The App is built in groups (``dam.app.BUILD_ORDER``), each from explicit inputs. A
group that needs something a later group makes, or a part that never reaches the App,
fails here rather than at the first request that touches it. Fake archives only."""

import dataclasses
import inspect
import typing

import pytest

from dam import app as app_module
from dam.app import BUILD_ORDER, App

# what ``App.create`` has before the first group, and the App itself (``live``)
BASE = {"settings", "app_paths", "paths", "engine", "jobs", "live"}


def _check_order(order) -> None:
    """Raise ``AssertionError`` when a group takes an input no earlier group made."""
    names, types = set(BASE), set()
    for build in order:
        hints = typing.get_type_hints(build, vars(app_module))
        for param in inspect.signature(build).parameters:
            assert param in names or hints[param] in types, f"{build.__name__} needs {param}"
        made = hints["return"]
        types.add(made)
        names |= {f.name for f in dataclasses.fields(made)}


def test_each_group_is_built_from_what_came_before():
    _check_order(BUILD_ORDER)


def test_a_wrong_order_is_caught():
    with pytest.raises(AssertionError, match="needs"):
        _check_order(tuple(reversed(BUILD_ORDER)))


def _parts() -> set[str]:
    out: set[str] = set()
    for build in BUILD_ORDER:
        made = typing.get_type_hints(build, vars(app_module))["return"]
        out |= {f.name for f in dataclasses.fields(made)}
    return out


def test_every_part_is_an_app_field_and_every_service_comes_from_a_group():
    later = {
        f.name
        for f in dataclasses.fields(App)
        if not f.init
        and f.default is dataclasses.MISSING
        and f.default_factory is dataclasses.MISSING
    }
    # set by the App itself
    assert later - _parts() == {"wake_indexer", "_packs", "_packs_before"}
    assert _parts() <= {f.name for f in dataclasses.fields(App)}


def test_the_built_app_has_every_part_wired(app):
    for name in _parts():
        assert getattr(app, name) is not None, name
    assert app.executor.locks is app.locks
    assert app.executor.copying == app.copy_jobs.running
    assert app.browse.copy_jobs is app.copy_jobs
    assert app.collections.on_change is not None
    assert app.convert.sync_publishers is app.collections.on_change
    assert app.content.thumbs == app.pictures.thumbs
    assert app.ai.app is app


def test_the_api_middleware_runs_in_its_order(app):
    """The host and origin checks wrap everything else, so they run first."""
    from dam.api import create_api
    from dam.api.security import (
        ArchiveGuardMiddleware,
        InternalErrorMiddleware,
        LocalOnlyMiddleware,
        UnlockTokenMiddleware,
    )

    class Archives:
        current_id = "main"
        switcher = None

    for archives, guard in ((None, []), (Archives(), [ArchiveGuardMiddleware])):
        api = create_api(app, None, archives)  # type: ignore[arg-type]
        outermost_first = [m.cls for m in api.user_middleware]
        assert outermost_first == [
            LocalOnlyMiddleware,
            InternalErrorMiddleware,
            UnlockTokenMiddleware,
            *guard,
        ]
