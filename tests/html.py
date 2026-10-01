import re


def visible_text(fragment: str) -> str:
    """Text a reader sees in an HTML fragment: SVGs and tags dropped, whitespace collapsed."""
    text = re.sub(r"<svg.*?</svg>", "", fragment, flags=re.DOTALL)
    return " ".join(re.sub(r"<[^>]+>", " ", text).split())


def h1_texts(html: str) -> list[str]:
    """Visible text of every <h1>."""
    return [visible_text(m) for m in re.findall(r"<h1\b[^>]*>(.*?)</h1>", html, re.DOTALL)]


_OPENING_TAG = re.compile(r"""<[^\s>/]+(?:\s+[^\s=>]+(?:="[^"]*"|='[^']*'|=[^\s>]+)?)*\s*/?>""")


def tag(html: str, marker: str) -> str:
    """The opening tag that contains `marker` (e.g. 'id="list"'), quoted `>` included."""
    i = html.index(marker)
    start = html.rindex("<", 0, i + 1)
    m = _OPENING_TAG.match(html, start)
    assert m is not None, f"no opening tag at {marker!r}"
    assert m.end() > i, f"{marker!r} is not inside an opening tag"
    return m.group(0)


def classes(opening_tag: str) -> set[str]:
    """The class tokens of an opening tag."""
    m = re.search(r'\bclass="([^"]*)"', opening_tag)
    return set(m.group(1).split()) if m else set()
