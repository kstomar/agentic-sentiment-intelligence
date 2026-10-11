import pytest

from app.schemas.investigation import InvestigationResponse


async def test_investigation_rest_workflow_b(api):
    app, client, h = api
    response = await client.post("/api/v1/agent/investigate", json={"question":"Main issues?", "feedback":[
        {"id":"A", "text":"late"}, {"id":"B", "text":"damaged"}]})
    assert response.status_code == 200
    result = InvestigationResponse.model_validate(response.json())
    assert result.total_feedback == 2 and result.sentiment_summary.NEGATIVE == 2
    assert result.top_issues[0].feedback_ids == ["A","B"]
    assert app.state.investigation_service is h.investigation and len(h.selector.calls)==1


@pytest.mark.parametrize("updates", [
    {"question":""}, {"question":"x"*501}, {"feedback":[]},
    {"feedback":[{"id":str(i),"text":"x"}for i in range(11)]},
    {"feedback":[{"id":"A","text":"a"},{"id":"A","text":"b"}]},
    {"feedback":[{"id":"A","text":""}]}, {"feedback":[{"id":"A","text":"x"*5001}]},
    {"business_type":"unknown"},
])
async def test_invalid_investigation_inputs(api, updates):
    _, client, h = api
    payload={"question":"q","feedback":[{"id":"A","text":"x"}]} | updates
    response=await client.post("/api/v1/agent/investigate",json=payload)
    assert response.status_code==422 and not h.selector.calls and not h.model.calls
