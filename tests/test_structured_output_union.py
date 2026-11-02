"""Static tagged unions and explicit nested non-empty fields of the structured-output mechanism.

The schema is generated from dataclasses by code only; the same code must always
produce the same schema, and existing (opt-out) specs must render exactly as before.
"""
import json
from dataclasses import dataclass, field
from typing import List, Literal, Optional, Union

import pytest

from impl.core.schema_validator import SchemaValidator
from impl.core.structured_output import StructuredOutputSpec, render_output_constraint


@dataclass
class Plain:
    kind: Literal['ok', 'bad']
    fact: str = field(metadata={'nonempty': True})


@dataclass
class Gap:
    kind: Literal['gap']
    fact: str
    missing: List[str] = field(metadata={'nonempty': True})


@dataclass
class Out:
    items: List[Union[Plain, Gap]] = field(default_factory=list)
    one: Optional[Union[Plain, Gap]] = None
    plain_list: List[str] = field(default_factory=list)


SPEC = StructuredOutputSpec.from_dataclass(Out)


def check(data):
    return SchemaValidator(SPEC).validate(data, strict=True, allow_extra=False)


def test_schema_is_a_static_anyof_of_refs_and_is_reproducible():
    schema = SPEC.json_schema()
    assert schema['properties']['items']['items'] == {'anyOf': [{'$ref': '#/$defs/Plain'}, {'$ref': '#/$defs/Gap'}]}
    assert schema['properties']['one'] == {'anyOf': [{'$ref': '#/$defs/Plain'}, {'$ref': '#/$defs/Gap'}, {'type': 'null'}]}
    assert schema['$defs']['Gap']['properties']['missing']['minItems'] == 1
    assert schema['$defs']['Plain']['properties']['fact'] == {'type': 'string', 'minLength': 1, 'pattern': r'\S'}
    again = StructuredOutputSpec.from_dataclass(Out).json_schema()
    assert json.dumps(schema, sort_keys=True) == json.dumps(again, sort_keys=True)


def test_prompt_states_the_branch_rule_only_when_there_is_a_real_choice():
    assert 'anyOf' in render_output_constraint(SPEC) and '只选一个分支' in render_output_constraint(SPEC)

    @dataclass
    class Nullable:
        item: Optional[Plain] = None
    assert '只选一个分支' not in render_output_constraint(StructuredOutputSpec.from_dataclass(Nullable))


def test_valid_branches_pass_and_each_branch_is_checked_by_its_own_fields():
    assert check({'items': [{'kind': 'ok', 'fact': 'x'}, {'kind': 'gap', 'fact': 'y', 'missing': ['缺']}]}) == []
    assert check({'one': None, 'items': []}) == []


@pytest.mark.parametrize('item,fragment', [
    ({'kind': 'gap', 'fact': 'y'}, '必填字段缺失：missing'),
    ({'kind': 'gap', 'fact': 'y', 'missing': []}, '字段必须非空但产出为空：missing'),
    ({'kind': 'ok', 'fact': ' \n '}, '字段必须非空但产出为空：fact'),
    ({'kind': 'ok', 'fact': 'x', 'missing': ['多余']}, '额外字段不允许：missing'),
    ({'kind': 'nope', 'fact': 'x'}, "期望 ['ok', 'bad', 'gap'] 之一"),
    ({'fact': 'x'}, "期望 ['ok', 'bad', 'gap'] 之一"),
])
def test_wrong_branch_shape_is_reported_with_the_item_path(item, fragment):
    errors = check({'items': [item]})
    assert any(e.startswith('items.[0].') and fragment in e for e in errors), errors


def test_non_object_items_and_optional_member_are_checked():
    assert any('期望 object' in e for e in check({'items': ['x']}))
    assert any(e.startswith('one.') and '必填字段缺失：missing' in e for e in check({'one': {'kind': 'gap', 'fact': 'x'}}))


def test_undeclared_fields_keep_their_old_behaviour():
    # No metadata -> empty list and blank text remain legal for plain fields.
    assert check({'plain_list': []}) == []


def test_branches_without_a_disjoint_literal_discriminator_fail_loudly_at_build_time():
    @dataclass
    class A:
        kind: Literal['x', 'y']

    @dataclass
    class B:
        kind: Literal['y']

    @dataclass
    class NoTag:
        name: str

    @dataclass
    class Overlap:
        v: Union[A, B]

    @dataclass
    class Untagged:
        v: Union[A, NoTag]

    for bad in (Overlap, Untagged):
        with pytest.raises(ValueError, match='找不到区分字段'):
            StructuredOutputSpec.from_dataclass(bad).json_schema()


def test_nonempty_only_applies_to_str_list_dict():
    @dataclass
    class Bad:
        n: int = field(default=0, metadata={'nonempty': True})
    with pytest.raises(ValueError, match='nonempty'):
        StructuredOutputSpec.from_dataclass(Bad).json_schema()


def test_declared_pattern_is_in_the_schema_and_enforced_at_every_level():
    @dataclass
    class Item:
        code: str = field(metadata={'pattern': r'^C[0-9]+$'})

    @dataclass
    class Box:
        items: List[Item] = field(default_factory=list)
        one: Optional[Item] = None

    spec = StructuredOutputSpec.from_dataclass(Box)
    assert spec.json_schema()['$defs']['Item']['properties']['code']['pattern'] == r'^C[0-9]+$'
    ok = SchemaValidator(spec).validate({'items': [{'code': 'C12'}], 'one': {'code': 'C1'}}, strict=True, allow_extra=False)
    assert ok == []
    bad = SchemaValidator(spec).validate({'items': [{'code': 'C1: expectation:x'}, {'code': 'obligation:a'}]}, strict=True, allow_extra=False)
    assert len(bad) == 2 and all('字段格式不符：code' in e and e.startswith('items.[') for e in bad)

    @dataclass
    class Bad:
        n: int = field(default=0, metadata={'pattern': 'x'})
    with pytest.raises(ValueError, match='pattern only applies to str'):
        StructuredOutputSpec.from_dataclass(Bad).json_schema()
