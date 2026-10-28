"""从项目根目录运行 python backend/scripts/try_match.py；需先启动后端。"""

import json
from pathlib import Path

import httpx

fixture = Path(__file__).resolve().parents[1] / "fixtures" / "parsed.json"
payload = json.loads(fixture.read_text(encoding="utf-8"))

response = httpx.post("http://127.0.0.1:8000/api/match", json=payload, timeout=40)
print(response.status_code)
print(json.dumps(response.json(), ensure_ascii=False, indent=2))
