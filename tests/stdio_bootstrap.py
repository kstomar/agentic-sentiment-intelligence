"""Verification-only child process: run the production stdio entry point offline."""

import runpy
import socket

import httpx

import app.agents.action_selector as selectors
import app.services.sentiment_service as sentiments
from app.agents.action_selector import ActionSelector
from app.services.sentiment_service import SentimentService
from tests.helpers import Model,SelectionModel


def deny(*args,**kwargs):
    raise AssertionError("No network during MCP subprocess QA")


async def deny_async(*args,**kwargs):
    deny()


socket.socket.connect=deny
socket.socket.connect_ex=deny
socket.getaddrinfo=deny
httpx.HTTPTransport.handle_request=deny
httpx.AsyncHTTPTransport.handle_async_request=deny_async
sentiments.create_sentiment_service=lambda *a,**kw:SentimentService(Model(),max_retries=0)
selectors.create_action_selector=lambda *a,**kw:ActionSelector(SelectionModel())

if __name__=="__main__":
    runpy.run_module("app.mcp_server.server",run_name="__main__")
