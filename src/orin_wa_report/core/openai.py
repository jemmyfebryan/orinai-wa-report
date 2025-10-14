import os
import json
from typing import List

from dotenv import load_dotenv

from openai import AsyncOpenAI
from openai.types.chat import ChatCompletionMessageParam

load_dotenv(override=True)

def create_client():
    openai_client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    return openai_client


async def chat_completion(
    openai_client: AsyncOpenAI,
    user_prompt: str | List[ChatCompletionMessageParam],
    system_prompt: str = None,
    formatted_schema: dict = None,
    model_name = "gpt-4.1-nano"
) -> str | dict:
    """
        Fast chat completion implementation, just use client, user prompt,
        and system prompt. You get the response.
        
        Args:
        openai_client: OpenAI Client, can be created with create_client() function
        user_prompt: User prompt string, or just use chat completion's messages
        system_prompt: System prompt string
        formatted_schema: Using this arg automatically uses formatted schema output
        model_name: Model used for the completion
    """
    
    messages = []
    # Messages Schema
    if system_prompt is None:
        if isinstance(user_prompt, str):
            messages.append(
                {
                    "role": "user",
                    "content": user_prompt
                }
            )
        else:
            messages = user_prompt
    else:
        messages.append(
            {
                "role": "system",
                "content": system_prompt
            }
        )
        if isinstance(user_prompt, str):
            messages.append(
                {
                    "role": "user",
                    "content": user_prompt
                }
            )
        else:
            messages.extend(user_prompt)

    # Is Response using Formatted Schema?
    if formatted_schema is None:
        completions = await openai_client.chat.completions.create(
            model=model_name,
            messages=messages,
            temperature=0
        )
        completions_result: str = completions.choices[0].message.content
    else:
        completions = await openai_client.chat.completions.create(
            model=model_name,
            messages=messages,
            response_format={
                "type": "json_schema",
                "json_schema": formatted_schema
            },
            temperature=0
        )
        completions_result: dict = json.loads(completions.choices[0].message.content)
    return completions_result