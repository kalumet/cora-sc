"""Keep Wingman's chat contract while using Responses for GPT-6 models."""

import re
from copy import deepcopy

from openai.types.chat import ChatCompletion, ChatCompletionChunk, ChatCompletionMessage
from pydantic import PrivateAttr


class ResponsesMessage(ChatCompletionMessage):
    # Retain native output (including encrypted reasoning) in local history only.
    _responses_output: list[dict] = PrivateAttr(default_factory=list)


def _as_dict(value):
    return value if isinstance(value, dict) else value.model_dump(exclude_none=True)


def _responses_input(messages):
    items = []
    for message in messages:
        native_output = getattr(message, "_responses_output", None)
        if native_output:
            items.extend(deepcopy(native_output))
            continue
        message = _as_dict(message)
        role = message["role"]
        if role == "tool":
            items.append({
                "type": "function_call_output",
                "call_id": message["tool_call_id"],
                "output": message.get("content") or "",
            })
            continue
        content = message.get("content")
        if content is not None:
            if isinstance(content, list):
                converted = []
                for part in content:
                    if part["type"] == "text":
                        converted.append({"type": "input_text", "text": part["text"]})
                    elif part["type"] == "image_url":
                        image = part["image_url"]
                        converted.append({
                            "type": "input_image", "image_url": image["url"],
                            "detail": image.get("detail", "auto"),
                        })
                    else:
                        raise ValueError(f"Unsupported Responses content type: {part['type']}")
                content = converted
            items.append({"role": role, "content": content})
        for call in message.get("tool_calls") or []:
            call = _as_dict(call)
            function = _as_dict(call["function"])
            items.append({
                "type": "function_call", "call_id": call["id"],
                "name": function["name"], "arguments": function["arguments"],
            })
    return items


def _chat_completion(response):
    if response.status == "failed":
        raise RuntimeError(f"Responses request failed: {response.error}")
    output = [_as_dict(item) for item in response.output]
    tool_calls = []
    text = []
    refusals = []
    for item in output:
        if item["type"] == "function_call":
            tool_calls.append({
                "id": item["call_id"], "type": "function",
                "function": {"name": item["name"], "arguments": item["arguments"]},
            })
        elif item["type"] == "message":
            for part in item.get("content", []):
                if part["type"] == "output_text":
                    text.append(part["text"])
                elif part["type"] == "refusal":
                    refusals.append(part["refusal"])
    message = ResponsesMessage(
        role="assistant", content="".join(text) or None,
        tool_calls=tool_calls or None, refusal="".join(refusals) or None,
    )
    message._responses_output = deepcopy(output)
    finish_reason = "tool_calls" if tool_calls else "stop"
    if response.status == "incomplete":
        details = _as_dict(response.incomplete_details) if response.incomplete_details else {}
        finish_reason = "length" if details.get("reason") == "max_output_tokens" else "content_filter"
    usage = None
    if response.usage is not None:
        raw_usage = _as_dict(response.usage)
        usage = {
            "prompt_tokens": raw_usage["input_tokens"],
            "completion_tokens": raw_usage["output_tokens"],
            "total_tokens": raw_usage["total_tokens"],
        }
        if raw_usage.get("input_tokens_details"):
            usage["prompt_tokens_details"] = raw_usage["input_tokens_details"]
        if raw_usage.get("output_tokens_details"):
            usage["completion_tokens_details"] = raw_usage["output_tokens_details"]
    return ChatCompletion(
        id=response.id, created=int(response.created_at), model=response.model,
        object="chat.completion", usage=usage,
        choices=[{"index": 0, "message": message, "finish_reason": finish_reason}],
    )


def _buffered_chat_stream(events):
    """Adapt a completed Responses stream to Wingman's chat chunk contract."""
    with events:
        for event in events:
            if event.type in {"response.completed", "response.incomplete"}:
                completion = _chat_completion(event.response)
                choice = completion.choices[0]
                delta = choice.message.model_dump(exclude_none=True)
                for index, call in enumerate(delta.get("tool_calls", [])):
                    call["index"] = index
                yield ChatCompletionChunk(
                    id=completion.id, created=completion.created, model=completion.model,
                    object="chat.completion.chunk", usage=completion.usage,
                    choices=[{"index": 0, "delta": delta, "finish_reason": choice.finish_reason}],
                )
            elif event.type in {"error", "response.failed"}:
                raise RuntimeError(f"Responses stream failed: {event}")


def create_chat_completion(client, **kwargs):
    """Select the endpoint and return the chat shape consumed by existing callers."""
    if not re.match(r"^gpt-6(?:[.-]|$)", kwargs.get("model", "")):
        return client.chat.completions.create(**kwargs)

    request = {
        "model": kwargs["model"],
        "input": _responses_input(kwargs["messages"]),
        "store": False,
        "include": ["reasoning.encrypted_content"],
        "stream": kwargs.get("stream", False),
    }
    effort = kwargs.get("reasoning_effort")
    if effort:
        request["reasoning"] = {"effort": effort}
    # GPT-6 defaults to reasoning. Sampling parameters are valid only at none.
    if effort == "none":
        for name in ("temperature", "top_p", "top_logprobs"):
            if kwargs.get(name) is not None:
                request[name] = kwargs[name]
    max_tokens = kwargs.get("max_completion_tokens", kwargs.get("max_tokens"))
    if max_tokens is not None:
        request["max_output_tokens"] = max_tokens
    response_format = kwargs.get("response_format")
    if response_format:
        if response_format["type"] == "json_schema":
            response_format = {"type": "json_schema", **response_format["json_schema"]}
        request["text"] = {"format": response_format}
    if kwargs.get("tools"):
        request["tools"] = [
            {"type": "function", **tool["function"], "strict": tool["function"].get("strict", False)}
            for tool in kwargs["tools"]
        ]
        request["tool_choice"] = kwargs.get("tool_choice", "auto")
    response = client.responses.create(**request)
    return _buffered_chat_stream(response) if request["stream"] else _chat_completion(response)
