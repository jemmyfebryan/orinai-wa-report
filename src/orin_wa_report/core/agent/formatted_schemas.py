def get_question_class_formatted_schema(question_classes_list):
    return {
        "name": "question_class",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "question_class": {
                    "type": "string",
                    "enum": question_classes_list
                }
            },
            "required": ["question_class"],
            "additionalProperties": False
        }
    }
    
def chat_filter_formatted_schema():
    return {
        "name": "chat_filter_result",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "is_processed": {
                    "type": "boolean",
                },
                "is_report": {
                    "type": "boolean"
                },
                "confidence": {
                    "type": "number",
                    "description": "Range 0 to 1 float, confidence that the result is correct."
                }
            },
            "required": ["is_processed", "is_report", "confidence"],
            "additionalProperties": False
        }
    }
    
  
def split_messages_formatted_schema():
    return {
        "name": "split_messages_result",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "split_messages_result": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "description": "Bagian pesan terurut"
                    }
                }
            },
            "required": ["split_messages_result"],
            "additionalProperties": False
        }
    }