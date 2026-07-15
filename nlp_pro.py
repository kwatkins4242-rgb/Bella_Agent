"""
nlp_pro.py — ODIN Memory local NLP layer.
Lightweight entity/intent extraction using spaCy if available,
falling back to simple keyword extraction if not. This runs on
every save, synchronously — no API call, no cost, no external
dependency, so it never breaks even if every provider is down.
"""

try:
    import spacy
    try:
        _nlp = spacy.load("en_core_web_sm")
        SPACY_AVAILABLE = True
    except Exception:
        SPACY_AVAILABLE = False
        print("[NLP] spaCy model 'en_core_web_sm' not found — run: python -m spacy download en_core_web_sm")
except ImportError:
    SPACY_AVAILABLE = False
    print("[NLP] spaCy not installed — falling back to keyword extraction")

INTENT_MAP = {
    "fix_code": ["fix", "debug", "error", "broken", "crash", "bug", "traceback"],
    "generate": ["build", "create", "generate", "write", "make", "code"],
    "explain": ["explain", "what is", "how does", "describe", "tell me about"],
    "search": ["search", "find", "look up", "google", "news", "weather"],
    "memory": ["remember", "forget", "recall", "what did", "last time", "history"],
    "system": ["status", "restart", "stop", "start", "port", "service", "module"],
    "automotive": ["car", "vehicle", "engine", "obd", "diagnostic", "repair", "dtc", "code"],
}


def extract_entities(text: str) -> dict:
    result = {"entities": [], "intent": "general", "keywords": []}

    if SPACY_AVAILABLE:
        doc = _nlp(text)
        result["entities"] = [{"text": ent.text, "label": ent.label_} for ent in doc.ents]
        result["keywords"] = [
            token.lemma_.lower() for token in doc
            if not token.is_stop and not token.is_punct and len(token.text) > 2
        ]
    else:
        words = [w.strip(".,?!").lower() for w in text.split() if len(w) > 3]
        result["keywords"] = words

    text_lower = text.lower()
    for intent, triggers in INTENT_MAP.items():
        if any(t in text_lower for t in triggers):
            result["intent"] = intent
            break

    return result


def format_for_context(entities: dict) -> str:
    parts = []
    if entities.get("intent") and entities["intent"] != "general":
        parts.append(f"Detected intent: {entities['intent']}")
    if entities.get("entities"):
        ent_strs = [f"{e['text']} ({e['label']})" for e in entities["entities"][:5]]
        parts.append(f"Named entities: {', '.join(ent_strs)}")
    return " | ".join(parts) if parts else ""
