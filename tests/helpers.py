"""Deterministic provider models and in-memory fixtures, not product substitutes."""

import asyncio
import io
import json
from dataclasses import dataclass

from openpyxl import Workbook

from app.agents.action_selector import ActionSelector
from app.core.config import Settings
from app.schemas.batch import TERMINAL_STATES
from app.services.investigation_service import InvestigationService
from app.services.sentiment_service import SentimentService

TEST_KEY = "qa-fabricated-development-key"
SENSITIVE = "qa-private-sentinel-never-a-real-secret"


def settings(**overrides):
    return Settings(_env_file=None, app_api_key=TEST_KEY, groq_api_key=None, **({'batch_job_ttl_seconds':1800} | overrides))


def analysis(text, sentiment="NEGATIVE", category="DELIVERY", **overrides):
    result = {
        "sentiment": sentiment, "issue_category": category, "urgency": "LOW",
        "aspects": [{"name": "delivery", "sentiment": sentiment}],
        "summary": "Fabricated feedback classification.",
        "suggested_next_step": "Consider reviewing the supplied feedback.",
        "evidence_phrases": [text],
    }
    return result | overrides


class Model:
    def __init__(self, *, outputs=None, errors=None, gate=None, delay=0):
        self.outputs = outputs or {}
        self.errors = errors or {}
        self.gate = gate
        self.delay = delay
        self.calls = []
        self.active = self.peak = 0

    async def ainvoke(self, messages):
        payload = json.loads(messages[-1][1])
        self.calls.append(payload)
        self.active += 1
        self.peak = max(self.peak, self.active)
        try:
            if self.gate is not None:
                await self.gate.wait()
            if self.delay:
                await asyncio.sleep(self.delay)
            text = payload["text"]
            if text in self.errors:
                raise self.errors[text]
            return self.outputs.get(text, analysis(text))
        finally:
            self.active -= 1


class SelectionModel:
    def __init__(self, action="GENERAL_FEEDBACK_SUMMARY", *, output=None, delay=0):
        self.output = output if output is not None else {
            "action": action, "category": None, "sentiment": None, "evidence_limit": 3,
        }
        self.calls = []
        self.delay = delay

    async def ainvoke(self, messages):
        self.calls.append(json.loads(messages[-1][1]))
        if self.delay:
            await asyncio.sleep(self.delay)
        return self.output


@dataclass
class Harness:
    model: Model
    selector: SelectionModel
    sentiment: SentimentService
    investigation: InvestigationService


def harness(*, action="GENERAL_FEEDBACK_SUMMARY", model=None, selector=None):
    model = model if model is not None else Model()
    selector = selector if selector is not None else SelectionModel(action)
    sentiment = SentimentService(model, max_retries=0)
    investigation = InvestigationService(ActionSelector(selector), sentiment)
    return Harness(model, selector, sentiment, investigation)


def xlsx(rows, *, second_sheet=None):
    book = Workbook()
    for row in rows:
        book.active.append(row)
    if second_sheet is not None:
        sheet = book.create_sheet("ignored")
        for row in second_sheet:
            sheet.append(row)
    stream = io.BytesIO()
    book.save(stream)
    book.close()
    return stream.getvalue()


async def until(predicate, timeout=3):
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(.002)


async def settled(manager, identifier):
    await until(lambda: manager.status(identifier).status in TERMINAL_STATES)
