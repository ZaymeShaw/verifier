from impl.core.show_schema import ShowSchema

SHOW_SCHEMA = ShowSchema(input_fields=["input.messages[-1].content"], output_fields=["reply_text", "stage", "tool_calls", "errors"])
