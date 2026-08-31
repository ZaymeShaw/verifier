# E1 Draft Catalog consumption (not selected)

Draft Judge now consumes a registry-driven Catalog of field_definitions,
enhanced_rules, value_mappings, and abbrname enums via Search→Load.

This note is investigation evidence only:

- Manifest `decision.status` is unchanged; no candidate is claimed `selected`.
- Production Judge is not promoted.
- Embedding is an additional Catalog channel on text collections
  (field_definitions, enhanced_rules) when Bailian/Authority infra is supplied.
  abbr/mappings keep embedding `rejected`. Default search still covers every
  registered index; embedding does not choose an index by query shape.
- Frozen CollectionSpec `embedding.min_cosine=0.58` (experiment t55/t58 band).
  Do not lower this to 0.50 in Judge core: that cutoff recalled unsupported
  hobby paraphrases onto insurance-intent fields in the field Key-Index
  experiment.
- Exact equality + query-internal rewrite remain; no business reject lexicon
  and no query-shape index routing in Judge Catalog core.
- SearchHit is not Evidence; Load is required.
