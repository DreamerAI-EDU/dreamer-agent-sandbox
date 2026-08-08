"""
Dreamer AI Phase 2.3 — KidSafePipeline

Middleware that sits between DeepTutor response and student-facing output.
Chains: ToneRewrite → LabelSoften → SessionWrap.

Two paths:
  Normal: ToneRewrite → response goes to student
  Error:  error_templates (bypasses all other middleware)

Error path is triggered by calling process_error(), not process_response().
"""

from typing import Dict, Optional, Tuple

from .error_templates import get_error_message, label_error
from .tone_rewrite import rewrite_tone
from .session_wrap import SessionState, generate_wrap


class KidSafePipeline:
    """Kid-safe output middleware for Dreamer AI.

    Usage:
        pipeline = KidSafePipeline()

        # Normal response
        safe = pipeline.process_response(
            raw_text="...", age_band="P4-P6", lang_code="zh-hk",
            session=session_state,
        )

        # Error response
        safe = pipeline.process_error(
            raw_error="500 Internal Server Error",
            error_type="server_error",
            age_band="P1-P3", lang_code="en",
        )
    """

    def process_response(
        self,
        raw_text: str,
        age_band: str,
        lang_code: str,
        session: Optional[SessionState] = None,
    ) -> str:
        """Process a normal DeepTutor response through kid-safe pipeline.

        Args:
            raw_text: Raw DeepTutor response text.
            age_band: "P1-P3", "P4-P6", or "S1-S3".
            lang_code: "en", "zh-hk", or "zh-cn".
            session: Optional SessionState for turn tracking and wrap.

        Returns:
            Kid-safe output string.
        """
        # Step 1: Tone rewrite
        turn = session.turns if session else 0
        safe_text = rewrite_tone(raw_text, age_band, lang_code, turn_count=turn)

        # Step 2: Session wrap if needed
        if session is not None:
            session.increment()
            if session.should_wrap():
                wrap_msg = generate_wrap(session, lang_code=lang_code)
                safe_text = safe_text + "\n\n" + wrap_msg

        return safe_text

    def process_error(
        self,
        raw_error: str,
        error_type: str,
        age_band: str,
        lang_code: str,
    ) -> str:
        """Process an error through the error template path.

        Errors bypass ToneRewrite/LabelSoften/SessionWrap entirely.
        Raw error is logged internally (via label_error), student
        sees only the template-based friendly message.

        Args:
            raw_error: The raw/internal error string.
            error_type: One of "ws_error", "timeout", "server_error",
                        "empty_response", "unknown".
            age_band: "P1-P3", "P4-P6", or "S1-S3".
            lang_code: "en", "zh-hk", or "zh-cn".

        Returns:
            Student-facing friendly error message string.
        """
        # Log the raw error internally (consumer of this module should
        # write this to an actual logger; here we just compute the label
        # for structured logging)
        _logged = label_error(error_type)

        # Return kid-safe template message only
        return get_error_message(age_band, lang_code, raw_error=raw_error)
