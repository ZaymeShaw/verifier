from impl.core.show_schema import ShowSchema

SHOW_SCHEMA = ShowSchema(input_fields=["user_text"], output_fields=["intent", "confidence", "target_value", "path_types"])
