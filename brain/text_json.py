import json
from typing import Any, Iterator


def iter_json_objects(text: str) -> Iterator[Any]:
    decoder = json.JSONDecoder()
    index = 0
    length = len(text)
    while index < length:
        start = text.find("{", index)
        if start < 0:
            return
        try:
            value, end = decoder.raw_decode(text[start:])
        except json.JSONDecodeError:
            index = start + 1
            continue
        yield value
        index = start + end