from __future__ import annotations

import json
import logging
import re

log = logging.getLogger(__name__)


class ScriptRejected(Exception):
    """Raised when no script passes validation and the fact-check gate."""


def _extract_json(text: str) -> dict:
    text = text.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    if fenced:
        text = fenced.group(1)
    else:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end == -1:
            raise ValueError("No JSON object found in model reply")
        text = text[start:end + 1]
    return json.loads(text)


def _reply_text(response) -> str:
    return "".join(b.text for b in response.content if getattr(b, "type", "") == "text")


def word_count(script: dict) -> int:
    return sum(len(s["narration"].split()) for s in script["scenes"])


def validate_script(script: dict, cfg: dict) -> None:
    """Structural checks. Raises ValueError with a message the model can act on."""
    for key in ("topic", "title", "scenes", "caption", "hashtags", "facts"):
        if key not in script:
            raise ValueError(f"missing field '{key}'")
    lo_s, hi_s = cfg["claude"]["scene_range"]
    lo_w, hi_w = cfg["claude"]["word_range"]
    scenes = script["scenes"]
    if not (lo_s <= len(scenes) <= hi_s):
        raise ValueError(f"need {lo_s}-{hi_s} scenes, got {len(scenes)}")
    for i, s in enumerate(scenes):
        if not s.get("narration", "").strip() or not s.get("visual", "").strip():
            raise ValueError(f"scene {i + 1} needs both 'narration' and 'visual'")
    wc = word_count(script)
    if not (lo_w <= wc <= hi_w):
        raise ValueError(f"narration is {wc} words; it must be {lo_w}-{hi_w}")
    if len(scenes[0]["narration"].split()) > 18:
        raise ValueError("the first scene (the hook) must be 18 words or fewer")
    if not isinstance(script["hashtags"], list) or not (3 <= len(script["hashtags"]) <= 12):
        raise ValueError("give between 3 and 12 hashtags")
    if not script["facts"]:
        raise ValueError("list the factual claims in 'facts'")
    if len(script["caption"]) > 1500:
        raise ValueError("caption is too long (max 1500 characters)")


def _system_prompt(niche_cfg: dict, cfg: dict) -> str:
    rules = "\n".join(f"- {r}" for r in niche_cfg["rules"])
    lo_w, hi_w = cfg["claude"]["word_range"]
    lo_s, hi_s = cfg["claude"]["scene_range"]
    return f"""You write original scripts for short vertical videos (Instagram Reels) in the "{niche_cfg['label']}" niche, read aloud by a text-to-speech voice over stock footage.

STYLE
{niche_cfg['style'].strip()}

HARD RULES
{rules}
- The script must be entirely original: never copy or closely paraphrase another creator's script, video or post.
- Write for the ear: short sentences, plain words, no emojis, no hashtags or stage directions inside narration.
- The first scene is a hook of at most 18 words that makes someone stay.
- End with a satisfying closing line, not a generic "follow for more".

FORMAT
Reply with one JSON object and nothing else:
{{
  "topic": "one sentence describing the video's subject",
  "title": "short internal title (max 8 words)",
  "scenes": [
    {{"narration": "text spoken in this scene", "visual": "2-4 word search query for generic stock footage that fits"}}
  ],
  "caption": "Instagram caption: 2-4 short lines, ends with a question that invites comments",
  "hashtags": ["#tag1", "#tag2"],
  "facts": ["every factual claim made in the narration, one standalone sentence each"]
}}
Use {lo_s}-{hi_s} scenes and {lo_w}-{hi_w} narration words in total. "visual" queries must describe generic footage that exists on a stock site (cities, hands counting money, old maps, crowds, landscapes), never specific people or brands."""


def _user_prompt(niche_cfg: dict, recent_titles: list[str], hints: list[str],
                 feedback: str | None) -> str:
    parts = ["Pick today's topic and write the script."]
    if recent_titles:
        parts.append("Do NOT repeat or closely resemble these recent topics:\n"
                     + "\n".join(f"- {t}" for t in recent_titles))
    if hints:
        parts.append(
            "For loose inspiration only, these are things people are discussing right now. "
            "You may pick an unrelated topic; never reuse their wording:\n"
            + "\n".join(f"- {h}" for h in hints[:20]))
    if feedback:
        parts.append("Your previous attempt was rejected for these reasons. Fix them "
                     "(you may choose a safer topic instead):\n" + feedback)
    return "\n\n".join(parts)


VERIFY_SYSTEM = """You are a strict fact-checker and compliance reviewer for short educational videos.
Review the script and its list of factual claims. Fail it if ANY of these is true:
- a claim is false, doubtful, disputed among reputable sources, or stated with more certainty than the evidence supports;
- a date, number, name or quotation is wrong or cannot be confirmed from well-established knowledge;
- arithmetic in an example is wrong;
- it names or recommends specific securities, funds, crypto assets or products, promises returns, or quotes current rates, tax slabs or regulations;
- it includes an invented quote, or inflammatory framing of a religion, caste, nationality or ethnicity.
If you are not confident a claim is correct, fail it. Reply with one JSON object only:
{"verdict": "pass" or "fail", "issues": ["specific problem and the correction, one per item"]}"""


def verify_script(client, model: str, script: dict) -> tuple[bool, list[str]]:
    narration = "\n".join(s["narration"] for s in script["scenes"])
    payload = (f"NARRATION:\n{narration}\n\nCLAIMS:\n"
               + "\n".join(f"- {f}" for f in script["facts"]))
    resp = client.messages.create(
        model=model, max_tokens=1200, system=VERIFY_SYSTEM,
        messages=[{"role": "user", "content": payload}],
    )
    result = _extract_json(_reply_text(resp))
    passed = str(result.get("verdict", "fail")).lower() == "pass"
    return passed, [str(i) for i in result.get("issues", [])]


def finalize(script: dict, niche_cfg: dict) -> dict:
    """Clean hashtags and add the niche's caption footer."""
    seen, tags = set(), []
    for t in list(script["hashtags"]) + list(niche_cfg.get("base_hashtags", [])):
        t = "#" + re.sub(r"[^\w]", "", str(t).lstrip("#"))
        if len(t) > 1 and t.lower() not in seen:
            seen.add(t.lower())
            tags.append(t)
    footer = niche_cfg.get("caption_footer", "").strip()
    caption = script["caption"].strip()
    if footer:
        caption += f"\n\n{footer}"
    caption += "\n\n" + " ".join(tags[:15])
    script["full_caption"] = caption
    return script


def generate(client, cfg: dict, niche: str, recent_titles: list[str],
             hints: list[str]) -> dict:
    """Write a script, validate it, fact-check it. Retries with feedback.

    Raises ScriptRejected if nothing passes, so nothing unverified is ever posted.
    """
    niche_cfg = cfg["niches"][niche]
    model = cfg["claude"]["model"]
    system = _system_prompt(niche_cfg, cfg)
    feedback: str | None = None

    for attempt in range(1, cfg["claude"]["max_attempts"] + 1):
        log.info("Script attempt %d for niche '%s'", attempt, niche)
        resp = client.messages.create(
            model=model, max_tokens=2500, system=system,
            messages=[{"role": "user",
                       "content": _user_prompt(niche_cfg, recent_titles, hints, feedback)}],
        )
        try:
            script = _extract_json(_reply_text(resp))
            validate_script(script, cfg)
        except (ValueError, KeyError, json.JSONDecodeError) as exc:
            feedback = f"Format problem: {exc}"
            log.warning("Rejected (format): %s", exc)
            continue

        passed, issues = verify_script(client, model, script)
        if passed:
            log.info("Script passed fact-check: %s", script["title"])
            return finalize(script, niche_cfg)
        feedback = "Fact-check issues:\n" + "\n".join(f"- {i}" for i in issues)
        log.warning("Rejected (fact-check): %s", issues)

    raise ScriptRejected(f"No script passed after {cfg['claude']['max_attempts']} attempts. "
                         f"Last problem: {feedback}")
