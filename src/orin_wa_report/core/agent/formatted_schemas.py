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
                "chat_filter_result": {
                    "type": "boolean",
                },
                "confidence": {
                    "type": "number",
                    "description": "Range 0 to 1 float, confidence that the result is correct."
                }
            },
            "required": ["chat_filter_result", "confidence"],
            "additionalProperties": False
        }
    }