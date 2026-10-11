import pytest

from app.schemas.chat import ChatResponse


async def test_chat_analysis_workflow_c_reuses_t01_once(api):
    _,client,h=api
    response=await client.post("/api/v1/chat",json={"mode":"ANALYZE_TEXT","message":"Analyze","feedback_text":"only-this"})
    result=ChatResponse.model_validate(response.json())
    assert response.status_code==200 and result.sentiment_analysis is not None and result.investigation is None
    assert len(h.model.calls)==1 and not h.selector.calls
    assert result.answer.startswith("The feedback is classified as negative")


async def test_chat_investigation_workflow_d_preserves_findings(api):
    _,client,h=api
    response=await client.post("/api/v1/chat",json={"mode":"INVESTIGATE_FEEDBACK","message":"Summary?","feedback":[{"id":"A","text":"only-this"}]})
    result=ChatResponse.model_validate(response.json())
    assert response.status_code==200 and result.investigation is not None and result.sentiment_analysis is None
    assert result.answer==result.investigation.answer and result.investigation.total_feedback==1
    assert len(h.model.calls)==len(h.selector.calls)==1


@pytest.mark.parametrize("payload", [
    {}, {"mode":"unknown","message":"q"}, {"mode":"ANALYZE_TEXT","feedback_text":"x"},
    {"mode":"ANALYZE_TEXT","message":"","feedback_text":"x"},
    {"mode":"ANALYZE_TEXT","message":"x"*501,"feedback_text":"x"},
    {"mode":"ANALYZE_TEXT","message":"q"}, {"mode":"INVESTIGATE_FEEDBACK","message":"q"},
    {"mode":"ANALYZE_TEXT","message":"q","feedback_text":"x","feedback":[{"id":"A","text":"x"}]},
    {"mode":"INVESTIGATE_FEEDBACK","message":"q","feedback":[{"id":str(i),"text":"x"}for i in range(11)]},
    {"mode":"ANALYZE_TEXT","message":"q","feedback_text":"x","history":[]},
])
async def test_chat_cross_field_and_history_validation(api,payload):
    _,client,h=api
    response=await client.post("/api/v1/chat",json=payload)
    assert response.status_code==422 and not h.model.calls and not h.selector.calls


async def test_chat_has_no_cross_request_memory(api):
    _,client,h=api
    for text in ["first-only","second-only"]:
        response=await client.post("/api/v1/chat",json={"mode":"ANALYZE_TEXT","message":"Analyze","feedback_text":text})
        assert response.status_code==200 and response.json()["sentiment_analysis"]["evidence_phrases"]==[text]
    response=await client.post("/api/v1/chat",json={"mode":"ANALYZE_TEXT","message":"Use the previous review"})
    assert response.status_code==422 and [c["text"]for c in h.model.calls]==["first-only","second-only"]
