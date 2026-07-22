# Mock Dataset Boundary Normalization

## Problem

The summary frontend intentionally loads Mock datasets with one
`/api/mock_datasets` request so dynamic projects do not invoke MockAgent twice.
The endpoint currently places raw dataset dictionaries inside the declared
`MockDatasetsResponse`, so nested cases bypass `parse_mock_case()`. Public
serialization can then omit nullable `output` and `reference`, and the frontend
rejects the result as an incomplete VNext MockCase.

## Design

Keep generation and fixture loading unchanged. At the server response boundary,
convert each pipeline dataset to the existing `MockDataset` dataclass and each
nested case through the existing `parse_mock_case()` function. Compute
`case_count` from the converted cases.

This preserves one and only one `pipeline.mock_datasets()` call, changes no
MockCase schema, and leaves pipeline/CLI/Draft consumers on their current dict
contract.

## Verification

- A service-level test requires every nested case to serialize with all seven
  VNext fields, including nullable `output` and `reference`.
- Existing count-forwarding tests continue to prove one pipeline invocation.
- API and browser checks verify one `/api/mock_datasets` request populates the
  case pool without a console protocol error.

