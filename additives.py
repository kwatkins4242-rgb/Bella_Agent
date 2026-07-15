"""
additives.py — per-turn enrichment (summary, sentiment, topics, relevance)
Uses whichever provider is active in config/providers.json.
"""
import json
import logging

from providers import call_llm, AllProvidersFailedError

logger = logging.getLogger("memory.additives")

PROMPT_TEMPLATE = """Analyze this conversation turn between a User and ODIN (AI).

USER: {user_msg}
ODIN: {assistant_msg}

Return a raw JSON object with these keys:
- summary: A concise 1-sentence recap of this turn.
- sentiment: The user's detected emotional state (1 word).
- topics: A list of 2-3 key topics or keywords.
- relevance: An importance score from 0.0 to 1.0.

Return ONLY JSON. No markdown fences."""


async def generate_additives(user_msg: str, assistant_msg: str) -> dict:
    prompt = PROMPT_TEMPLATE.format(user_msg=user_msg, assistant_msg=assistant_msg)
    try:
        result = await call_llm(prompt, max_tokens=200, temperature=0.2)
        clean_text = result["text"].replace("```json", "").replace("```", "").strip()
        parsed = json.loads(clean_text)
        parsed["_provider"] = result["provider"]
        return parsed
    except AllProvidersFailedError as e:
        logger.error("additives generation failed, all providers down: %s", e)
        return {}
    except (json.JSONDecodeError, KeyError) as e:
        logger.error("additives parse failed: %s", e)
        return {"error": str(e)}
