import json
import re
from dataclasses import dataclass
from io import StringIO
from typing import TYPE_CHECKING, Any, AsyncIterable, Dict, List, Literal, Optional, Union

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.catalog import FunctionParameterInfo

from mlflow.environment_variables import MLFLOW_ENABLE_UC_FUNCTIONS
from mlflow.exceptions import MlflowException
from mlflow.gateway.config import OpenAIAPIType, OpenAIConfig, RouteConfig
from mlflow.gateway.providers.base import BaseProvider
from mlflow.gateway.providers.utils import send_request, send_stream_request
from mlflow.gateway.schemas import chat, completions, embeddings
from mlflow.gateway.utils import handle_incomplete_chunks, strip_sse_prefix
from mlflow.utils.uri import append_to_uri_path, append_to_uri_query_params

if TYPE_CHECKING:
    from databricks.sdk import WorkspaceClient
    from databricks.sdk.service.catalog import FunctionInfo
    from databricks.sdk.service.sql import StatementParameterListItem


def uc_type_to_json_schema_type(uc_type_json: Union[str, Dict[str, Any]]) -> Dict[str, Any]:
    """
    Converts the JSON representation of a Unity Catalog data type to the corresponding JSON schema
    type. The conversion is lossy because we do not need to convert it back.
    """
    # See https://docs.databricks.com/en/sql/language-manual/sql-ref-datatypes.html
    # The actual type name in type_json is different from the corresponding SQL type name.
    mapping = {
        "long": {"type": "integer"},
        "binary": {"type": "string"},
        "boolean": {"type": "boolean"},
        "date": {"type": "string", "format": "date"},
        "double": {"type": "number"},
        "float": {"type": "number"},
        "integer": {"type": "integer"},
        "void": {"type": "null"},
        "short": {"type": "integer"},
        "string": {"type": "string"},
        "timestamp": {"type": "string", "format": "date-time"},
        "timestamp_ntz": {"type": "string", "format": "date-time"},
        "byte": {"type": "integer"},
    }
    if isinstance(uc_type_json, str):
        if uc_type_json in mapping:
            return mapping[uc_type_json]
        else:
            if uc_type_json.startswith("decimal"):
                return {"type": "number"}
            elif uc_type_json.startswith("interval"):
                raise TypeError(f"Type {uc_type_json} is not supported.")
            else:
                raise TypeError(f"Unknown type {uc_type_json}. Try upgrading this package.")
    else:
        assert isinstance(uc_type_json, dict)
        type = uc_type_json["type"]
        if type == "array":
            element_type = uc_type_to_json_schema_type(uc_type_json["elementType"])
            return {"type": "array", "items": element_type}
        elif type == "map":
            key_type = uc_type_json["keyType"]
            assert key_type == "string", TypeError(
                f"Only support STRING key type for MAP but got {key_type}."
            )
            value_type = uc_type_to_json_schema_type(uc_type_json["valueType"])
            return {
                "type": "object",
                "additionalProperties": value_type,
            }
        elif type == "struct":
            properties = {}
            for field in uc_type_json["fields"]:
                properties[field["name"]] = uc_type_to_json_schema_type(field["type"])
            return {"type": "object", "properties": properties}
        else:
            raise TypeError(f"Unknown type {uc_type_json}. Try upgrading this package.")


def extract_param_metadata(p: FunctionParameterInfo) -> dict:
    type_json = json.loads(p.type_json)["type"]
    json_schema_type = uc_type_to_json_schema_type(type_json)
    json_schema_type["name"] = p.name
    json_schema_type["description"] = (
        p.comment + f" (default: {p.parameter_default})" if p.parameter_default else ""
    )
    return json_schema_type


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


@dataclass
class ParameterizedStatement:
    statement: str
    parameters: List["StatementParameterListItem"]


@dataclass
class FunctionExecutionResult:
    """
    Result of executing a function.
    We always use a string to present the result value for AI model to consume.
    """

    error: Optional[str] = None
    format: Optional[Literal["SCALAR", "CSV"]] = None
    value: Optional[str] = None
    truncated: Optional[bool] = None

    def to_json(self) -> str:
        data = {k: v for (k, v) in self.__dict__.items() if v is not None}
        return json.dumps(data)


def is_scalar(function: "FunctionInfo") -> bool:
    from databricks.sdk.service.catalog import ColumnTypeName

    return function.data_type != ColumnTypeName.TABLE_TYPE


def get_execute_function_sql_stmt(
    function: "FunctionInfo", json_params: Dict[str, Any]
) -> ParameterizedStatement:
    from databricks.sdk.service.catalog import ColumnTypeName
    from databricks.sdk.service.sql import StatementParameterListItem

    parts = []
    output_params = []
    if is_scalar(function):
        # TODO: IDENTIFIER(:function) did not work
        parts.append(f"SELECT {function.full_name}(")
    else:
        parts.append(f"SELECT * FROM {function.full_name}(")
    if function.input_params is None or function.input_params.parameters is None:
        assert not json_params, "Function has no parameters but parameters were provided."
    else:
        args = []
        use_named_args = False
        for p in function.input_params.parameters:
            if p.name not in json_params:
                if p.parameter_default is not None:
                    use_named_args = True
                else:
                    raise ValueError(f"Parameter {p.name} is required but not provided.")
            else:
                arg_clause = ""
                if use_named_args:
                    arg_clause += f"{p.name} => "
                json_value = json_params[p.name]
                if p.type_name in (
                    ColumnTypeName.ARRAY,
                    ColumnTypeName.MAP,
                    ColumnTypeName.STRUCT,
                ):
                    # Use from_json to restore values of complex types.
                    json_value_str = json.dumps(json_value)
                    # TODO: parametrize type
                    arg_clause += f"from_json(:{p.name}, '{p.type_text}')"
                    output_params.append(
                        StatementParameterListItem(name=p.name, value=json_value_str)
                    )
                elif p.type_name == ColumnTypeName.BINARY:
                    # Use ubbase64 to restore binary values.
                    arg_clause += f"unbase64(:{p.name})"
                    output_params.append(StatementParameterListItem(name=p.name, value=json_value))
                else:
                    arg_clause += f":{p.name}"
                    output_params.append(
                        StatementParameterListItem(name=p.name, value=json_value, type=p.type_text)
                    )
                args.append(arg_clause)
        parts.append(",".join(args))
    parts.append(")")
    # TODO: check extra params in kwargs
    statement = "".join(parts)
    return ParameterizedStatement(statement=statement, parameters=output_params)


def execute_function(
    ws: "WorkspaceClient",
    warehouse_id: str,
    function: "FunctionInfo",
    parameters: Dict[str, Any],
) -> FunctionExecutionResult:
    """
    Execute a function with the given arguments and return the result.
    """
    try:
        import pandas as pd
    except ImportError as e:
        raise ImportError(
            "Could not import pandas python package. "
            "Please install it with `pip install pandas`."
        ) from e
    from databricks.sdk.service.sql import StatementState

    # TODO: async so we can run functions in parallel
    parametrized_statement = get_execute_function_sql_stmt(function, parameters)
    # TODO: configurable limits
    response = ws.statement_execution.execute_statement(
        statement=parametrized_statement.statement,
        warehouse_id=warehouse_id,
        parameters=parametrized_statement.parameters,
        wait_timeout="30s",
        row_limit=100,
        byte_limit=4096,
    )
    status = response.status
    assert status is not None, f"Statement execution failed: {response}"
    if status.state != StatementState.SUCCEEDED:
        error = status.error
        assert error is not None, "Statement execution failed but no error message was provided."
        return FunctionExecutionResult(error=f"{error.error_code}: {error.message}")
    manifest = response.manifest
    assert manifest is not None
    truncated = manifest.truncated
    result = response.result
    assert result is not None, "Statement execution succeeded but no result was provided."
    data_array = result.data_array
    if is_scalar(function):
        value = None
        if data_array and len(data_array) > 0 and len(data_array[0]) > 0:
            value = str(data_array[0][0])  # type: ignore
        return FunctionExecutionResult(format="SCALAR", value=value, truncated=truncated)
    else:
        schema = manifest.schema
        assert (
            schema is not None and schema.columns is not None
        ), "Statement execution succeeded but no schema was provided."
        columns = [c.name for c in schema.columns]
        if data_array is None:
            data_array = []
        pdf = pd.DataFrame.from_records(data_array, columns=columns)
        csv_buffer = StringIO()
        pdf.to_csv(csv_buffer, index=False)
        return FunctionExecutionResult(
            format="CSV", value=csv_buffer.getvalue(), truncated=truncated
        )


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

    async def _chat(self, payload: chat.RequestPayload) -> chat.ResponsePayload:
        from fastapi.encoders import jsonable_encoder

        payload = jsonable_encoder(payload, exclude_none=True)
        self.check_for_model_field(payload)

        return await send_request(
            headers=self._request_headers,
            base_url=self._request_base_url,
            path="chat/completions",
            payload=self._add_model_to_payload_if_necessary(payload),
        )

    async def _chat_uc_function(self, payload: chat.RequestPayload) -> chat.ResponsePayload:
        from fastapi.encoders import jsonable_encoder

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
                        result = execute_function(name, args, kwargs)
                        if result.value is not None:
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
        return resp

    async def chat(self, payload: chat.RequestPayload) -> chat.ResponsePayload:
        if MLFLOW_ENABLE_UC_FUNCTIONS.get():
            resp = await self._chat_uc_function(payload)
        else:
            resp = await self._chat(payload)

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
