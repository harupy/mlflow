from pydantic import BaseModel, Field
from typing import List, Optional, Union, Dict


# https://platform.openai.com/docs/api-reference/completions/create (2023-0607)


class Message(BaseModel):
    role: str = Field(
        ...,
        description="The role of the author of this message. One of system, user, or assistant.",
    )
    content: str = Field(
        ...,
        description="The contents of the message.",
    )
    name: Optional[str] = Field(
        None,
        description=(
            "The name of the author of this message. May contain a-z, A-Z, 0-9, "
            "and underscores, with a maximum length of 64 characters."
        ),
    )


class RequestBody(BaseModel):
    model: str = Field(..., description="ID of the model to use.")
    messages: List[Message] = Field(
        ...,
        description="A list of messages describing the conversation so far.",
    )
    temperature: Optional[float] = Field(
        None,
        description="What sampling temperature to use, between 0 and 2.",
    )
    top_p: Optional[float] = Field(
        None,
        description="An alternative to sampling with temperature, called nucleus sampling.",
    )
    n: Optional[int] = Field(
        None,
        description="How many chat completion choices to generate for each input message.",
    )
    stream: Optional[bool] = Field(None, description="If set, partial message deltas will be sent.")
    stop: Optional[Union[str, List[str]]] = Field(
        None,
        description="Up to 4 sequences where the API will stop generating further tokens.",
    )
    max_tokens: Optional[int] = Field(
        None,
        description="The maximum number of tokens to generate in the chat completion.",
    )
    presence_penalty: Optional[float] = Field(
        None,
        description=(
            "Number between -2.0 and 2.0. Positive values penalize "
            "new tokens based on whether they appear in the text so far.",
        ),
    )
    frequency_penalty: Optional[float] = Field(
        None,
        description=(
            "Number between -2.0 and 2.0. Positive values penalize "
            "new tokens based on their existing frequency in the text so far."
        ),
    )
    logit_bias: Optional[Dict[int, float]] = Field(
        None, description="Modify the likelihood of specified tokens appearing in the completion."
    )
    user: Optional[str] = Field(None, description="A unique identifier representing your end-user.")


class Choice(BaseModel):
    index: int = Field(..., description="Index of the chat completion choice.")
    message: Message = Field(
        ..., description="Message object associated with the chat completion choice."
    )
    finish_reason: str = Field(
        ..., description="Reason the chat completion finished. Typically 'stop'."
    )


class Usage(BaseModel):
    prompt_tokens: int = Field(
        ...,
        description="Number of tokens in the prompt.",
    )
    completion_tokens: int = Field(
        ...,
        description="Number of tokens in the completion.",
    )
    total_tokens: int = Field(
        ...,
        description="Total number of tokens in the request.",
    )


class ChatResponse(BaseModel):
    id: str = Field(
        ...,
        description="ID of the chat completion.",
    )
    object: str = Field(
        ...,
        description="Type of the object, typically 'chat.completion'.",
    )
    created: int = Field(
        ...,
        description="Timestamp when the chat completion was created.",
    )
    choices: List[Choice] = Field(
        ...,
        description="List of chat completion choices.",
    )
    usage: Usage = Field(
        ...,
        description="Usage details about the tokens.",
    )
