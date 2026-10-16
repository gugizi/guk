"""Product identity. Versions are four numeric parts: major.minor.patch.build."""

PRODUCT = "OKEMON"
VERSION = "1.0.0.0"

import re

VERSION_PATTERN = re.compile(r"^\d+\.\d+\.\d+\.\d+$")


def require_version(value: str) -> str:
    text = str(value).strip()
    if VERSION_PATTERN.fullmatch(text) is None:
        raise ValueError("버전은 #.#.#.# 네 자리여야 합니다. 예: 1.0.0.0")
    return text
