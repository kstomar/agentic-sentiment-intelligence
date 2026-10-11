import pytest

from app.agents.action_selector import ActionSelector
from app.core.exceptions import ApplicationError, ErrorCode as E
from tests.helpers import SelectionModel


@pytest.mark.parametrize("output", [None, {}, {"action": "run_shell", "category": None, "sentiment": None, "evidence_limit": 3},
    {"action": "SENTIMENT_OVERVIEW", "category": "DELIVERY", "sentiment": None, "evidence_limit": 3},
    {"action": "EVIDENCE_SEARCH", "category": None, "sentiment": None, "evidence_limit": 11}])
async def test_invalid_selector_outputs_fail_closed(output):
    model = SelectionModel(output=output if output is not None else "invalid")
    with pytest.raises(ApplicationError) as caught:
        await ActionSelector(model).select("question", "general")
    assert caught.value.code == E.INVALID_ACTION_SELECTION and len(model.calls) == 1


async def test_selector_receives_question_and_hint_only():
    model = SelectionModel()
    await ActionSelector(model).select("What complaints?", "ecommerce")
    assert model.calls == [{"question": "What complaints?", "business_type": "ecommerce"}]
