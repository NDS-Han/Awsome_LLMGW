# Copyright 2026 © Amazon.com and Affiliates: This deliverable is considered Developed Content as defined in the AWS Service Terms.

"""Lightweight OpenAI-compatible mock vLLM server for local development.

Supports:
- GET  /v1/models
- POST /v1/chat/completions  (stream=true/false)
- POST /v1/completions       (stream=true/false)

Echoes the incoming model id and returns deterministic token usage estimates.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import AsyncGenerator

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

app = FastAPI(title="mock-vllm")

DEFAULT_MODEL = os.environ.get("DEFAULT_MODEL", "meta-llama/Meta-Llama-3-70B-Instruct")
MOCK_CONTENT = "Hello! This is a mock response from the local vLLM-compatible server."


def _estimate_tokens(text: str) -> int:
    """Very rough token estimator for cost/usage bookkeeping."""
    return max(1, len(text) // 4)


def _now() -> int:
    return int(time.time())


def _usage_from_messages(messages: list[dict], completion_text: str) -> dict:
    prompt_text = " ".join(str(m.get("content", "")) for m in messages)
    prompt_tokens = _estimate_tokens(prompt_text)
    completion_tokens = _estimate_tokens(completion_text)
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
    }


@app.get("/v1/models")
async def list_models() -> dict:
    return {
        "object": "list",
        "data": [
            {
                "id": DEFAULT_MODEL,
                "object": "model",
                "created": _now(),
                "owned_by": "mock-vllm",
            }
        ],
    }


@app.get("/v1/models/{model_id:path}")
async def get_model(model_id: str) -> JSONResponse:
    if model_id != DEFAULT_MODEL:
        return JSONResponse(
            status_code=404,
            content={"object": "error", "message": f"Model '{model_id}' not found"},
        )
    return JSONResponse(
        content={
            "id": DEFAULT_MODEL,
            "object": "model",
            "created": _now(),
            "owned_by": "mock-vllm",
        }
    )


async def _stream_chat_completion(model: str, messages: list[dict]) -> AsyncGenerator[str, None]:
    created = _now()
    completion_id = f"chatcmpl-mock-{created}"
    usage = _usage_from_messages(messages, MOCK_CONTENT)
    prompt_tokens = usage["prompt_tokens"]
    completion_tokens = usage["completion_tokens"]
    total_tokens = usage["total_tokens"]

    # First chunk: role delta
    yield f"data: {json.dumps({'id': completion_id, 'object': 'chat.completion.chunk', 'created': created, 'model': model, 'choices': [{'index': 0, 'delta': {'role': 'assistant'}, 'finish_reason': None}]})}\n\n"

    # Content chunks
    for word in MOCK_CONTENT.split():
        yield f"data: {json.dumps({'id': completion_id, 'object': 'chat.completion.chunk', 'created': created, 'model': model, 'choices': [{'index': 0, 'delta': {'content': word + ' '}, 'finish_reason': None}]})}\n\n"

    # Final usage chunk (required by OpenModelAdapter stream_options.include_usage=true)
    yield f"data: {json.dumps({'id': completion_id, 'object': 'chat.completion.chunk', 'created': created, 'model': model, 'choices': [], 'usage': {'prompt_tokens': prompt_tokens, 'completion_tokens': completion_tokens, 'total_tokens': total_tokens}})}\n\n"

    yield "data: [DONE]\n\n"


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    body = await request.json()
    model = body.get("model") or DEFAULT_MODEL
    messages = body.get("messages", [])
    stream = bool(body.get("stream", False))

    if stream:
        return StreamingResponse(
            _stream_chat_completion(model, messages),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache"},
        )

    usage = _usage_from_messages(messages, MOCK_CONTENT)
    return JSONResponse(
        content={
            "id": f"chatcmpl-mock-{_now()}",
            "object": "chat.completion",
            "created": _now(),
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": MOCK_CONTENT},
                    "finish_reason": "stop",
                }
            ],
            "usage": usage,
        }
    )


async def _stream_completion(model: str, prompt: str) -> AsyncGenerator[str, None]:
    created = _now()
    completion_id = f"cmpl-mock-{created}"
    prompt_tokens = _estimate_tokens(str(prompt))
    completion_tokens = _estimate_tokens(MOCK_CONTENT)

    for word in MOCK_CONTENT.split():
        yield f"data: {json.dumps({'id': completion_id, 'object': 'text_completion', 'created': created, 'model': model, 'choices': [{'index': 0, 'text': word + ' ', 'finish_reason': None}]})}\n\n"

    yield f"data: {json.dumps({'id': completion_id, 'object': 'text_completion', 'created': created, 'model': model, 'choices': [], 'usage': {'prompt_tokens': prompt_tokens, 'completion_tokens': completion_tokens, 'total_tokens': prompt_tokens + completion_tokens}})}\n\n"
    yield "data: [DONE]\n\n"


@app.post("/v1/completions")
async def completions(request: Request):
    body = await request.json()
    model = body.get("model") or DEFAULT_MODEL
    prompt = body.get("prompt", "")
    stream = bool(body.get("stream", False))

    if stream:
        return StreamingResponse(
            _stream_completion(model, prompt),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache"},
        )

    usage = _usage_from_messages([{"content": str(prompt)}], MOCK_CONTENT)
    return JSONResponse(
        content={
            "id": f"cmpl-mock-{_now()}",
            "object": "text_completion",
            "created": _now(),
            "model": model,
            "choices": [{"index": 0, "text": MOCK_CONTENT, "finish_reason": "stop"}],
            "usage": usage,
        }
    )


@app.get("/health")
@app.get("/v1/health")
async def health() -> dict:
    return {"status": "ok"}
