#!/usr/bin/env python3
"""
Research Radar updater for Hanfei Zhu's homepage.

Fetches recent papers related to Hanfei's research directions from arXiv
(optionally enriched with an LLM one-line summary + Chinese translation),
and writes them to ../data/papers.json for the static site to render.

Usage:
    python3 scripts/update_radar.py                 # abstracts only, no API key needed
    ANTHROPIC_API_KEY=sk-... python3 scripts/update_radar.py   # + AI summaries (Claude)
    OPENAI_API_KEY=sk-...   python3 scripts/update_radar.py   # + AI summaries (GPT)

Third-party / proxy API keys are supported (any OpenAI- or Anthropic-compatible
endpoint). Point the base URL at your provider and, if needed, override the model:
    OPENAI_API_KEY=xxx OPENAI_BASE_URL=https://your-proxy.com/v1 RADAR_MODEL=gpt-4o-mini python3 scripts/update_radar.py
    ANTHROPIC_API_KEY=xxx ANTHROPIC_BASE_URL=https://your-proxy.com RADAR_MODEL=claude-sonnet-5 python3 scripts/update_radar.py

Designed to run in GitHub Actions on a weekly cron (see .github/workflows/radar.yml).
Only depends on the Python standard library unless AI summaries are enabled.
"""

import os, sys, json, time, html, re, urllib.parse, urllib.request
from datetime import datetime, timezone
from xml.etree import ElementTree as ET

# ---- Hanfei's research topics -> arXiv query buckets ------------------------
# Each bucket: a human-readable topic label + an arXiv search expression.
TOPICS = [
    ("LLM Evaluation",        'cat:cs.HC AND abs:"large language model" AND (abs:evaluation OR abs:benchmark)'),
    ("Human-Centered AI",     '(cat:cs.HC OR cat:cs.AI) AND abs:"human-centered" AND abs:"language model"'),
    ("LLM User Simulation",   'cat:cs.HC AND (abs:"user simulation" OR abs:"simulated users" OR abs:"usability") AND abs:"language model"'),
    ("AI-Assisted Creativity",'cat:cs.HC AND (abs:"creativity support" OR abs:"design implication" OR abs:"idea generation") AND abs:"language model"'),
]

MAX_PER_TOPIC   = 12          # fetch this many per bucket before de-duping
KEEP_TOTAL      = 16          # keep at most this many, newest first
ARXIV_ENDPOINT  = "https://export.arxiv.org/api/query"
ATOM            = "{http://www.w3.org/2005/Atom}"
OUT_PATH        = os.path.join(os.path.dirname(__file__), "..", "data", "papers.json")
USER_AGENT      = "ResearchRadar/1.0 (Hanfei Zhu homepage; mailto:zhf1102@zju.edu.cn)"


def fetch_arxiv(query, max_results):
    """Query arXiv, sorted by most recent submission. Retries politely on 429."""
    params = urllib.parse.urlencode({
        "search_query": query,
        "start": 0,
        "max_results": max_results,
        "sortBy": "submittedDate",
        "sortOrder": "descending",
    })
    url = f"{ARXIV_ENDPOINT}?{params}"
    for attempt in range(5):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < 4:
                wait = 5 * (attempt + 1)
                print(f"  429 from arXiv, backing off {wait}s...", file=sys.stderr)
                time.sleep(wait)
                continue
            raise
        except Exception as e:
            if attempt < 4:
                time.sleep(4)
                continue
            print(f"  giving up on query: {e}", file=sys.stderr)
            return ""
    return ""


def parse_entries(xml_text, topic):
    if not xml_text:
        return []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []
    papers = []
    for e in root.findall(f"{ATOM}entry"):
        def txt(tag):
            el = e.find(f"{ATOM}{tag}")
            return (el.text or "").strip() if el is not None else ""
        raw_id = txt("id")                     # http://arxiv.org/abs/2406.12345v1
        aid = raw_id.rsplit("/", 1)[-1]
        title = re.sub(r"\s+", " ", txt("title")).strip()
        abstract = re.sub(r"\s+", " ", txt("summary")).strip()
        published = txt("published")[:10]
        authors = [a.find(f"{ATOM}name").text.strip()
                   for a in e.findall(f"{ATOM}author") if a.find(f"{ATOM}name") is not None]
        cats = [c.get("term") for c in e.findall(f"{ATOM}category") if c.get("term")]
        pdf = ""
        for link in e.findall(f"{ATOM}link"):
            if link.get("title") == "pdf":
                pdf = link.get("href", "")
        papers.append({
            "id": aid,
            "title": title,
            "authors": authors[:8],
            "published": published,
            "source": "arXiv",
            "topic": topic,
            "url": raw_id.replace("http://", "https://"),
            "pdf": pdf,
            "categories": cats[:4],
            "abstract": abstract,
            "summary": abstract[:280].rstrip() + ("…" if len(abstract) > 280 else ""),
            "summary_zh": "",
        })
    return papers


# ---- optional: LLM one-line summary + Chinese translation -------------------
def ai_summarize(papers):
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
    openai_key = os.environ.get("OPENAI_API_KEY")
    if not (anthropic_key or openai_key):
        print("No LLM key found -> using truncated abstracts as summaries.", file=sys.stderr)
        return papers

    for p in papers:
        prompt = (
            "You are curating a researcher's paper-tracking feed. In 1-2 sentences, "
            "summarize the key contribution of this paper for an HCI/AI audience, then give a "
            "one-sentence Chinese translation of that summary. Respond as strict JSON "
            '{"en": "...", "zh": "..."}.\n\n'
            f"Title: {p['title']}\nAbstract: {p['abstract'][:1500]}"
        )
        try:
            if anthropic_key:
                en, zh = _call_anthropic(anthropic_key, prompt)
            else:
                en, zh = _call_openai(openai_key, prompt)
            if en:
                p["summary"] = en
            if zh:
                p["summary_zh"] = zh
            time.sleep(0.5)
        except Exception as e:
            print(f"  AI summary failed for {p['id']}: {e}", file=sys.stderr)
    return papers


def _extract_json(text):
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return "", ""
    try:
        d = json.loads(m.group(0))
        return d.get("en", "").strip(), d.get("zh", "").strip()
    except Exception:
        return "", ""


def _call_anthropic(key, prompt):
    base = os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com").rstrip("/")
    model = os.environ.get("RADAR_MODEL", "claude-sonnet-5")
    body = json.dumps({
        "model": model,
        "max_tokens": 400,
        "messages": [{"role": "user", "content": prompt}],
    }).encode()
    req = urllib.request.Request(
        f"{base}/v1/messages", data=body,
        headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                 "content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=40) as r:
        data = json.loads(r.read())
    return _extract_json("".join(b.get("text", "") for b in data.get("content", [])))


def _call_openai(key, prompt):
    base = os.environ.get("OPENAI_BASE_URL", os.environ.get("OPENAI_API_BASE", "https://api.openai.com/v1")).rstrip("/")
    model = os.environ.get("RADAR_MODEL", "gpt-4o-mini")
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
    }).encode()
    req = urllib.request.Request(
        f"{base}/chat/completions", data=body,
        headers={"Authorization": f"Bearer {key}", "content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=40) as r:
        data = json.loads(r.read())
    return _extract_json(data["choices"][0]["message"]["content"])


def main():
    collected = {}
    for topic, query in TOPICS:
        print(f"Fetching topic: {topic}", file=sys.stderr)
        xml = fetch_arxiv(query, MAX_PER_TOPIC)
        for p in parse_entries(xml, topic):
            # keep first occurrence (earliest topic bucket wins for label)
            collected.setdefault(p["id"], p)
        time.sleep(3)  # be polite to arXiv (they ask ~1 request / 3s)

    papers = sorted(collected.values(), key=lambda p: p["published"], reverse=True)[:KEEP_TOTAL]
    papers = ai_summarize(papers)

    out = {
        "updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "arXiv",
        "generated_by": "ai" if (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("OPENAI_API_KEY")) else "abstract",
        "topics": [t for t, _ in TOPICS],
        "count": len(papers),
        "papers": papers,
    }
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"Wrote {len(papers)} papers -> {os.path.relpath(OUT_PATH)}", file=sys.stderr)


if __name__ == "__main__":
    main()
