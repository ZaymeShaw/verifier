from typing import Any, Dict
from agno.utils.json_schema import get_json_schema
import logging
logging.disable(logging.CRITICAL)

# Test 1: Dict[str, Any] - current (broken)
def f1(params: Dict[str, Any]) -> Any: pass
from typing import get_type_hints
th1 = get_type_hints(f1)
s1 = get_json_schema({k:v for k,v in th1.items() if k != 'return'})
print("Dict[str, Any] params:", s1)

# Test 2: plain dict
def f2(params: dict) -> dict: pass
th2 = get_type_hints(f2)
s2 = get_json_schema({k:v for k,v in th2.items() if k != 'return'})
print("plain dict params:", s2)

# Test 3: concrete string params
def f3(query: str) -> str: pass
th3 = get_type_hints(f3)
s3 = get_json_schema({k:v for k,v in th3.items() if k != 'return'})
print("str params:", s3)
