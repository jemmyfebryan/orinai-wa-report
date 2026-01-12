from typing import List, Dict
import copy
import os
from dotenv import load_dotenv
from openai import AsyncOpenAI
from openai.types.chat import ChatCompletionMessageParam

from src.orin_wa_report.core.openai import chat_completion
from src.orin_wa_report.core.agent.formatted_schemas import (
    get_question_class_formatted_schema,
    chat_filter_formatted_schema,
    split_messages_formatted_schema,
)
from src.orin_wa_report.core.agent.prompts import (
    QUESTION_CLASS_SYSTEM_PROMPT,
    CHAT_FILTER_SYSTEM_PROMPT,
    SPLIT_MESSAGES_SYSTEM_PROMPT,
    SPLIT_MESSAGES_USER_PROMPT,
)
from src.orin_wa_report.core.db import (
    get_settings_db
)
from src.orin_wa_report.core.utils import log_data

from src.orin_wa_report.core.logger import get_logger

logger = get_logger(__name__, service="LLM")

load_dotenv()

VERSION = os.getenv("VERSION")

async def get_question_class(
    openai_client: AsyncOpenAI,
    messages: List[ChatCompletionMessageParam],
    question_class_details: Dict[str, Dict],
    # Reccuring
    depth: int = 1,
) -> List[str]:
    question_classes_list = list(question_class_details.keys())
    question_classes_description = {
        key: value["description"] for key, value in question_class_details.items()
    }
    
    question_class_llm_result: Dict = await chat_completion(
        openai_client=openai_client,
        user_prompt=messages,
        system_prompt=QUESTION_CLASS_SYSTEM_PROMPT.format(
            question_classes_list=question_classes_list,
            question_classes_description=question_classes_description
        ),
        formatted_schema=get_question_class_formatted_schema(
            question_classes_list=question_classes_list
        ),
        model_name="gpt-4.1",
    )
    
    question_class_result: List[str] = [question_class_llm_result.get("question_class", "")]
    
    logger.info(f"Question Class at depth {depth}: {question_class_result[0]}")
    
    # Check if the class has subclass
    question_class_dict = question_class_details.get(question_class_result[0])

    is_class_has_subclass = "subclass" in question_class_dict.keys()
    if is_class_has_subclass:
        question_class_result = question_class_result + await get_question_class(
            openai_client=openai_client,
            messages=messages,
            question_class_details=question_class_dict.get("subclass"),
            depth=depth+1
        )
        
    return question_class_result

async def chat_filter(
    openai_client: AsyncOpenAI,
    messages: List[ChatCompletionMessageParam],
    model_name: str = "gpt-4.1-mini",
    log_data_path: str = f"./src/orin_wa_report/core/database/jsonl/chat_filters_{VERSION}.jsonl",
) -> bool:
    db = await get_settings_db()
    
    chat_filter_instruction, chat_filter_questions = await db.get_chat_filter_setting()
    
    chat_filter_result: Dict = await chat_completion(
        openai_client=openai_client,
        user_prompt=f"""
Messages:\n\n{messages}"        
""",
        system_prompt=CHAT_FILTER_SYSTEM_PROMPT.format(
            chat_filter_instruction=chat_filter_instruction,
            chat_filter_questions=chat_filter_questions,
        ),
        formatted_schema=chat_filter_formatted_schema(),
        model_name=model_name,
    )
    
    if log_data_path:
        log_data_dict = copy.deepcopy(chat_filter_result)
        log_data_dict["messages"] = messages
        log_data_dict["model_name"] = model_name
        await log_data(
            file_name=log_data_path,
            data_dict=log_data_dict
        )
    
    return chat_filter_result
    
async def split_messages(
    openai_client: AsyncOpenAI,
    all_replies: List,
    chat_filter_is_report: bool,
) -> List[str]:
    """
    From all the replies, conclude message and split it to
    multiple messages to be send to user.
    
    :param openai_client: OpenAI Client Object
    :type openai_client: AsyncOpenAI
    :param all_replies: List of all replies
    :type all_replies: List
    """
    
    all_replies_formatted = "\n\n".join(all_replies)
    
    if chat_filter_is_report:
        extra_instructions = "-Tambahkan pesan untuk memberitahu bahwa customer/user bisa melihat report lebih detail pada file excel yang dikirim"
        
        all_replies_formatted += ("\n\n [Excel File Sent]")
    else:
        extra_instructions = ""
    
    split_messages_result: Dict = await chat_completion(
        openai_client=openai_client,
        user_prompt=SPLIT_MESSAGES_USER_PROMPT.format(all_replies=all_replies_formatted),
        system_prompt=SPLIT_MESSAGES_SYSTEM_PROMPT.format(
            extra_instructions=extra_instructions
        ),
        formatted_schema=split_messages_formatted_schema(),
        model_name="gpt-4.1-mini",
    )
    
    return split_messages_result.get("split_messages_result")