"""Product identity. Versions are four numeric parts: major.minor.patch.build."""

import re

PRODUCT = "OKEDBMON"
VERSION = "1.0.0.0"
LEGACY_TITLES = {"SpaceMon", "Spacemon", "SPACEMON", "OKEMON"}

VERSION_PATTERN = re.compile(r"^\d+\.\d+\.\d+\.\d+$")


def require_version(value: str) -> str:
    text = str(value).strip()
    if VERSION_PATTERN.fullmatch(text) is None:
        raise ValueError("버전은 #.#.#.# 네 자리여야 합니다. 예: 1.0.0.0")
    return text


def display_name(title: str = PRODUCT, version: str = VERSION) -> str:
    return f"{title} V{version}"
