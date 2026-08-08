"""
Dreamer AI Phase 2.3 — Session Wrap

7-turn friendly session-end wrap messages.
Trilingual: en / zh-hk / zh-cn.
Includes topic progress summary placeholder.
"""

from typing import List, Optional
from dataclasses import dataclass, field

# ── Constants ──────────────────────────────────────────

SESSION_WRAP_TURN = 7  # Trigger wrap on 7th turn
EN = "en"
ZH_HK = "zh-hk"
ZH_CN = "zh-cn"


@dataclass
class TopicSummary:
    """A single topic's progress summary for the wrap message."""
    topic: str
    label_key: str  # "not_yet" | "developing" | "achieved" | "exemplary"


@dataclass
class SessionState:
    """Track session turns and topics for wrap generation."""
    turns: int = 0
    topics: List[TopicSummary] = field(default_factory=list)
    lang_code: str = EN

    def increment(self) -> None:
        self.turns += 1

    def add_topic(self, topic: str, label_key: str) -> None:
        self.topics.append(TopicSummary(topic=topic, label_key=label_key))

    def should_wrap(self) -> bool:
        return self.turns >= SESSION_WRAP_TURN


# ── Wrap message templates ─────────────────────────────

_TEMPLATES = {
    EN: {
        "header": "That's all for today's session — great work!",
        "topic_intro": "Here's a quick look at what we covered:",
        "topic_line": "  {topic}: {label}",
        "footer": "Keep exploring and see you next time!",
        "no_topics": "We had a great chat today. Come back soon!",
    },
    ZH_HK: {
        "header": "今日嘅學習環節完結喇，你做得好好！",
        "topic_intro": "以下係今日學過嘅內容：",
        "topic_line": "  {topic}：{label}",
        "footer": "繼續探索，下次再見！",
        "no_topics": "今日傾得好開心，下次再嚟！",
    },
    ZH_CN: {
        "header": "今天的学习环节结束啦，你做得很棒！",
        "topic_intro": "以下是今天学过的内容：",
        "topic_line": "  {topic}：{label}",
        "footer": "继续探索，下次再见！",
        "no_topics": "今天聊得很开心，下次再来！",
    },
}


def _build_topic_line(topic: TopicSummary, lang: str) -> str:
    """Format a single topic line using the label_soften module."""
    from .label_soften import soften_label

    # Determine age band from context — default to P1-P3 for wrap
    # (actual integration passes real age_band, this is the conservative default)
    kid_label = soften_label(topic.label_key, "P1-P3", lang, audience="kid_facing")
    return _TEMPLATES[lang]["topic_line"].format(topic=topic.topic, label=kid_label)


def generate_wrap(
    session: SessionState,
    lang_code: Optional[str] = None,
) -> str:
    """Generate a session-end wrap message.

    Args:
        session: SessionState with turns and topics.
        lang_code: Override language. Falls back to session.lang_code.

    Returns:
        Multi-line wrap message string.
    """
    lang = lang_code or session.lang_code
    if lang not in _TEMPLATES:
        lang = EN

    tpl = _TEMPLATES[lang]
    lines = [tpl["header"]]

    if session.topics:
        lines.append("")
        lines.append(tpl["topic_intro"])
        for topic in session.topics:
            lines.append(_build_topic_line(topic, lang))

    lines.append("")
    if not session.topics:
        lines.append(tpl["no_topics"])
    else:
        lines.append(tpl["footer"])

    return "\n".join(lines)


def is_wrap_turn(turn_count: int) -> bool:
    """Check if the given turn count triggers a session wrap."""
    return turn_count >= SESSION_WRAP_TURN
