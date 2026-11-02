from impl.core.show_schema import ShowSchema

SHOW_SCHEMA = ShowSchema(
    input_fields=["url", "method", "headers", "capability_ref", "capability", "show_schema", "body"],
    output_fields=["output_text"],
)
