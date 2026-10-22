"""summarize-document: what a bill or document is about, in two sentences and up to five
key facts (spec §3). Running it saves nothing: the summary is stored only when the user
clicks "Use this summary" (``PUT /api/files/{id}/summary`` with ``source: "ai"``)."""

from typing import TYPE_CHECKING, Any

from dam.ai import guard
from dam.ai.tasks import Built, register
from dam.ai.tasks._common import digest, language, shorten, source

if TYPE_CHECKING:
    from dam.app import App

SUMMARY_CHARS = 400
FACTS = 5
FACT_CHARS = 200

SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string", "maxLength": SUMMARY_CHARS},
        "key_facts": {
            "type": "array",
            "items": {"type": "string", "maxLength": FACT_CHARS},
            "maxItems": FACTS,
        },
    },
    "required": ["summary", "key_facts"],
    "additionalProperties": False,
}


def system_prompt(lang: str) -> str:
    return (
        "You summarize one document from the user's family archive. Answer with a "
        "summary of at most two sentences saying what the document is and what it is "
        "about (who it is from, what for, any amount or date that matters), and "
        f"key_facts: at most {FACTS} short facts (amounts, dates, reference numbers, "
        f"names). Limits: the summary at most {SUMMARY_CHARS} characters, at most "
        f"{FACTS} facts of up to {FACT_CHARS} characters each. Write in {lang}. "
        "Keep the document's proper names (company names, Finnish terms) as they "
        f"appear in it. {guard.DATA_PREAMBLE}"
    )


class SummarizeDocument:
    id = "summarize-document"
    model_tier = "small"
    prompt_version = "v2"
    schema = SCHEMA

    def build(self, app: "App", params: dict[str, Any]) -> Built:
        src = source(app, params)
        rec = src.record
        lang = language(app)
        system = system_prompt(lang)
        if src.excluded is not None or src.blocked is not None:
            return Built(system, "", [rec.drive_id], "", src.blocked)
        user = (
            "File name:\n"
            + guard.delimited("file_name", rec.name or "")
            + "\n\nDocument text:\n"
            + guard.delimited("document", src.text)
        )
        sha_key = digest(
            {
                "task": self.id,
                "sha256": rec.sha256,
                "text": digest(src.text),
                "name": rec.name,
                "language": lang,
            }
        )
        return Built(system, user, [rec.drive_id], sha_key)

    def post(self, data: dict, built: Built) -> dict:
        # the limits are soft (the service does not reject an answer over them)
        facts = [shorten(f, FACT_CHARS) for f in data["key_facts"] if f.strip()][:FACTS]
        return {"summary": shorten(data["summary"], SUMMARY_CHARS), "key_facts": facts}


register(SummarizeDocument())
