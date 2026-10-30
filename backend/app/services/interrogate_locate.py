from __future__ import annotations


def locate_span(
    raw_text: str, text: str, hint_start: int | None = None
) -> tuple[int, int] | None:
    """返回 text 在 raw_text 中的 (start, end)。

    优先相信规则层给出的 hint_start；不一致时退回全文查找。
    找不到返回 None，由调用方跳过该风险。
    """
    if not text:
        return None

    if (
        hint_start is not None
        and 0 <= hint_start <= len(raw_text) - len(text)
        and raw_text.startswith(text, hint_start)
    ):
        return hint_start, hint_start + len(text)

    pos = raw_text.find(text)
    if pos == -1:
        return None
    return pos, pos + len(text)
