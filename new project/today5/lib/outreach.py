"""Personalised outreach (task 4): short message built on one specific trigger, with a generic check."""
import json
import re

from pydantic import BaseModel, ConfigDict

from lib import settings
from lib.ai import generate_json

BANNED = ["hope this email finds you", "hope you are doing well", "hope you're doing well", "synergy",
          "leverage", "revolutionize", "revolutionise", "cutting-edge", "game-changer", "game changer",
          "seamless", "best-in-class", "world-class", "unlock", "empower"]


class Message(BaseModel):
    model_config = ConfigDict(extra="ignore")
    subject: str
    body: str
    trigger_used: str = ""
    generic: bool = False          # AI's own answer to the generic check
    generic_reason: str = ""


def pick_trigger(signals, brief):
    real = [s for s in signals if s.get("is_signal")]
    real.sort(key=lambda s: s.get("event_date") or "", reverse=True)
    if real:
        return real[0]["description"]
    for key in ("recent_news", "hiring", "what_they_do"):
        lines = brief.get(key) or []
        if lines:
            return lines[0]["text"]
    return None


def _problems(msg):
    probs = []
    words = len(msg.body.split())
    if words >= 90:
        probs.append(f"body is {words} words, must be under 90")
    low = msg.body.lower()
    for b in BANNED:
        if b in low:
            probs.append(f'remove "{b}"')
    if "?" not in msg.body:
        probs.append("end with one soft question")
    return probs


def _write(company_name, brief, trigger, contact, feedback=None):
    greeting = contact.get("name").split()[0] if contact and contact.get("name") else None
    prompt = f"""Write a cold outreach email to {company_name}. We sell {settings.target()["product"]}.
Recipient: {json.dumps(contact or {}, ensure_ascii=False)}  (greet as "Hi {greeting or 'there'},")
TRIGGER (a specific fact about them): {trigger or 'none found'}

RULES:
- Body under 90 words.
- First line must use the TRIGGER fact specifically.
- Mention ONE clear pain from the brief that our product solves.
- End with ONE soft question (no hard ask for a meeting).
- No buzzwords. Never write "I hope this email finds you well".
- Plain, human, specific to this company. Sign off as "- [Your name]".
- trigger_used: the exact fact you used in the first line.
{("FIX THESE PROBLEMS FROM THE LAST DRAFT: " + feedback) if feedback else ""}

GENERIC CHECK: after writing, ask yourself "Could this message be sent to any other company unchanged?"
Set generic true/false honestly and give generic_reason.

Return JSON: {{"subject":"...","body":"...","trigger_used":"...","generic":false,"generic_reason":"..."}}

BRIEF: {json.dumps(brief, ensure_ascii=False)}
"""
    return generate_json(prompt, Message)


def write(company_name, brief, signals, contact):
    trigger = pick_trigger(signals, brief)
    msg = _write(company_name, brief, trigger, contact)
    problems = _problems(msg)
    if msg.generic:
        problems.append(f"it is generic ({msg.generic_reason}); make it specific to {company_name}")
    if problems:  # regenerate once
        msg = _write(company_name, brief, trigger, contact, feedback="; ".join(problems))
    body = re.sub(r"\n{3,}", "\n\n", msg.body.strip())
    return {"subject": msg.subject.strip(), "body": body, "trigger_used": msg.trigger_used.strip()}
