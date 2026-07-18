from impl.core.show_schema import ShowSchema

SHOW_SCHEMA = ShowSchema(input_fields=["user_text"], output_fields=["robot_text", "stage", "card_summary", "session_summary", "errors"])
