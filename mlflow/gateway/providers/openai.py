import concurrent.futures
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import AsyncIterable, List

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.catalog import FunctionParameterInfo
from fastapi import HTTPException

from mlflow.exceptions import MlflowException
from mlflow.gateway.config import OpenAIAPIType, OpenAIConfig, RouteConfig
from mlflow.gateway.providers.base import BaseProvider
from mlflow.gateway.providers.utils import send_request, send_stream_request
from mlflow.gateway.schemas import chat, completions, embeddings
from mlflow.gateway.utils import handle_incomplete_chunks, strip_sse_prefix
from mlflow.utils.uri import append_to_uri_path, append_to_uri_query_params


def transform_type(type_text: str) -> str:
    return {
        "boolean": "boolean",
        "byte": "number",
        "short": "number",
        "int": "number",
        "long": "number",
        "float": "number",
        "double": "number",
        "date": "string",
        "timestamp": "string",
        "timestamp_ntz": "string",
        "string": "string",
        "binary": "string",
        "decimal": "string",
        "interval": "string",
        # TODO: Support complex types
        # "array": "array",
        # "struct": "object",
        # "table": ???
    }.get(type_text, "string")


def extract_param_metadata(p: FunctionParameterInfo) -> dict:
    return {
        "type": transform_type(p.type_text),
        "description": p.comment
        + (f" (default: {p.parameter_default})" if p.parameter_default else ""),
    }


def get_func(name):
    w = WorkspaceClient()
    func = w.functions.get(name=name)
    return {
        "description": func.comment,
        "name": name.replace(".", "__")[-64:],
        "parameters": {
            "type": "object",
            "properties": {p.name: extract_param_metadata(p) for p in func.input_params.parameters},
            "required": [
                p.name for p in func.input_params.parameters if p.parameter_default is None
            ],
        },
    }, Args(
        required=[p.name for p in func.input_params.parameters if p.parameter_default is None],
        optional=[p.name for p in func.input_params.parameters if p.parameter_default],
    )


@dataclass
class Args:
    required: List[str]
    optional: List[str]


def run_func(name: str, args: Args, kwargs, timeout=60):
    import sqlalchemy as sa
    from sqlalchemy.orm import Session

    host = os.getenv("DATABRICKS_SERVER_HOSTNAME")
    http_path = os.getenv("DATABRICKS_HTTP_PATH")
    access_token = os.getenv("DATABRICKS_TOKEN")

    extra_connect_args = {
        "_tls_verify_hostname": True,
        "_user_agent_entry": "Test",
    }

    engine = sa.create_engine(
        f"databricks://token:{access_token}@{host}?http_path={http_path}",
        connect_args=extra_connect_args,
        echo=True,
    )

    def job():
        nonlocal args

        with Session(engine) as session:
            with session.begin():
                # Python UDFs don't support named arguments yet.
                # We can use named arguments for all arguments once it's supported.
                required = [f":{k}" for k in args.required]
                optional = [f"{k} => :{k}" for k in args.optional if k in kwargs]
                args = ", ".join(required + optional)
                sql = sa.text(f"{name}({args})").bindparams(**kwargs)
                return session.query(sql).scalar()

    with ThreadPoolExecutor(max_workers=1) as executor:
        try:
            res = executor.submit(job).result(timeout=timeout)
        except concurrent.futures.TimeoutError:
            raise HTTPException(status_code=408, detail=f"Function '{name}' timed out")
        else:
            return res


def join_uc_functions(hosted_func_calls):
    calls = [
        f"""
<uc_function_call>
{json.dumps(request, indent=2)}
</uc_function_call>

<uc_function_result>
{json.dumps(result, indent=2)}
</uc_function_result>
""".strip()
        for (request, result) in hosted_func_calls
    ]
    return "\n\n".join(calls)


_REGEX = re.compile(
    r"""
<uc_function_call>
(?P<uc_function_call>.*?)
</uc_function_call>

<uc_function_result>
(?P<uc_function_result>.*?)
</uc_function_result>
""",
    re.DOTALL,
)


def parse_uc_functions(content):
    tool_calls = []
    tool_messages = []
    for m in _REGEX.finditer(content):
        c = m.group("uc_function_call")
        g = m.group("uc_function_result")

        tool_calls.append(json.loads(c))
        tool_messages.append(json.loads(g))

    return tool_calls, tool_messages, _REGEX.sub("", content).rstrip()


@dataclass
class TokenUsageAccumulator:
    prompt_tokens: int = 0
    completions_tokens: int = 0
    total_tokens: int = 0

    def update(self, usage_dict):
        self.prompt_tokens += usage_dict.get("prompt_tokens", 0)
        self.completions_tokens += usage_dict.get("completion_tokens", 0)
        self.total_tokens += usage_dict.get("total_tokens", 0)


def prepend_host_functions(content, hosted_func_calls):
    return join_uc_functions(hosted_func_calls) + "\n\n" + content


class OpenAIProvider(BaseProvider):
    NAME = "OpenAI"

    def __init__(self, config: RouteConfig) -> None:
        super().__init__(config)
        if config.model.config is None or not isinstance(config.model.config, OpenAIConfig):
            # Should be unreachable
            raise MlflowException.invalid_parameter_value(
                "Invalid config type {config.model.config}"
            )
        self.openai_config: OpenAIConfig = config.model.config

    @property
    def _request_base_url(self):
        api_type = self.openai_config.openai_api_type
        if api_type == OpenAIAPIType.OPENAI:
            base_url = self.openai_config.openai_api_base or "https://api.openai.com/v1"
            if api_version := self.openai_config.openai_api_version is not None:
                return append_to_uri_query_params(base_url, ("api-version", api_version))
            else:
                return base_url
        elif api_type in (OpenAIAPIType.AZURE, OpenAIAPIType.AZUREAD):
            openai_url = append_to_uri_path(
                self.openai_config.openai_api_base,
                "openai",
                "deployments",
                self.openai_config.openai_deployment_name,
            )
            return append_to_uri_query_params(
                openai_url,
                ("api-version", self.openai_config.openai_api_version),
            )
        else:
            raise MlflowException.invalid_parameter_value(
                f"Invalid OpenAI API type '{self.openai_config.openai_api_type}'"
            )

    @property
    def _request_headers(self):
        api_type = self.openai_config.openai_api_type
        if api_type == OpenAIAPIType.OPENAI:
            headers = {
                "Authorization": f"Bearer {self.openai_config.openai_api_key}",
            }
            if org := self.openai_config.openai_organization:
                headers["OpenAI-Organization"] = org
            return headers
        elif api_type == OpenAIAPIType.AZUREAD:
            return {
                "Authorization": f"Bearer {self.openai_config.openai_api_key}",
            }
        elif api_type == OpenAIAPIType.AZURE:
            return {
                "api-key": self.openai_config.openai_api_key,
            }
        else:
            raise MlflowException.invalid_parameter_value(
                f"Invalid OpenAI API type '{self.openai_config.openai_api_type}'"
            )

    def _add_model_to_payload_if_necessary(self, payload):
        # NB: For Azure OpenAI, the deployment name (which is included in the URL) specifies
        # the model; it is not specified in the payload. For OpenAI outside of Azure, the
        # model is always specified in the payload
        if self.openai_config.openai_api_type not in (OpenAIAPIType.AZURE, OpenAIAPIType.AZUREAD):
            return {"model": self.config.model.name, **payload}
        else:
            return payload

    async def chat_stream(
        self, payload: chat.RequestPayload
    ) -> AsyncIterable[chat.StreamResponsePayload]:
        from fastapi.encoders import jsonable_encoder

        payload = jsonable_encoder(payload, exclude_none=True)
        self.check_for_model_field(payload)

        stream = send_stream_request(
            headers=self._request_headers,
            base_url=self._request_base_url,
            path="chat/completions",
            payload=self._add_model_to_payload_if_necessary(payload),
        )

        async for chunk in handle_incomplete_chunks(stream):
            chunk = chunk.strip()
            if not chunk:
                continue

            data = strip_sse_prefix(chunk.decode("utf-8"))
            if data == "[DONE]":
                return

            resp = json.loads(data)
            yield chat.StreamResponsePayload(
                id=resp["id"],
                object=resp["object"],
                created=resp["created"],
                model=resp["model"],
                choices=[
                    chat.StreamChoice(
                        index=c["index"],
                        finish_reason=c["finish_reason"],
                        delta=chat.StreamDelta(
                            role=c["delta"].get("role"), content=c["delta"].get("content")
                        ),
                    )
                    for c in resp["choices"]
                ],
            )

    async def chat(self, payload: chat.RequestPayload) -> chat.ResponsePayload:
        from fastapi.encoders import jsonable_encoder

        print("-" * 30)

        payload = jsonable_encoder(payload, exclude_none=True)
        self.check_for_model_field(payload)

        user_msg = payload["messages"][0]["content"]

        token_usage_accumulator = TokenUsageAccumulator()
        tool_calls, tool_messages, parsed = parse_uc_functions(payload["messages"][0]["content"])
        if tool_calls:
            user_tool_messages = [m for m in payload["messages"] if m["role"] == "tool"]
            user_tool_calls = next(m for m in payload["messages"] if "tool_calls" in m).get(
                "tool_calls"
            )
            messages = [
                {
                    "role": "user",
                    "content": parsed,
                },
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": tool_calls + user_tool_calls,
                },
                *tool_messages,
                *user_tool_messages,
            ]
            resp = await send_request(
                headers=self._request_headers,
                base_url=self._request_base_url,
                path="chat/completions",
                payload=self._add_model_to_payload_if_necessary(
                    {
                        **payload,
                        "messages": messages,
                    }
                ),
            )

        elif any(t["type"] == "uc_function" for t in payload.get("tools", [])):
            updated_tools = []
            hosted_func_mapping = {}
            for tool in payload.get("tools", []):
                if tool["type"] == "uc_function":
                    data, args = get_func(tool["uc_function"]["name"])
                    t = {
                        "type": "function",
                        "function": data,
                    }
                    hosted_func_mapping[t["function"]["name"]] = (
                        tool["uc_function"]["name"],
                        args,
                    )
                    updated_tools.append(t)
                    continue
                else:
                    updated_tools.append(tool)

            payload["tools"] = updated_tools

            messages = payload.pop("messages")
            hosted_func_calls = []
            user_tool_calls = []
            resp = None
            should_break = False
            for _ in range(20):
                if should_break:
                    if hosted_func_calls:
                        resp["choices"][0]["message"]["content"] = (
                            user_msg + "\n\n" + join_uc_functions(hosted_func_calls)
                        )

                    if user_tool_calls:
                        resp["choices"][0]["message"]["tool_calls"] = user_tool_calls
                    break

                resp = await send_request(
                    headers=self._request_headers,
                    base_url=self._request_base_url,
                    path="chat/completions",
                    payload=self._add_model_to_payload_if_necessary(
                        {
                            **payload,
                            "messages": messages,
                        }
                    ),
                )
                token_usage_accumulator.update(resp.get("usage", {}))
                # TODO to support n > 1.
                assistant_msg = resp["choices"][0]["message"]
                tool_calls = assistant_msg.get("tool_calls")
                if tool_calls is None:
                    if hosted_func_calls:
                        resp["choices"][0]["message"]["content"] = prepend_host_functions(
                            resp["choices"][0]["message"]["content"], hosted_func_calls
                        )

                    if user_tool_calls:
                        resp["choices"][0]["message"]["tool_calls"] = user_tool_calls

                    break

                tool_messages = []
                for tool_call in tool_calls:  # TODO: should run in parallel
                    func = tool_call["function"]
                    kwargs = json.loads(func["arguments"])
                    if v := hosted_func_mapping.get(func["name"]):
                        (name, args) = v
                        result = run_func(name, args, kwargs)
                        tool_message = {
                            "role": "tool",
                            "tool_call_id": tool_call["id"],
                            "content": str(result),
                        }
                        tool_messages.append(tool_message)

                    if func["name"] in hosted_func_mapping:
                        hosted_func_calls.append(
                            (
                                {
                                    "id": tool_call["id"],
                                    "type": "function",
                                    "function": {
                                        "name": func["name"],
                                        "arguments": func["arguments"],
                                    },
                                },
                                {
                                    "role": "tool",
                                    "tool_call_id": tool_call["id"],
                                    "content": str(result),
                                },
                            )
                        )
                    else:
                        should_break = True
                        user_tool_calls.append(
                            {
                                "id": tool_call["id"],
                                "type": "function",
                                "function": {
                                    "name": func["name"],
                                    "arguments": func["arguments"],
                                },
                            }
                        )
                print(assistant_msg)

                if message_content := assistant_msg.pop("content", None):
                    messages.append({"role": "assistant", "content": message_content})
                assistant_msg.pop("function_call", None)
                messages += [assistant_msg, *tool_messages]
            else:
                raise MlflowException("Max iterations reached")

        else:
            resp = await send_request(
                headers=self._request_headers,
                base_url=self._request_base_url,
                path="chat/completions",
                payload=self._add_model_to_payload_if_necessary(payload),
            )
        # Response example (https://platform.openai.com/docs/api-reference/chat/create)
        # ```
        # {
        #    "id":"chatcmpl-abc123",
        #    "object":"chat.completion",
        #    "created":1677858242,
        #    "model":"gpt-3.5-turbo-0301",
        #    "usage":{
        #       "prompt_tokens":13,
        #       "completion_tokens":7,
        #       "total_tokens":20
        #    },
        #    "choices":[
        #       {
        #          "message":{
        #             "role":"assistant",
        #             "content":"\n\nThis is a test!"
        #          },
        #          "finish_reason":"stop",
        #          "index":0
        #       }
        #    ]
        # }
        # ```
        return chat.ResponsePayload(
            id=resp["id"],
            object=resp["object"],
            created=resp["created"],
            model=resp["model"],
            choices=[
                chat.Choice(
                    index=idx,
                    message=chat.ResponseMessage(
                        role=c["message"]["role"],
                        content=c["message"].get("content"),
                        tool_calls=[
                            chat.ToolCall(**tc) for tc in c["message"].get("tool_calls", [])
                        ],
                    ),
                    finish_reason=c["finish_reason"],
                )
                for idx, c in enumerate(resp["choices"])
            ],
            usage=chat.ChatUsage(
                prompt_tokens=resp["usage"]["prompt_tokens"],
                completion_tokens=resp["usage"]["completion_tokens"],
                total_tokens=resp["usage"]["total_tokens"],
            ),
        )

    def _prepare_completion_request_payload(self, payload):
        payload["messages"] = [{"role": "user", "content": payload.pop("prompt")}]
        return payload

    def _prepare_completion_response_payload(self, resp):
        return completions.ResponsePayload(
            id=resp["id"],
            # The chat models response from OpenAI is of object type "chat.completion". Since
            # we're using the completions response format here, we hardcode the "text_completion"
            # object type in the response instead
            object="text_completion",
            created=resp["created"],
            model=resp["model"],
            choices=[
                completions.Choice(
                    index=idx,
                    text=c["message"]["content"],
                    finish_reason=c["finish_reason"],
                )
                for idx, c in enumerate(resp["choices"])
            ],
            usage=completions.CompletionsUsage(
                prompt_tokens=resp["usage"]["prompt_tokens"],
                completion_tokens=resp["usage"]["completion_tokens"],
                total_tokens=resp["usage"]["total_tokens"],
            ),
        )

    async def completions_stream(
        self, payload: completions.RequestPayload
    ) -> AsyncIterable[completions.StreamResponsePayload]:
        from fastapi.encoders import jsonable_encoder

        payload = jsonable_encoder(payload, exclude_none=True)
        self.check_for_model_field(payload)
        payload = self._prepare_completion_request_payload(payload)

        stream = send_stream_request(
            headers=self._request_headers,
            base_url=self._request_base_url,
            path="chat/completions",
            payload=self._add_model_to_payload_if_necessary(payload),
        )

        async for chunk in handle_incomplete_chunks(stream):
            chunk = chunk.strip()
            if not chunk:
                continue

            data = strip_sse_prefix(chunk.decode("utf-8"))
            if data == "[DONE]":
                return

            resp = json.loads(data)
            yield completions.StreamResponsePayload(
                id=resp["id"],
                # The chat models response from OpenAI is of object type "chat.completion.chunk".
                # Since we're using the completions response format here, we hardcode the
                # "text_completion_chunk" object type in the response instead
                object="text_completion_chunk",
                created=resp["created"],
                model=resp["model"],
                choices=[
                    completions.StreamChoice(
                        index=c["index"],
                        finish_reason=c["finish_reason"],
                        delta=completions.StreamDelta(
                            content=c["delta"].get("content"),
                        ),
                    )
                    for c in resp["choices"]
                ],
            )

    async def completions(self, payload: completions.RequestPayload) -> completions.ResponsePayload:
        from fastapi.encoders import jsonable_encoder

        payload = jsonable_encoder(payload, exclude_none=True)
        self.check_for_model_field(payload)
        payload = self._prepare_completion_request_payload(payload)

        resp = await send_request(
            headers=self._request_headers,
            base_url=self._request_base_url,
            path="chat/completions",
            payload=self._add_model_to_payload_if_necessary(payload),
        )
        # Response example (https://platform.openai.com/docs/api-reference/completions/create)
        # ```
        # {
        #   "id": "cmpl-uqkvlQyYK7bGYrRHQ0eXlWi7",
        #   "object": "text_completion",
        #   "created": 1589478378,
        #   "model": "text-davinci-003",
        #   "choices": [
        #     {
        #       "text": "\n\nThis is indeed a test",
        #       "index": 0,
        #       "logprobs": null,
        #       "finish_reason": "length"
        #     }
        #   ],
        #   "usage": {
        #     "prompt_tokens": 5,
        #     "completion_tokens": 7,
        #     "total_tokens": 12
        #   }
        # }
        # ```
        return self._prepare_completion_response_payload(resp)

    async def embeddings(self, payload: embeddings.RequestPayload) -> embeddings.ResponsePayload:
        from fastapi.encoders import jsonable_encoder

        payload = jsonable_encoder(payload, exclude_none=True)
        self.check_for_model_field(payload)
        resp = await send_request(
            headers=self._request_headers,
            base_url=self._request_base_url,
            path="embeddings",
            payload=self._add_model_to_payload_if_necessary(payload),
        )
        # Response example (https://platform.openai.com/docs/api-reference/embeddings/create):
        # ```
        # {
        #   "object": "list",
        #   "data": [
        #     {
        #       "object": "embedding",
        #       "embedding": [
        #         0.0023064255,
        #         -0.009327292,
        #         .... (1536 floats total for ada-002)
        #         -0.0028842222,
        #       ],
        #       "index": 0
        #     }
        #   ],
        #   "model": "text-embedding-ada-002",
        #   "usage": {
        #     "prompt_tokens": 8,
        #     "total_tokens": 8
        #   }
        # }
        # ```
        return embeddings.ResponsePayload(
            data=[
                embeddings.EmbeddingObject(
                    embedding=d["embedding"],
                    index=idx,
                )
                for idx, d in enumerate(resp["data"])
            ],
            model=resp["model"],
            usage=embeddings.EmbeddingsUsage(
                prompt_tokens=resp["usage"]["prompt_tokens"],
                total_tokens=resp["usage"]["total_tokens"],
            ),
        )
