"""The find-relatives AI task: a local shortlist, a preview of exactly what is sent, and
an answer cleaned against the shortlist. The provider is always a fake."""

import pytest
from sqlalchemy import insert, update

from dam.ai import guard
from dam.ai.fake import FakeProvider
from dam.ai.tasks import find_relatives as fr
from dam.db.tables import file_assignments, files
from dam.errors import InvalidRequest

SUBJECT = "20. Home/Insurance/decision.txt"
CASE = "Pohjola vakuutus myrskyvaurio katto korvauspäätös VN-77334421"


def text_of(extra: str = "") -> bytes:
    return f"{CASE} {extra}".encode()


def reply_with(*picks):
    return lambda **_kw: {"matches": [{"id": i, "reason": r, "confidence": c} for i, r, c in picks]}


@pytest.fixture
def farchive(app, fake_archive):
    """A subject and one good candidate; others that must never reach the shortlist."""
    app.ai.provider = FakeProvider(reply_with(("c1", "Same claim number.", 0.9)))
    fake_archive.add(SUBJECT, text_of(), drive_id="subj")
    fake_archive.add("20. Home/Repairs/invoice.txt", text_of("korjauslasku"), drive_id="good")
    fake_archive.add("50. Medical/Lab/claim.txt", text_of("medical"), drive_id="medical")
    fake_archive.add("##. To Delete/old claim.txt", text_of("old"), drive_id="trashed")
    fake_archive.add("20. Home/Insurance/same folder.txt", text_of("saman kansion"), drive_id="rel")
    fake_archive.add("20. Home/Repairs/not related.txt", text_of("ei liity"), drive_id="dism")
    fake_archive.add("20. Home/Repairs/gone.txt", text_of("kadonnut"), drive_id="gone")
    app.scan()
    app.index()
    app.relatives.dismiss("subj", "dism")
    mark_gone(app)
    return fake_archive


def mark_gone(app):
    with app.engine.begin() as conn:
        conn.execute(update(files).where(files.c.drive_id == "gone").values(missing=True))


def ids_of(app, drive_id="subj"):
    cands, _ = fr.shortlist(app, drive_id, app.repo.text_for(drive_id))
    return [c["drive_id"] for c in cands]


def test_shortlist_leaves_out_excluded_dismissed_related_trashed_and_missing(app, farchive):
    # the same-folder file is already a relative of the subject
    assert "rel" in [r.drive_id for r in app.relatives.of("subj").relatives]
    assert ids_of(app) == ["good"]


def test_shortlist_never_holds_the_subject(app, farchive):
    assert "subj" not in ids_of(app)


def test_query_uses_rare_terms_references_ibans_and_sender(app, farchive):
    with app.engine.begin() as conn:
        conn.execute(
            insert(file_assignments).values(
                drive_id="subj", sender="Pohjola Vakuutus", set_by="owner", set_at=1.0
            )
        )
    body = CASE + " maksu FI21 1234 5600 0007 85 viite 20261015"
    match, words = fr.shortlist_query(app, "subj", body)
    assert '"VN-77334421"' in match
    assert '"FI21 1234 5600 0007 85"' in match
    assert '"Pohjola Vakuutus"' in match
    assert '"myrskyvaurio"' in match and " OR " in match
    assert "myrskyvaurio" in words


def test_prepare_sends_only_the_excerpts(app, farchive):
    subject_tail = "SUBJECTTAIL"
    cand_tail = "CANDIDATETAIL"
    long_subject = CASE + " " + "x " * 1100 + subject_tail
    long_cand = CASE + " " + "y " * 200 + cand_tail
    farchive.add(SUBJECT, long_subject.encode(), drive_id="subj")
    farchive.add("20. Home/Repairs/invoice.txt", long_cand.encode(), drive_id="good")
    app.scan()
    app.index()
    mark_gone(app)
    prepared = app.ai.prepare("find-relatives", {"drive_id": "subj"})
    assert prepared.blocked is None
    assert subject_tail not in prepared.payload_text
    assert cand_tail not in prepared.payload_text
    assert "id: c1" in prepared.payload_text and "invoice.txt" in prepared.payload_text
    assert "20. Home/Repairs" in prepared.payload_text
    assert "Medical" not in prepared.payload_text and "To Delete" not in prepared.payload_text
    assert prepared.files == ["subj", "good"]
    assert any("Not sent" in n and "tags" in n for n in prepared.notes)
    assert prepared.estimate_eur > 0
    assert app.ai.provider.calls == []  # a preview sends nothing


def test_run_keeps_only_shortlisted_confident_picks(app, farchive):
    app.ai.provider = FakeProvider(
        reply_with(
            ("c1", "Same claim number VN-77334421.", 0.92),
            ("c7", "Not in the shortlist.", 0.99),
            ("c1", "Duplicate.", 0.5),
        )
    )
    prepared = app.ai.prepare("find-relatives", {"drive_id": "subj"})
    result = app.ai.run(prepared.token, "find-relatives")
    assert result.data["matches"] == [
        {"drive_id": "good", "reason": "Same claim number VN-77334421.", "confidence": 0.92}
    ]
    assert result.data["candidates"] == 1
    assert "not in the shortlist" in result.data["rejected"]["matches"]
    assert app.ai.provider.calls[0]["max_tokens"] == 2000


def test_low_confidence_is_hidden(app, farchive):
    app.ai.provider = FakeProvider(reply_with(("c1", "Maybe.", fr.MIN_CONFIDENCE - 0.01)))
    prepared = app.ai.prepare("find-relatives", {"drive_id": "subj"})
    data = app.ai.run(prepared.token, "find-relatives").data
    assert data["matches"] == [] and data["hidden"] == 1


def test_none_is_an_empty_list(app, farchive):
    app.ai.provider = FakeProvider(reply_with())
    prepared = app.ai.prepare("find-relatives", {"drive_id": "subj"})
    data = app.ai.run(prepared.token, "find-relatives").data
    assert data["matches"] == [] and data["candidates"] == 1


def test_an_answer_from_earlier_costs_nothing(app, farchive):
    first = app.ai.prepare("find-relatives", {"drive_id": "subj"})
    assert first.cached is None
    app.ai.run(first.token, "find-relatives")
    again = app.ai.prepare("find-relatives", {"drive_id": "subj"})
    assert again.cached is not None and again.cached["matches"][0]["drive_id"] == "good"
    result = app.ai.run(again.token, "find-relatives")
    assert result.cached and result.cost_eur == 0.0
    assert len(app.ai.provider.calls) == 1


def test_a_changed_shortlist_is_asked_again(app, farchive):
    first = app.ai.prepare("find-relatives", {"drive_id": "subj"})
    app.ai.run(first.token, "find-relatives")
    app.relatives.dismiss("subj", "good")
    farchive.add("20. Home/Repairs/second.txt", text_of("toinen"), drive_id="second")
    app.scan()
    app.index()
    mark_gone(app)
    again = app.ai.prepare("find-relatives", {"drive_id": "subj"})
    assert again.cached is None and again.files == ["subj", "second"]


def test_over_budget_is_refused(app, farchive):
    app.settings.ai.monthly_budget_eur = 0
    prepared = app.ai.prepare("find-relatives", {"drive_id": "subj"})
    assert prepared.blocked is not None and "over budget" in prepared.blocked
    with pytest.raises(InvalidRequest, match="over budget"):
        app.ai.run(prepared.token, "find-relatives")
    assert app.ai.provider.calls == []


def test_a_subject_in_an_excluded_folder_is_refused(app, farchive):
    prepared = app.ai.prepare("find-relatives", {"drive_id": "medical"})
    assert prepared.blocked is not None and "excluded folder" in prepared.blocked
    assert prepared.payload_text == ""
    with pytest.raises(InvalidRequest, match="excluded folder"):
        app.ai.run(prepared.token, "find-relatives")
    assert app.ai.provider.calls == []


def test_no_candidates_says_so_without_a_call(app, fake_archive):
    app.ai.provider = FakeProvider(reply_with())
    fake_archive.add(SUBJECT, text_of(), drive_id="subj")
    app.scan()
    app.index()
    prepared = app.ai.prepare("find-relatives", {"drive_id": "subj"})
    assert prepared.blocked == fr.NOTHING and prepared.payload_text == ""
    assert prepared.files == []
    assert app.ai.provider.calls == []


def test_candidate_cap_and_limits():
    assert fr.CANDIDATES == 28 and fr.CANDIDATE_CHARS == 300 and fr.SUBJECT_CHARS == 2000
    assert fr.MIN_CONFIDENCE == 0.6
    assert guard.DATA_PREAMBLE in fr.system_prompt("English")


BASE = "http://127.0.0.1:8765"
H = {"Origin": BASE}


def test_the_api_answers_with_the_files_as_they_are_now(app, farchive):
    from fastapi.testclient import TestClient

    from dam.api import create_api

    with TestClient(create_api(app), base_url=BASE) as client:
        prep = client.post(
            "/api/ai/find-relatives/prepare", json={"params": {"drive_id": "subj"}}, headers=H
        ).json()
        assert prep["blocked"] is None
        run = client.post(
            "/api/ai/find-relatives/run", json={"token": prep["token"]}, headers=H
        ).json()
        pick = run["data"]["matches"][0]
        assert pick["drive_id"] == "good" and pick["name"] == "invoice.txt"
        assert pick["path"] == "20. Home/Repairs/invoice.txt" and pick["in_inbox"] is False
        assert pick["folder"] == "20. Home/Repairs" and pick["reason"] == "Same claim number."
        # marked "Not related" after the answer was kept: it no longer shows
        app.relatives.dismiss("subj", "good")
        again = client.post(
            "/api/ai/find-relatives/prepare", json={"params": {"drive_id": "subj"}}, headers=H
        ).json()
        assert again["blocked"] == fr.NOTHING
        app.relatives.restore("subj", "good")
        prep = client.post(
            "/api/ai/find-relatives/prepare", json={"params": {"drive_id": "subj"}}, headers=H
        ).json()
        assert prep["cached"] is not None
        app.relatives.dismiss("subj", "good")
        data = fr.resolve(app, prep["cached"])
        assert data["matches"] == []
