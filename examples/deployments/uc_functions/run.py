"""
# Set environment variables
export DATABRICKS_HOST="..."
export DATABRICKS_SERVER_HOSTNAME="..."
export DATABRICKS_HTTP_PATH="..."
export DATABRICKS_TOKEN="..."
export DATABRICKS_CATALOG="..."
export DATABRICKS_SCHEMA="..."
export OPENAI_API_KEY="..."

# Run server
mlflow deployments start-server \
    --config-path examples/deployments/deployments_server/openai/config.yaml --port 7000

# Run client
python examples/deployments/uc_functions/run.py
"""

import openai

client = openai.OpenAI(base_url="http://localhost:7000/v1")

req = {
    "messages": [
        {
            "role": "user",
            "content": (
                "I opened a bank account on 2024/01/05 and I have to keep my deposit there "
                "for 90 days to qualify a bonus. When can I withdraw the money?"
            ),
        }
    ],
}

# Without tools
print("--- Without tools ---")
resp = client.chat.completions.create(
    model="chat",
    **req,
)
print(resp.choices[0].message.content)

# With tools
print("--- With tools ---")
resp = client.chat.completions.create(
    model="chat",
    **req,
    tools=[
        {
            "type": "uc_function",  # type: ignore
            "uc_function": {
                "name": "ml.haru.add",
            },
        }
    ],
)
print(resp.choices[0].message.content)

hosted_funcs = [
    {
        "type": "uc_function",  # type: ignore
        "uc_function": {
            "name": "ml.haru.add",
        },
    }
]

user_funcs = [
    {
        "type": "function",
        "function": {
            "description": "Multiply numbers",
            "name": "multiply",
            "parameters": {
                "type": "object",
                "properties": {
                    "x": {
                        "type": "integer",
                        "description": "First number",
                    },
                    "y": {
                        "type": "integer",
                        "description": "Second number",
                    },
                },
                "required": ["x", "y"],
            },
        },
    }
]
print("--- With tools ---")
resp = client.chat.completions.create(
    model="chat",
    messages=[
        {
            "role": "user",
            "content": "What is the result of 1 + 2?",
        }
    ],
    tools=[
        *hosted_funcs,
    ],
)
print(resp.choices[0].message.content)

print("--- With hosted + user-defined tools ---")
resp = client.chat.completions.create(
    model="chat",
    messages=[
        {
            "role": "user",
            "content": "What is the result of 1 + 2? What is the result of 3 * 4?",
        }
    ],
    tools=[
        *hosted_funcs,
        *user_funcs,
    ],
)
print(resp.choices[0].message.content)
print(resp.choices[0].message.tool_calls)

resp = client.chat.completions.create(
    model="chat",
    messages=[
        {
            "role": "assistant",
            "content": resp.choices[0].message.content,
        },
        {
            "role": "assistant",
            "content": "",
            "tool_calls": resp.choices[0].message.tool_calls,
        },
        {
            "role": "tool",
            "tool_call_id": resp.choices[0].message.tool_calls[0].id,
            "content": "12",
        },
    ],
)

print(resp.choices[0].message.content)
