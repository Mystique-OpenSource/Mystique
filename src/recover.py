import json

from common import Language
from config import PLACE_HOLDER
from project import Method


def recover(target_before: str, target_slice_lines: set[int], recover_code: str) -> str | None:
    try:
        target_before_method = Method.init_from_code(target_before.strip(), Language.C)
    except Exception:
        return None
    result = target_before_method.recover_placeholder(recover_code, target_slice_lines, PLACE_HOLDER)
    return result


def recover_batch(data_path: str, info_path: str) -> None:
    with open(data_path) as f:
        data = json.load(f)
    with open(info_path) as f:
        info = json.load(f)

    for k, v in data.items():
        our_tool = v["our_tool"].strip()
        target_before = info[k]["target_before"]
        if "target_slice_lines" not in info[k]:
            continue
        target_slice_lines = set(info[k]["target_slice_lines"])
        result = recover(target_before, target_slice_lines, our_tool)
        if result is None:
            continue
        data[k]["our_tool_recover"] = result

    with open(data_path, "w") as f:
        json.dump(data, f, indent=4)
