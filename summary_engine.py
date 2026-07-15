"""
ODIN Memory — Layer 4: Summary Engine
Generates daily summaries from raw conversations (Layer 1).
Uses whichever provider is active in config/providers.json —
no hardcoded SDK here anymore.
"""

import sys
import json
from datetime import datetime, timezone, date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from settings import get_settings
from providers import call_llm, AllProvidersFailedError
from layers.layer1_raw.raw_logger import RawLogger

settings = get_settings()
SUMMARIES_DIR = settings.summaries_dir
SUMMARIES_DIR.mkdir(parents=True, exist_ok=True)

DAILY_SUMMARY_PROMPT = """You are ODIN's memory summarizer. Create a concise daily summary from these conversations.

The summary should capture:
1. Main topics discussed
2. Tasks or problems worked on
3. Decisions made
4. User's emotional state or energy level (if apparent)
5. Key takeaways ODIN should remember

Keep it under 300 words. Write in third person ("The user..." / "Charles...").
Return as JSON:
{{
  "date": "{date}",
  "headline": "One sentence summary of the day",
  "topics": ["topic1", "topic2"],
  "tasks_worked_on": ["task1"],
  "decisions_made": ["decision1"],
  "mood_energy": "brief note on user state",
  "key_takeaways": ["takeaway1", "takeaway2"],
  "full_summary": "Full narrative paragraph"
}}

Return ONLY valid JSON. No markdown fences.

CONVERSATIONS FROM {date}:
{conversations}
"""


class SummaryEngine:

    def __init__(self):
        self.raw_logger = RawLogger()

    async def generate_daily_summary(self, target_date: str = None) -> dict:
        if not target_date:
            target_date = date.today().isoformat()

        summary_file = SUMMARIES_DIR / f"{target_date}.json"

        sessions = self._get_sessions_for_date(target_date)
        if not sessions:
            return {
                "date": target_date,
                "status": "no_data",
                "message": "No conversations found for this date",
            }

        conversation_text = self._format_sessions(sessions)
        prompt = DAILY_SUMMARY_PROMPT.format(
            date=target_date,
            conversations=conversation_text[:8000],
        )

        try:
            result = await call_llm(prompt, max_tokens=1000, temperature=0.3)
            summary = self._parse_json(result["text"])

            if summary:
                summary["generated_at"] = datetime.now(timezone.utc).isoformat()
                summary["generated_by_provider"] = result["provider"]
                summary["session_count"] = len(sessions)
                summary["message_count"] = sum(len(s["messages"]) for s in sessions)

                with open(summary_file, "w", encoding="utf-8") as f:
                    json.dump(summary, f, indent=2, ensure_ascii=False)

                return summary
            return {"date": target_date, "status": "parse_failed", "raw": result["text"]}

        except AllProvidersFailedError as e:
            return {"date": target_date, "status": "error", "detail": str(e)}

    def get_summary(self, target_date: str) -> dict | None:
        summary_file = SUMMARIES_DIR / f"{target_date}.json"
        if not summary_file.exists():
            return None
        with open(summary_file, "r", encoding="utf-8") as f:
            return json.load(f)

    def get_recent_summaries(self, days: int = 7) -> list[dict]:
        results = []
        today = date.today()
        for i in range(days):
            day = (today - timedelta(days=i)).isoformat()
            summary = self.get_summary(day)
            if summary:
                results.append(summary)
        return results

    def list_all_summary_dates(self) -> list[str]:
        return sorted([f.stem for f in SUMMARIES_DIR.glob("*.json")], reverse=True)

    def count_summaries(self) -> int:
        return len(list(SUMMARIES_DIR.glob("*.json")))

    def _get_sessions_for_date(self, target_date: str) -> list[dict]:
        sessions = []
        for session_id in self.raw_logger.list_sessions():
            session = self.raw_logger.get_session(session_id)
            if not session:
                continue
            for msg in session.get("messages", []):
                ts = msg.get("timestamp", "")
                if ts.startswith(target_date):
                    sessions.append(session)
                    break
        return sessions

    def _format_sessions(self, sessions: list[dict]) -> str:
        parts = []
        for s in sessions:
            parts.append(f"\n--- Session {s['session_id']} ---")
            for msg in s["messages"]:
                ts = msg.get("timestamp", "")[:16]
                parts.append(f"[{ts}] {msg['role'].upper()}: {msg['content']}")
        return "\n".join(parts)

    def _parse_json(self, raw: str) -> dict | None:
        import re
        raw = re.sub(r"```(?:json)?\n?", "", raw).strip().rstrip("`")
        try:
            return json.loads(raw)
        except Exception:
            obj_match = re.search(r"\{.*\}", raw, re.DOTALL)
            if obj_match:
                try:
                    return json.loads(obj_match.group())
                except Exception:
                    pass
        return None
