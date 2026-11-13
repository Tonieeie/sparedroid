"""Keyword FAQ: answer common questions from a JSON file. No AI, no cost, fully predictable.

    SPAREDROID_HANDLER=examples.keyword_faq:handle
    SPAREDROID_FAQ=examples/faq.example.json     (optional, this is the default)

The JSON is a list of {"keywords": [...], "answer": "..."}. The first entry whose
keyword appears in the message wins. Edit the file and the next message picks it up.
"""

import json
import os
from pathlib import Path

from sparedroid import Message

FALLBACK = "这个问题我还答不上来，已经帮你记下了，同事稍后回复你～"


def _faq() -> list[dict]:
    path = Path(os.environ.get("SPAREDROID_FAQ", Path(__file__).with_name("faq.example.json")))
    return json.loads(path.read_text(encoding="utf-8"))


def handle(msg: Message, bot) -> str:
    text = msg.body.lower()
    for entry in _faq():
        if any(k.lower() in text for k in entry["keywords"]):
            return entry["answer"]
    return FALLBACK
