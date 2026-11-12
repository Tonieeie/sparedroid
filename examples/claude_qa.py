"""AI customer service: answer questions with Claude, grounded in your own knowledge file.

    pip install "wecomdroid[ai]"          # or: pip install anthropic
    WECOMDROID_HANDLER=examples.claude_qa:handle
    ANTHROPIC_API_KEY=sk-ant-...
    WECOMDROID_KNOWLEDGE=examples/knowledge.example.md   (your FAQ / product docs, plain text or Markdown)
    WECOMDROID_AI_MODEL=claude-opus-5-5                  (optional)

How it stays safe for a customer-facing group:

* The whole knowledge file goes into a cached system prompt, and the model is told
  to answer only from it - if the answer isn't there, it hands off to a human
  instead of inventing prices or policies.
* Server-side refusal fallback is on, so a rare safety decline is retried on a
  fallback model instead of leaving the customer with nothing.
* Any API error turns into a polite "a colleague will follow up", never a stack trace.

For a big knowledge base, swap the "whole file in the prompt" approach for retrieval
(embed + search, then pass only the top passages); the handler shape stays the same.
"""

import logging
import os
from functools import lru_cache
from pathlib import Path

import anthropic

from wecomdroid import Message

log = logging.getLogger("wecomdroid.claude_qa")

HANDOFF = "这个问题我需要请同事确认一下，稍后回复你 🙏"

SYSTEM = """你是一个企业微信群里的客服助手，帮客户解答问题。

只根据下面 <knowledge> 里的资料回答。资料里没有的内容（尤其是价格、优惠、时间、承诺），
不要猜，直接回复「HANDOFF」这一个词，系统会转给人工。

回复要求：
- 中文，口语化、友善，可以用一个表情
- 简短：一般 1–3 句，最多 120 字
- 不要用 Markdown 标题、表格或代码块（企业微信里显示不出来）
- 不要提到你是 AI、模型或"资料"本身

<knowledge>
{knowledge}
</knowledge>"""


@lru_cache(maxsize=1)
def _client() -> anthropic.Anthropic:
    return anthropic.Anthropic()


def _knowledge() -> str:
    path = Path(os.environ.get("WECOMDROID_KNOWLEDGE", Path(__file__).with_name("knowledge.example.md")))
    return path.read_text(encoding="utf-8")


def handle(msg: Message, bot) -> str | None:
    question = msg.body.strip()
    if not question:
        return "有什么可以帮你的？@我 + 你的问题就好～"
    try:
        response = _client().beta.messages.create(
            model=os.environ.get("WECOMDROID_AI_MODEL", "claude-opus-5-5"),
            max_tokens=1024,
            # Group-chat Q&A doesn't need deep reasoning; low effort keeps replies fast and cheap.
            output_config={"effort": "low"},
            system=[{
                "type": "text",
                "text": SYSTEM.format(knowledge=_knowledge()),
                # The knowledge file is the same on every question: cache it.
                "cache_control": {"type": "ephemeral"},
            }],
            messages=[{"role": "user", "content": f"{msg.sender} 问：{question}"}],
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
    except anthropic.RateLimitError:
        log.warning("Claude rate limited")
        return HANDOFF
    except anthropic.APIStatusError as e:
        log.warning("Claude API error %s: %s", e.status_code, e.message)
        return HANDOFF
    except anthropic.APIConnectionError:
        log.warning("cannot reach the Claude API")
        return HANDOFF

    if response.stop_reason == "refusal":
        return HANDOFF
    answer = "".join(b.text for b in response.content if b.type == "text").strip()
    if not answer or "HANDOFF" in answer:
        # Tell the team someone needs a human; the customer gets a polite holding reply.
        bot.alert(f"**WeComDroid**: 「{msg.chat}」 里 {msg.sender} 的问题需要人工：{question[:200]}")
        return HANDOFF
    return answer
