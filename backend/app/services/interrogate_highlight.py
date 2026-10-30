from __future__ import annotations

from html import escape

from app.contracts.interrogate import RiskItem


def render_highlighted(raw_text: str, risks: list[RiskItem]) -> str:
    """收集所有的需要标红片段"""
    valid: list[tuple[int, int, int, RiskItem]] = []
    for index, risk in enumerate(risks, start=1):
        start = max(0, risk.start)
        end = min(len(raw_text), risk.end)
        if start < end:
            valid.append((start, end, index, risk))

    if not valid:
        return escape(raw_text).replace("\n", "<br>")

    cuts = {0, len(raw_text)}
    for start, end, _index, _risk in valid:
        cuts.add(start)
        cuts.add(end)
    ordered = sorted(cuts)


    parts: list[str] = []
    for left, right in zip(ordered, ordered[1:]):
        segment = escape(raw_text[left:right]) #escape用来转义，不被当成html
        hits = [
            (index, risk)
            for start, end, index, risk in valid
            if start <= left and right <= end
        ]
        # 如果有标红片段的处理
        if hits:
            labels = "".join(f"<sup>{index}</sup>" for index, _risk in hits)
            title = escape(
                "；".join(
                    f"#{index} {risk.type}：{risk.reason}"
                    for index, risk in hits
                )
            )
            segment = (
                f'<span title="{title}" '
                f'style="background:#ffe0e0;border-bottom:2px solid #e05252">'
                f"{segment}{labels}</span>"
            )
        parts.append(segment)

    return "".join(parts).replace("\n", "<br>")
