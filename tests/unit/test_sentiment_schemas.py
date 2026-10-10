import pytest
from pydantic import ValidationError

from app.schemas.sentiment import SentimentRequest, SentimentResponse
from tests.helpers import analysis


@pytest.mark.parametrize("sentiment", ["POSITIVE", "NEGATIVE", "NEUTRAL", "MIXED"])
def test_classifications_and_exact_evidence(sentiment):
    result = SentimentResponse.model_validate(analysis("Original text", sentiment),
                                              context={"feedback_text": "Original text"})
    assert result.sentiment == sentiment
    assert result.evidence_phrases == ["Original text"]


@pytest.mark.parametrize("payload", [
    {}, {"text": ""}, {"text": " \n"}, {"text": "x" * 5001}, {"text": 123},
    {"text": "x", "source": "file_upload"}, {"text": "x", "business_type": "unknown"},
    {"text": "x", "tenant_id": "another-business"}, {"text": "x", "source": None},
])
def test_invalid_requests(payload):
    with pytest.raises(ValidationError):
        SentimentRequest.model_validate(payload)


@pytest.mark.parametrize("updates", [
    {"sentiment": "UNKNOWN"}, {"urgency": "URGENT"}, {"issue_category": "UNKNOWN"},
    {"aspects": [{"name": "delivery", "sentiment": "UNKNOWN"}]},
    {"aspects": [{"name": "Not snake case", "sentiment": "NEGATIVE"}]},
    {"summary": ""}, {"evidence_phrases": ["invented quotation"]},
])
def test_invalid_classifications_and_invented_evidence(updates):
    with pytest.raises(ValidationError):
        SentimentResponse.model_validate(analysis("source", **updates), context={"feedback_text": "source"})


def test_bounds_and_multiple_aspects():
    request = SentimentRequest(text="x" * 5000)
    result = SentimentResponse.model_validate(analysis(request.text, aspects=[
        {"name": "food", "sentiment": "POSITIVE"}, {"name": "delivery", "sentiment": "NEGATIVE"},
    ]), context={"feedback_text": request.text})
    assert len(result.aspects) == 2
