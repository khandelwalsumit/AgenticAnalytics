"""Helper utilities for graph orchestration and deterministic artifact assembly."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage

from agents.nodes import _read_json, _read_text
from agents.state import AnalyticsState
from config import DATA_DIR, DATA_OUTPUT_DIR, DATA_CACHE_DIR
from tools import TOOL_REGISTRY

import chainlit as cl
from ui.components import sync_task_list

logger = logging.getLogger("agenticanalytics.graph")


from config import SUMMARIZE_THRESHOLD_CHARS, SYNTHESIZER_MAX_LENS_CHARS

MAX_REPORT_RETRIES = 3


# ═══════════════════════════════════════════════════════════════════════════
# Per-bucket summarization (OPT-1)
# Extracts structured summaries from raw lens markdown to reduce synthesizer
# context. Preserves: key issues/themes, call volume, and solutions by team.
# ═══════════════════════════════════════════════════════════════════════════

_TEAM_LABELS = {
    "digital": "Digital / UX",
    "operations": "Operations",
    "communication": "Communication",
    "policy": "Policy / Compliance",
}


def _try_parse_json(text: str) -> Any:
    """Parse JSON, repairing truncated output from LLMs that hit token limits.

    LLMs sometimes produce JSON that ends mid-string because the response
    was cut off at max_tokens.  This function tries json.loads first, then
    progressively closes open brackets/braces from the truncation point.
    """
    text = (text or "").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        pass

    # Count unclosed brackets and try to close them
    # Walk the string tracking open/close state (ignore chars inside strings)
    opens: list[str] = []
    in_string = False
    escape = False
    for ch in text:
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"' and not escape:
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch in ("{", "["):
            opens.append(ch)
        elif ch == "}" and opens and opens[-1] == "{":
            opens.pop()
        elif ch == "]" and opens and opens[-1] == "[":
            opens.pop()

    if not opens:
        return None

    # Truncate any trailing partial value (unfinished string, number, etc.)
    # by finding the last complete key-value separator
    repair = text.rstrip()
    # Strip trailing partial tokens: commas, colons, partial strings
    while repair and repair[-1] in (",", ":", " ", "\n", "\r", "\t"):
        repair = repair[:-1]
    # If we're inside an unclosed string, close it
    # Count unescaped quotes — odd means we're mid-string
    quote_count = 0
    esc = False
    for ch in repair:
        if esc:
            esc = False
            continue
        if ch == "\\":
            esc = True
            continue
        if ch == '"':
            quote_count += 1
    if quote_count % 2 == 1:
        repair += '"'

    # Close all open brackets in reverse order
    for bracket in reversed(opens):
        repair += "]" if bracket == "[" else "}"

    try:
        return json.loads(repair)
    except (json.JSONDecodeError, ValueError):
        return None


def _extract_bucket_summary(bucket_key: str, bucket_name: str, raw_md: str) -> str:
    """Extract structured summary from a friction agent's JSON output.

    Friction agents output JSON in code fences with: top_drivers, findings,
    ease_score, impact_score, priority_score. This function parses that JSON
    and formats it as markdown for the synthesizer.

    Fails loudly if the expected JSON structure is missing so broken agents
    are immediately visible.
    """
    if not raw_md or not raw_md.strip():
        raise ValueError(
            f"[_extract_bucket_summary] Empty output for bucket '{bucket_name}' "
            f"(key={bucket_key}). The friction agent produced no response."
        )

    data: dict[str, Any] = {}

    # full_response is a concat of multiple AI messages — scan ALL code fences
    # and pick the one that contains friction output keys (top_drivers/findings).
    # The last valid match wins (final agent output is typically last).
    candidates: list[str] = []
    if "```" in raw_md:
        for part in raw_md.split("```")[1::2]:
            part = part.strip()
            if part.startswith("json"):
                part = part[4:].strip()
            candidates.append(part)

    # Also try raw brace extraction
    if "{" in raw_md:
        start = raw_md.find("{")
        end = raw_md.rfind("}")
        if start < end:
            candidates.append(raw_md[start:end + 1])

    for candidate in candidates:
        parsed = _try_parse_json(candidate)
        if isinstance(parsed, list) and parsed and isinstance(parsed[0], dict):
            parsed = parsed[0]
        if isinstance(parsed, dict) and ("top_drivers" in parsed or "findings" in parsed):
            data = parsed

    if not data:
        raise ValueError(
            f"[_extract_bucket_summary] Could not parse JSON from friction agent "
            f"output for bucket '{bucket_name}' (key={bucket_key}). "
            f"Raw output starts with: {raw_md[:300]!r}"
        )

    # Required fields — fail if missing so we know which agent is broken
    for required_key in ("top_drivers", "findings"):
        if required_key not in data:
            raise ValueError(
                f"[_extract_bucket_summary] Missing required key '{required_key}' "
                f"in friction output for bucket '{bucket_name}'. "
                f"Got keys: {list(data.keys())}"
            )

    parts = [f"### {bucket_name}"]

    def _num(val: Any, default: int | float = 0) -> int | float:
        """Coerce a possibly-None value to a number."""
        if val is None:
            return default
        try:
            return type(default)(val)
        except (TypeError, ValueError):
            return default

    # Volume
    call_count = int(_num(data.get("call_count"), 0))
    call_pct = float(_num(data.get("call_percentage"), 0.0))
    total_calls = int(_num(data.get("total_dataset_calls"), call_count))
    parts.append(f"**Volume**: {call_count} calls ({call_pct:.1f}% of {total_calls} total)")

    # Scores
    ease = _num(data.get("ease_score"), 0)
    impact = _num(data.get("impact_score"), 0)
    priority = _num(data.get("priority_score"), 0)
    parts.append(f"**Scores**: Impact={impact}/10 | Ease={ease}/10 | Priority={priority}/10")

    # Top drivers
    for d in data.get("top_drivers") or []:
        if not isinstance(d, dict) or "driver" not in d:
            continue
        d_count = int(_num(d.get("call_count"), 0))
        d_pct = float(_num(d.get("contribution_pct"), 0.0))
        d_solution = str(d.get("recommended_solution") or "N/A")[:150]
        parts.append(
            f"  - [{d.get('type') or 'secondary'}] {d['driver']} — "
            f"{d_count} calls ({d_pct:.1f}%) "
            f"→ {d_solution}"
        )

    # Findings with scores (may be truncated — skip incomplete entries)
    findings = data.get("findings") or []
    if findings:
        parts.append("**Findings**:")
        for f in findings:
            if not isinstance(f, dict):
                continue
            finding_text = str(f.get("finding") or "")
            if not finding_text:
                continue
            preventable = f.get("preventable_call", f.get("preventable", False))
            f_impact = _num(f.get("impact_score"), 0)
            f_ease = _num(f.get("ease_score"), 0)
            f_conf = _num(f.get("confidence"), 0)
            parts.append(
                f"  - (impact={f_impact}, ease={f_ease}, "
                f"conf={f_conf}, preventable={'yes' if preventable else 'no'}) "
                f"{finding_text[:200]}"
            )
            action = (str(f.get("recommended_action") or "")
                      or str(f.get("recommended_product_fix") or "")
                      or str(f.get("recommended_process_fix") or ""))
            if action:
                team = _detect_team_from_text(action)
                team_label = _TEAM_LABELS.get(team, team.title())
                parts.append(f"    → [{team_label}] {action[:180]}")

    return "\n".join(parts) + "\n"


def _detect_team_from_text(text: str) -> str:
    """Detect which team a solution belongs to based on keywords."""
    lower = text.lower()
    team_keywords = {
        "digital": ["app", "web", "ui", "ux", "digital", "mobile", "online", "self-service",
                     "portal", "interface", "click", "page", "screen", "button", "api"],
        "operations": ["process", "sla", "handoff", "agent", "queue", "workflow", "manual",
                        "backlog", "escalat", "training", "procedure", "turnaround"],
        "communication": ["notification", "email", "sms", "alert", "message", "letter",
                           "communicat", "inform", "update", "reminder", "template", "proactive"],
        "policy": ["policy", "regulat", "compliance", "fee", "rule", "terms", "legal",
                    "waiver", "exception", "eligib", "restrict"],
    }
    scores: dict[str, int] = {team: 0 for team in team_keywords}
    for team, keywords in team_keywords.items():
        for kw in keywords:
            if kw in lower:
                scores[team] += 1
    best_team = max(scores, key=scores.get)  # type: ignore[arg-type]
    return best_team if scores[best_team] > 0 else "operations"


L2_BATCH_SIZE = 10  # Group ~10 buckets per intermediate LLM summary


def _extract_bucket_entries(
    lens_id: str,
    bucket_path_dict: dict[str, str],
    raw_buckets: dict[str, Any],
) -> list[dict[str, Any]]:
    """Extract structured summaries from all bucket files for one lens.

    Returns a list of dicts sorted by volume descending, each containing:
      key, name, volume, summary (full markdown), condensed (one-liner), parsed (bool).
    """
    from pathlib import Path as _P

    entries: list[dict[str, Any]] = []
    for bk in sorted(bucket_path_dict.keys()):
        bpath = bucket_path_dict[bk]
        bucket_name = bk
        row_count = 0
        if isinstance(raw_buckets.get(bk), dict):
            bucket_name = raw_buckets[bk].get("bucket_name", bk)
            row_count = int(raw_buckets[bk].get("row_count", 0) or 0)

        if not (bpath and _P(bpath).exists()):
            entries.append({
                "key": bk, "name": bucket_name, "volume": row_count,
                "summary": f"### {bucket_name}\n(No output)\n",
                "condensed": f"- {bucket_name}: no output",
                "parsed": False,
            })
            continue

        raw_content = _P(bpath).read_text(encoding="utf-8").strip()
        if not raw_content:
            logger.warning("Empty friction output for %s / %s: %s", lens_id, bk, bpath)
            entries.append({
                "key": bk, "name": bucket_name, "volume": row_count,
                "summary": f"### {bucket_name}\n(No output — empty response)\n",
                "condensed": f"- {bucket_name}: empty output",
                "parsed": False,
            })
            continue

        try:
            full_summary = _extract_bucket_summary(bk, bucket_name, raw_content)
            parsed_volume = _parse_volume_from_summary(full_summary, row_count)
            condensed = _condense_bucket_one_liner(bk, bucket_name, raw_content, parsed_volume)
            entries.append({
                "key": bk, "name": bucket_name, "volume": parsed_volume,
                "summary": full_summary, "condensed": condensed, "parsed": True,
            })
        except Exception as exc:
            logger.warning("Skipping bucket %s / %s - summary extraction failed: %s", lens_id, bk, exc)
            continue

    entries.sort(key=lambda e: e["volume"], reverse=True)
    return entries


def _summarize_lens_buckets(
    lens_id: str,
    bucket_path_dict: dict[str, str],
    raw_buckets: dict[str, Any],
) -> str:
    """Summarize all bucket outputs for one lens using volume-weighted L2 compression.

    Used when bucket count ≤ 10. For >10 buckets, use
    ``_summarize_lens_buckets_with_llm`` which adds intermediate LLM grouping.

    Three-tier approach to keep synthesizer context manageable:
      - **Tier 1** (top buckets covering ~80% of total call volume): full extracted
        summary with all findings, drivers, and solutions.
      - **Tier 2** (remaining buckets): condensed to one line each — bucket name,
        call count, top driver, and scores.
      - **Volume header**: total calls, bucket count, and tier split so the
        synthesizer understands the data distribution.
    """
    bucket_entries = _extract_bucket_entries(lens_id, bucket_path_dict, raw_buckets)
    return _build_tiered_lens_output(lens_id, bucket_entries)


def _build_tiered_lens_output(
    lens_id: str,
    bucket_entries: list[dict[str, Any]],
) -> str:
    """Build the final lens output from extracted bucket entries using tier1/tier2 split."""
    total_volume = sum(e["volume"] for e in bucket_entries)

    # Tier 1: top buckets covering ~80% of volume (min 5, max 20)
    cumulative = 0
    tier1_cutoff = max(5, min(20, len(bucket_entries)))
    volume_threshold = total_volume * 0.80 if total_volume > 0 else 0
    for idx, entry in enumerate(bucket_entries):
        cumulative += entry["volume"]
        if cumulative >= volume_threshold and idx >= 4:
            tier1_cutoff = idx + 1
            break

    tier1 = bucket_entries[:tier1_cutoff]
    tier2 = bucket_entries[tier1_cutoff:]

    tier1_volume = sum(e["volume"] for e in tier1)
    tier2_volume = sum(e["volume"] for e in tier2)

    parts = [
        f"# {lens_id} — Lens Summary (L2)\n",
        f"**{len(bucket_entries)} buckets analyzed** | "
        f"Total calls: {total_volume:,} | "
        f"Tier 1 (detailed): {len(tier1)} buckets ({tier1_volume:,} calls, "
        f"{tier1_volume / total_volume * 100:.0f}% of volume)" if total_volume > 0 else
        f"Tier 1 (detailed): {len(tier1)} buckets",
    ]
    if tier2:
        parts.append(
            f"Tier 2 (condensed): {len(tier2)} buckets ({tier2_volume:,} calls, "
            f"{tier2_volume / total_volume * 100:.0f}% of volume)" if total_volume > 0 else
            f"Tier 2 (condensed): {len(tier2)} buckets"
        )
    parts.append("")

    # Tier 1: full summaries
    parts.append("## High-Volume Themes (Detailed)\n")
    for entry in tier1:
        parts.append(entry["summary"])

    # Tier 2: one-liner condensed
    if tier2:
        parts.append("\n## Lower-Volume Themes (Condensed)\n")
        parts.append(
            "The following themes had lower call volumes. "
            "Key details are condensed to top driver and scores:\n"
        )
        for entry in tier2:
            parts.append(entry["condensed"])

    result = "\n".join(parts)

    # Hard cap to prevent context explosion
    if len(result) > SYNTHESIZER_MAX_LENS_CHARS:
        truncated_at = SYNTHESIZER_MAX_LENS_CHARS - 200
        result = (
            result[:truncated_at]
            + f"\n\n---\n*[Truncated: lens output exceeded {SYNTHESIZER_MAX_LENS_CHARS:,} char limit. "
            f"{len(result):,} total chars, showing top themes by volume.]*\n"
        )
        logger.warning(
            "Lens %s output truncated: %d -> %d chars",
            lens_id, len("\n".join(parts)), len(result),
        )

    logger.info(
        "L2 summary for %s: %d buckets (tier1=%d, tier2=%d), %d chars",
        lens_id, len(bucket_entries), len(tier1), len(tier2), len(result),
    )
    return result


def _group_buckets_into_batches(
    entries: list[dict[str, Any]],
    batch_size: int = L2_BATCH_SIZE,
) -> list[list[dict[str, Any]]]:
    """Group bucket entries into batches of ~batch_size, sorted by volume descending.

    Buckets are already sorted by volume. We create batches so each intermediate
    summary covers a manageable set of themes.
    """
    if not entries:
        return []
    batches: list[list[dict[str, Any]]] = []
    for i in range(0, len(entries), batch_size):
        batches.append(entries[i:i + batch_size])
    return batches


async def _llm_summarize_batch(
    lens_id: str,
    batch_idx: int,
    batch: list[dict[str, Any]],
    total_volume: int,
) -> str:
    """Call the LLM to produce an intermediate L2 summary for a batch of buckets.

    Each batch gets a focused prompt asking the LLM to consolidate the bucket
    analyses into key themes, preserving volume data and actionable solutions.
    """
    from langchain_core.messages import HumanMessage as _HM, SystemMessage as _SM
    from core.chat_model import VertexAILLM

    batch_volume = sum(e["volume"] for e in batch)
    bucket_texts = []
    for entry in batch:
        bucket_texts.append(entry["summary"])

    combined_input = "\n\n".join(bucket_texts)

    system_prompt = (
        "You are a friction analysis summarizer. You receive detailed analyses "
        "of multiple customer call buckets from the same analytical lens. "
        "Your job is to consolidate them into a concise intermediate summary that:\n"
        "1. Identifies the TOP 3-5 cross-cutting themes across these buckets\n"
        "2. Preserves exact call volumes and percentages\n"
        "3. Ranks themes by total call volume (highest first)\n"
        "4. For each theme: state the problem, combined call volume, "
        "top drivers, impact/ease scores, and recommended solutions\n"
        "5. Notes which original buckets contribute to each theme\n\n"
        "Keep it structured and concise. Use markdown headers and bullet points. "
        "Do NOT invent data — only summarize what is provided."
    )

    user_prompt = (
        f"Lens: {lens_id}\n"
        f"Batch {batch_idx + 1}: {len(batch)} buckets, "
        f"{batch_volume:,} calls ({batch_volume / max(total_volume, 1) * 100:.0f}% of total)\n\n"
        f"Summarize the following bucket analyses into consolidated themes:\n\n"
        f"{combined_input}"
    )

    try:
        llm = VertexAILLM(temperature=0.1, max_output_tokens=4096)
        response = await llm.ainvoke([_SM(content=system_prompt), _HM(content=user_prompt)])
        summary = response.content if hasattr(response, "content") else str(response)
        logger.info(
            "L2 intermediate summary for %s batch %d: %d buckets -> %d chars",
            lens_id, batch_idx + 1, len(batch), len(summary),
        )
        return f"## Batch {batch_idx + 1} ({len(batch)} buckets, {batch_volume:,} calls)\n\n{summary}\n"
    except Exception as exc:
        logger.error("L2 intermediate LLM call failed for %s batch %d: %s", lens_id, batch_idx + 1, exc)
        # Fallback: return raw extracted summaries without LLM consolidation
        fallback_parts = [f"## Batch {batch_idx + 1} ({len(batch)} buckets, {batch_volume:,} calls)\n"]
        for entry in batch:
            fallback_parts.append(entry["summary"])
        return "\n".join(fallback_parts)


async def _summarize_lens_buckets_with_llm(
    lens_id: str,
    bucket_path_dict: dict[str, str],
    raw_buckets: dict[str, Any],
) -> str:
    """Summarize bucket outputs with intermediate LLM grouping for >10 buckets.

    Pipeline:
      1. Extract per-bucket structured summaries (text-only, no LLM)
      2. Group into batches of ~10 buckets sorted by volume
      3. LLM call per batch to produce intermediate consolidated summary
      4. Assemble final lens output from batch summaries + hard cap
    """
    import asyncio as _aio

    bucket_entries = _extract_bucket_entries(lens_id, bucket_path_dict, raw_buckets)

    if len(bucket_entries) <= L2_BATCH_SIZE:
        # ≤10 buckets: use direct tiered output (no LLM needed)
        return _build_tiered_lens_output(lens_id, bucket_entries)

    total_volume = sum(e["volume"] for e in bucket_entries)
    batches = _group_buckets_into_batches(bucket_entries, L2_BATCH_SIZE)

    logger.info(
        "L2 intermediate summarization for %s: %d buckets -> %d batches (batch_size=%d)",
        lens_id, len(bucket_entries), len(batches), L2_BATCH_SIZE,
    )

    # Run all batch LLM calls in parallel
    batch_coros = [
        _llm_summarize_batch(lens_id, i, batch, total_volume)
        for i, batch in enumerate(batches)
    ]
    batch_summaries = await _aio.gather(*batch_coros)

    # Assemble final lens output
    parts = [
        f"# {lens_id} — Lens Summary (L2, Intermediate Grouped)\n",
        f"**{len(bucket_entries)} buckets analyzed** | "
        f"Total calls: {total_volume:,} | "
        f"Grouped into {len(batches)} intermediate summaries\n",
    ]
    for summary in batch_summaries:
        parts.append(summary)

    result = "\n".join(parts)

    # Hard cap
    if len(result) > SYNTHESIZER_MAX_LENS_CHARS:
        truncated_at = SYNTHESIZER_MAX_LENS_CHARS - 200
        result = (
            result[:truncated_at]
            + f"\n\n---\n*[Truncated: lens output exceeded {SYNTHESIZER_MAX_LENS_CHARS:,} char limit. "
            f"{len(result):,} total chars.]*\n"
        )
        logger.warning("Lens %s output truncated: %d chars", lens_id, len(result))

    logger.info(
        "L2 grouped summary for %s: %d buckets, %d batches, %d chars",
        lens_id, len(bucket_entries), len(batches), len(result),
    )
    return result


def _parse_volume_from_summary(summary: str, fallback: int = 0) -> int:
    """Extract call count from a bucket summary's **Volume** line."""
    m = re.search(r"\*\*Volume\*\*:\s*(\d[\d,]*)\s*calls", summary)
    if m:
        return int(m.group(1).replace(",", ""))
    return fallback


def _condense_bucket_one_liner(
    bucket_key: str, bucket_name: str, raw_md: str, volume: int,
) -> str:
    """Produce a single-line condensed summary for a low-volume bucket.

    Format: - BucketName: N calls | Impact=X Ease=Y | Top driver: ...
    """
    data = _extract_json_from_friction_output(raw_md)
    if not data:
        return f"- {bucket_name}: {volume} calls (could not parse details)"

    impact = data.get("impact_score", 0)
    ease = data.get("ease_score", 0)
    top_driver = ""
    for d in data.get("top_drivers", []):
        if isinstance(d, dict) and d.get("driver"):
            top_driver = str(d["driver"])[:100]
            break

    line = f"- **{bucket_name}**: {volume:,} calls | Impact={impact}/10 Ease={ease}/10"
    if top_driver:
        line += f" | Top driver: {top_driver}"
    return line


def _extract_json_from_friction_output(raw_md: str) -> dict[str, Any]:
    """Extract the friction agent's JSON payload from raw markdown output.

    Shared parser used by both _extract_bucket_summary and _condense_bucket_one_liner.
    """
    data: dict[str, Any] = {}
    candidates: list[str] = []
    if "```" in raw_md:
        for part in raw_md.split("```")[1::2]:
            part = part.strip()
            if part.startswith("json"):
                part = part[4:].strip()
            candidates.append(part)
    if "{" in raw_md:
        start = raw_md.find("{")
        end = raw_md.rfind("}")
        if start < end:
            candidates.append(raw_md[start:end + 1])
    for candidate in candidates:
        parsed = _try_parse_json(candidate)
        if isinstance(parsed, list) and parsed and isinstance(parsed[0], dict):
            parsed = parsed[0]
        if isinstance(parsed, dict) and ("top_drivers" in parsed or "findings" in parsed):
            data = parsed
    return data


def _should_summarize_lens_outputs(
    nested_md_paths: dict[str, dict[str, str]],
) -> bool:
    """Check if total raw lens output exceeds threshold, requiring summarization."""
    from pathlib import Path as _P

    total_chars = 0
    for lens_id, bucket_paths in nested_md_paths.items():
        for bk, bpath in bucket_paths.items():
            if bpath and _P(bpath).exists():
                total_chars += _P(bpath).stat().st_size
            if total_chars > SUMMARIZE_THRESHOLD_CHARS:
                return True
    return False


def _extract_json(text: str) -> dict[str, Any]:
    text = (text or "").strip()
    if not text:
        return {}

    if "```" in text:
        for part in text.split("```")[1::2]:
            part = part.strip()
            if part.startswith("json"):
                part = part[4:].strip()
            try:
                parsed = json.loads(part)
                return parsed if isinstance(parsed, dict) else {}
            except (json.JSONDecodeError, ValueError):
                continue

    for candidate in (text, text[text.find("{"): text.rfind("}") + 1] if "{" in text else ""):
        if not candidate:
            continue
        try:
            parsed = json.loads(candidate)
            return parsed if isinstance(parsed, dict) else {}
        except (json.JSONDecodeError, ValueError):
            continue
    return {}


def _tools_used_in_call(base_state: dict[str, Any], result: dict[str, Any]) -> list[str]:
    base_len = len(base_state.get("execution_trace", []))
    trace = result.get("execution_trace", [])
    if not isinstance(trace, list) or not trace:
        return []
    delta = trace[base_len:] if len(trace) > base_len else trace[-1:]
    tools: list[str] = []
    for entry in delta:
        if isinstance(entry, dict):
            tools.extend([t for t in entry.get("tools_used", []) if isinstance(t, str)])
    return tools


def _path_exists(raw_path: str) -> bool:
    if not raw_path:
        return False
    p = Path(raw_path)
    if p.exists():
        return True
    tmp_candidate = _thread_tmp_dir() / p.name
    if tmp_candidate.exists():
        return True
    if not p.is_absolute():
        alt = Path(DATA_DIR) / p.name
        if alt.exists():
            return True
    return False


def _safe_thread_id(raw: str) -> str:
    text = str(raw or "").strip() or "unknown_thread"
    return re.sub(r"[^a-zA-Z0-9_-]", "_", text)[:80]


def _thread_tmp_dir(thread_id: str = "") -> Path:
    if not thread_id:
        try:
            thread_id = str(cl.user_session.get("thread_id") or "unknown_thread")
        except Exception:
            thread_id = "unknown_thread"
    return Path(DATA_CACHE_DIR) / _safe_thread_id(thread_id)


def _thread_output_dir() -> Path:
    thread_id = str(cl.user_session.get("thread_id") or "unknown_thread")
    return Path(DATA_OUTPUT_DIR) / _safe_thread_id(thread_id)


def _validate_narrative(result: dict[str, Any]) -> list[str]:
    narrative_path = result.get("narrative_path", "")
    if not narrative_path:
        return ["narrative_path missing from narrative node result."]
    if not Path(narrative_path).exists():
        return [f"narrative_path file not found: {narrative_path}"]
    full = _read_text(narrative_path).strip()
    if not full:
        return [f"narrative_path file is empty: {narrative_path}"]

    errors: list[str] = []
    slide_tag_pattern = r"<!--\s*SLIDE\s*:\s*.+?-->"
    tags = re.findall(slide_tag_pattern, full, flags=re.IGNORECASE | re.DOTALL)
    if len(tags) < 3:
        errors.append("Narrative markdown must include at least 3 `<!-- SLIDE: ... -->` tags.")

    # Only flag as JSON-like if the entire output is predominantly JSON
    # (starts with '{' or '[') AND lacks slide tags.  A small JSON preamble
    # before valid markdown is acceptable — the LLM sometimes emits a
    # structured summary before the narrative.
    stripped = full.lstrip()
    if stripped.startswith(("{", "[")) and len(tags) < 3:
        errors.append("Narrative output appears JSON-like; expected pure markdown with slide tags.")

    return errors


def _validate_dataviz(result: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    payload = result.get("dataviz_output", {})
    full = payload.get("full_response", "") if isinstance(payload, dict) else ""
    data = _extract_json(full)
    charts = data.get("charts", []) if isinstance(data, dict) else []
    if not isinstance(charts, list) or len(charts) < 3:
        errors.append("DataViz output must include 3 charts.")
        return errors

    required_types = {"friction_distribution", "impact_ease_scatter", "driver_breakdown"}
    found_types = {str(c.get("type", "")) for c in charts if isinstance(c, dict)}
    missing_types = sorted(required_types - found_types)
    if missing_types:
        errors.append(f"DataViz output missing chart types: {missing_types}")

    for chart in charts:
        if not isinstance(chart, dict):
            continue
        path = str(chart.get("file_path", "")).strip()
        if path and not _path_exists(path):
            errors.append(f"Chart file not found on disk: {path}")

    return errors


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return default


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _build_deterministic_dataviz_output(state: dict[str, Any]) -> dict[str, Any]:
    """Generate required charts deterministically via Python chart scripts."""
    synthesis: dict[str, Any] = {}
    synthesis_path = state.get("synthesis_path", "")
    if synthesis_path:
        synthesis = _read_json(synthesis_path)

    themes_raw = synthesis.get("themes", []) if isinstance(synthesis, dict) else []

    themes: list[str] = []
    call_counts: list[int] = []
    ease_scores: list[float] = []
    impact_scores: list[float] = []
    primary_counts: list[int] = []
    secondary_counts: list[int] = []

    for item in themes_raw[:8] if isinstance(themes_raw, list) else []:
        if not isinstance(item, dict):
            continue
        theme_name = str(item.get("theme", "")).strip() or "Unknown"
        total_calls = max(0, _safe_int(item.get("call_count", 0), 0))
        ease = max(0.0, _safe_float(item.get("ease_score", 0.0), 0.0))
        impact = max(0.0, _safe_float(item.get("impact_score", 0.0), 0.0))

        primary = 0
        secondary = 0
        drivers = item.get("all_drivers", [])
        if isinstance(drivers, list):
            for driver in drivers:
                if not isinstance(driver, dict):
                    continue
                driver_calls = max(0, _safe_int(driver.get("call_count", 0), 0))
                if str(driver.get("type", "")).strip().lower() == "primary":
                    primary += driver_calls
                else:
                    secondary += driver_calls
        if primary == 0 and secondary == 0:
            primary = total_calls

        themes.append(theme_name)
        call_counts.append(total_calls)
        ease_scores.append(min(ease, 10.0))
        impact_scores.append(min(impact, 10.0))
        primary_counts.append(primary)
        secondary_counts.append(secondary)

    if not themes:
        themes = ["No matching data"]
        call_counts = [0]
        ease_scores = [0.0]
        impact_scores = [0.0]
        primary_counts = [0]
        secondary_counts = [0]

    chart_specs = [
        {
            "type": "friction_distribution",
            "title": "Customer Call Volume by Theme",
            "description": "Horizontal bar chart showing themes sorted by call volume",
            "output_filename": "friction_distribution.png",
            "code": (
                "import numpy as np\n"
                f"labels = {json.dumps(themes)}\n"
                f"values = {json.dumps(call_counts)}\n"
                "if not labels:\n"
                "    labels = ['No matching data']\n"
                "    values = [0]\n"
                "order = np.argsort(values)\n"
                "labels = [labels[i] for i in order]\n"
                "values = [values[i] for i in order]\n"
                "fig, ax = plt.subplots(figsize=(10, max(4, 0.45 * len(labels) + 1.5)))\n"
                "bars = ax.barh(labels, values, color='#4361ee')\n"
                "max_value = max(values) if values else 1\n"
                "for bar, val in zip(bars, values):\n"
                "    ax.text(val + max(0.2, max_value * 0.02), bar.get_y() + bar.get_height() / 2, str(int(val)), va='center', fontsize=9)\n"
                "ax.set_title('Customer Call Volume by Theme')\n"
                "ax.set_xlabel('Number of Calls')\n"
                "fig.tight_layout()\n"
                "fig.savefig(output_path, dpi=180, bbox_inches='tight')\n"
            ),
        },
        {
            "type": "impact_ease_scatter",
            "title": "Impact vs Ease Prioritization Matrix",
            "description": "Bubble scatter plot with quadrant guides",
            "output_filename": "impact_ease_scatter.png",
            "code": (
                f"labels = {json.dumps(themes)}\n"
                f"ease = {json.dumps(ease_scores)}\n"
                f"impact = {json.dumps(impact_scores)}\n"
                f"calls = {json.dumps(call_counts)}\n"
                "sizes = [max(80, c * 16 + 80) for c in calls]\n"
                "fig, ax = plt.subplots(figsize=(9, 6))\n"
                "ax.scatter(ease, impact, s=sizes, alpha=0.7, c='#4361ee', edgecolors='#1a1a2e')\n"
                "for x, y, label in zip(ease, impact, labels):\n"
                "    ax.text(x + 0.1, y + 0.1, label, fontsize=8)\n"
                "ax.axhline(5.5, linestyle='--', linewidth=1, color='#bbbbbb')\n"
                "ax.axvline(5.5, linestyle='--', linewidth=1, color='#bbbbbb')\n"
                "ax.set_xlim(0, 10.5)\n"
                "ax.set_ylim(0, 10.5)\n"
                "ax.set_title('Impact vs Ease Prioritization Matrix')\n"
                "ax.set_xlabel('Ease of Implementation (1-10)')\n"
                "ax.set_ylabel('Customer Impact (1-10)')\n"
                "fig.tight_layout()\n"
                "fig.savefig(output_path, dpi=180, bbox_inches='tight')\n"
            ),
        },
        {
            "type": "driver_breakdown",
            "title": "Driver Breakdown by Theme",
            "description": "Stacked horizontal bar chart of primary vs secondary drivers",
            "output_filename": "driver_breakdown.png",
            "code": (
                "import numpy as np\n"
                f"labels = {json.dumps(themes)}\n"
                f"primary = {json.dumps(primary_counts)}\n"
                f"secondary = {json.dumps(secondary_counts)}\n"
                "totals = [p + s for p, s in zip(primary, secondary)]\n"
                "order = np.argsort(totals)\n"
                "labels = [labels[i] for i in order]\n"
                "primary = [primary[i] for i in order]\n"
                "secondary = [secondary[i] for i in order]\n"
                "fig, ax = plt.subplots(figsize=(10, max(4, 0.5 * len(labels) + 1.5)))\n"
                "ax.barh(labels, primary, color='#4361ee', label='Primary Driver')\n"
                "ax.barh(labels, secondary, left=primary, color='#4cc9f0', label='Secondary Drivers')\n"
                "ax.set_title('Driver Breakdown by Theme')\n"
                "ax.set_xlabel('Number of Calls')\n"
                "ax.legend(loc='best')\n"
                "fig.tight_layout()\n"
                "fig.savefig(output_path, dpi=180, bbox_inches='tight')\n"
            ),
        },
    ]

    chart_tool = TOOL_REGISTRY["execute_chart_code"]
    # Resolve output dir from state so the tool doesn't need Chainlit context
    # (safe for thread-pool contexts where cl.user_session is unavailable).
    tid = _safe_thread_id(state.get("thread_id", "unknown_thread"))
    chart_output_dir = str(Path(DATA_CACHE_DIR) / tid)
    charts: list[dict[str, Any]] = []
    for spec in chart_specs:
        raw_result = chart_tool.invoke({
            "code": spec["code"],
            "output_filename": spec["output_filename"],
            "output_dir": chart_output_dir,
        })
        parsed = _extract_json(str(raw_result))
        chart_path = str(parsed.get("chart_path", "")).strip()
        if not chart_path:
            chart_path = str(_thread_tmp_dir(state.get("thread_id", "")) / spec["output_filename"])

        if not _path_exists(chart_path):
            logger.warning(
                "DataViz fallback chart generation missed file %s; retrying with placeholder.",
                chart_path,
            )
            placeholder = (
                "fig, ax = plt.subplots(figsize=(8, 4))\n"
                "ax.text(0.5, 0.5, 'No chart data available', ha='center', va='center', fontsize=14)\n"
                "ax.axis('off')\n"
                "fig.tight_layout()\n"
                "fig.savefig(output_path, dpi=180, bbox_inches='tight')\n"
            )
            raw_result = chart_tool.invoke({
                "code": placeholder,
                "output_filename": spec["output_filename"],
            })
            parsed = _extract_json(str(raw_result))
            chart_path = str(parsed.get("chart_path", "")).strip() or chart_path

        charts.append({
            "type": spec["type"],
            "title": spec["title"],
            "file_path": chart_path,
            "html_path": str(Path(chart_path).with_suffix(".html")),
            "description": spec["description"],
        })

    payload = {"charts": charts}
    payload_json = json.dumps(payload, indent=2)
    logger.info("DataViz deterministic chart generation completed.")
    return {
        "messages": [AIMessage(content=payload_json)],
        "reasoning": [{
            "step_name": "DataViz Script",
            "step_text": "Executed deterministic Python chart scripts and generated required visual assets.",
            "agent": "dataviz_script",
        }],
        "dataviz_output": {
            "output": payload_json[:200],
            "full_response": payload_json,
            "agent": "dataviz_script",
        },
    }


def _parse_slide_tag(raw_tag: str) -> dict[str, str]:
    """Parse one <!-- SLIDE: ... --> tag into section/layout/title fields."""
    inner = str(raw_tag or "").strip()
    inner = inner.removeprefix("<!--").removesuffix("-->").strip()
    if inner.lower().startswith("slide:"):
        inner = inner[6:].strip()

    parts = [p.strip() for p in inner.split("|") if p.strip()]
    if not parts:
        return {}

    section_type = parts[0].strip()
    layout = ""
    title = ""
    for part in parts[1:]:
        if ":" not in part:
            continue
        key, value = part.split(":", 1)
        key = key.strip().lower()
        value = value.strip().strip('"').strip("'")
        if key == "layout":
            layout = value
        elif key == "title":
            title = value

    return {
        "section_type": section_type,
        "layout": layout,
        "title": title,
    }


def _parse_narrative_slide_blocks(markdown_text: str) -> list[dict[str, str]]:
    """Split narrative markdown into ordered slide blocks using SLIDE tags."""
    text = str(markdown_text or "")
    tag_pattern = re.compile(r"<!--\s*SLIDE\s*:.*?-->", flags=re.IGNORECASE | re.DOTALL)
    matches = list(tag_pattern.finditer(text))
    blocks: list[dict[str, str]] = []
    if not matches:
        return blocks

    for idx, match in enumerate(matches):
        tag_text = match.group(0)
        parsed = _parse_slide_tag(tag_text)
        if not parsed:
            continue
        start = match.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        blocks.append({
            "section_type": parsed.get("section_type", ""),
            "layout": parsed.get("layout", ""),
            "title": parsed.get("title", ""),
            "body": body,
            "tag": tag_text,
        })

    return blocks


def _extract_deck_title_subtitle_from_markdown(markdown_text: str) -> tuple[str, str]:
    """Pick deck title/subtitle from narrative markdown."""
    title = "Friction Analysis Report"
    subtitle = ""
    lines = [ln.strip() for ln in str(markdown_text or "").splitlines()]
    lines = [ln for ln in lines if ln and not ln.startswith("<!--")]

    for line in lines:
        if line.startswith("# "):
            title = line[2:].strip() or title
            break

    for line in lines:
        if line.startswith("## "):
            subtitle = line[3:].strip()
            break
        if not line.startswith("#"):
            subtitle = line
            break
    return title, subtitle


def _build_fallback_formatting_from_narrative_markdown(narrative_markdown: str) -> dict[str, Any]:
    """Deterministic fallback blueprint from narrative slide tags."""
    blocks = _parse_narrative_slide_blocks(narrative_markdown)
    deck_title, deck_subtitle = _extract_deck_title_subtitle_from_markdown(narrative_markdown)
    if not blocks:
        blocks = [{
            "section_type": "executive_summary",
            "layout": "title_slide",
            "title": deck_title,
            "body": narrative_markdown.strip(),
            "tag": "",
        }]

    slides: list[dict[str, Any]] = []
    for idx, block in enumerate(blocks, start=1):
        layout_raw = str(block.get("layout", "")).strip().lower()
        layout_map = {
            "title_impact": "title_slide",
            "section_divider": "section_divider",
            "callout_stat": "callout",
            "three_column": "three_column",
            "table_full": "table",
            "action_list": "table",
            "scorecard_drivers": "scorecard_table",
        }
        layout = layout_map.get(layout_raw, layout_raw or "callout")
        if layout not in {"title_slide", "section_divider", "callout", "three_column", "table", "scorecard_table"}:
            layout = "callout"

        body = str(block.get("body", "")).strip()
        elements: list[dict[str, Any]] = []
        if body:
            elements.append({
                "type": "paragraph",
                "text": body[:4000],
            })
        else:
            elements.append({
                "type": "paragraph",
                "text": "Slide content generated from narrative fallback.",
            })

        slides.append({
            "slide_number": idx,
            "section_type": str(block.get("section_type", "")).strip() or "narrative",
            "layout": layout,
            "title": str(block.get("title", "")).strip() or f"Slide {idx}",
            "elements": elements,
        })

    return {
        "deck_title": deck_title,
        "deck_subtitle": deck_subtitle,
        "total_slides": len(slides),
        "qa_enhancements_applied": [
            "fallback: generated deterministic slide blueprint from narrative markdown",
        ],
        "slides": slides,
    }


def _validate_formatting_blueprint(result: dict[str, Any]) -> list[str]:
    """Validate formatting agent structured deck blueprint."""
    payload = result.get("formatting_output", {})
    full = payload.get("full_response", "") if isinstance(payload, dict) else ""
    data = _extract_json(full)

    if not isinstance(data, dict):
        return ["Formatting output is not valid JSON."]

    slides = data.get("slides", [])
    if not isinstance(slides, list) or len(slides) < 3:
        return ["Formatting output must include at least 3 slides."]
    return []


def _styled_text(text: str, style: str) -> str:
    content = str(text or "").strip()
    if not content:
        return ""
    style_key = str(style or "normal").strip().lower()
    if style_key == "bold":
        return f"**{content}**"
    if style_key == "italic":
        return f"*{content}*"
    if style_key == "bold_italic":
        return f"***{content}***"
    return content


def _resolve_chart_placeholder(
    value: str,
    chart_paths: dict[str, str],
    unused_ids: list[str],
) -> str:
    text = str(value or "").strip()
    if not text:
        return ""

    if text in chart_paths:
        if text in unused_ids:
            unused_ids.remove(text)
        return text

    m = re.search(r"\{\{\s*chart\.([a-zA-Z0-9_-]+)\s*\}\}", text)
    if m:
        key = m.group(1).strip()
        if key in chart_paths:
            if key in unused_ids:
                unused_ids.remove(key)
            return key

    stem = Path(text).stem
    if stem in chart_paths:
        if stem in unused_ids:
            unused_ids.remove(stem)
        return stem

    if unused_ids:
        return unused_ids.pop(0)
    return ""


def _build_slide_plan_from_formatting(
    formatting_json: dict[str, Any],
    chart_paths: dict[str, str],
) -> dict[str, Any]:
    slides = formatting_json.get("slides", []) if isinstance(formatting_json, dict) else []
    if not isinstance(slides, list):
        slides = []

    # Keep deterministic order even if model returns unordered slide_number.
    slides = sorted(
        [s for s in slides if isinstance(s, dict)],
        key=lambda s: _safe_int(s.get("slide_number", 0), 0) or 10_000,
    )

    plan_slides: list[dict[str, Any]] = []
    unused_chart_ids = list(chart_paths.keys())

    for idx, slide in enumerate(slides, start=1):
        layout = str(slide.get("layout", "callout")).strip() or "callout"
        section_type = str(slide.get("section_type", "")).strip().lower()
        title = _stringify(slide.get("title", ""), limit=180) or f"Slide {idx}"
        elements = slide.get("elements", [])
        if not isinstance(elements, list):
            elements = []

        subtitle = ""
        points: list[str] = []
        visual = "none"
        notes: list[str] = []
        qa_note = _stringify(slide.get("qa_note", ""), limit=250)
        if qa_note:
            notes.append(f"QA: {qa_note}")

        for elem in elements:
            if not isinstance(elem, dict):
                continue
            etype = str(elem.get("type", "")).strip()

            if etype == "image_prompt":
                placeholder_raw = str(elem.get("placeholder_id", "")).strip() or str(elem.get("text", "")).strip()
                placeholder = _resolve_chart_placeholder(placeholder_raw, chart_paths, unused_chart_ids)
                if placeholder:
                    visual = placeholder
                caption = _stringify(elem.get("caption", ""), limit=220)
                if caption:
                    notes.append(caption)
                continue

            if etype == "table":
                headers = elem.get("headers", [])
                rows = elem.get("rows", [])
                if isinstance(headers, list) and headers:
                    points.append(" | ".join([_stringify(h, limit=80) for h in headers]))
                if isinstance(rows, list):
                    for row in rows[:8]:
                        if isinstance(row, list):
                            points.append(" | ".join([_stringify(cell, limit=120) for cell in row]))
                continue

            text = _stringify(elem.get("text", ""), limit=600)
            if not text:
                continue
            styled = _styled_text(text, str(elem.get("style", "normal")))
            level = max(1, min(4, _safe_int(elem.get("level", 1), 1)))

            if layout == "title_slide":
                if not subtitle and etype in {"heading2", "heading3", "paragraph", "callout_text", "bullet"}:
                    subtitle = styled
                else:
                    notes.append(styled)
                continue

            if etype == "bullet":
                label = _stringify(elem.get("label", ""), limit=80)
                content = f"{label}: {styled}" if label else styled
                indent = "  " * max(0, level - 1)
                points.append(f"{indent}- {content}")
            else:
                points.append(styled)

        if layout == "title_slide":
            plan_slides.append({
                "type": "title",
                "title": title,
                "subtitle": subtitle,
                "points": [],
                "visual": "none",
                "notes": " ".join(notes).strip(),
            })
            continue

        slide_type = "content"
        if visual == "impact_ease_scatter" or "matrix" in section_type:
            slide_type = "impact_ease"
        elif visual != "none" or layout in {"scorecard_table", "three_column"}:
            slide_type = "theme_detail"

        plan_slides.append({
            "type": slide_type,
            "title": title,
            "points": points[:12],
            "visual": visual,
            "notes": " ".join(notes).strip(),
        })

    if not plan_slides:
        deck_title = _stringify(formatting_json.get("deck_title", ""), limit=140) or "Friction Analysis Report"
        deck_subtitle = _stringify(formatting_json.get("deck_subtitle", ""), limit=180)
        plan_slides.append({
            "type": "title",
            "title": deck_title,
            "subtitle": deck_subtitle,
            "points": [],
            "visual": "none",
            "notes": "Auto-generated fallback title slide.",
        })

    return {"slides": plan_slides}


def _run_artifact_writer_node(
    state: AnalyticsState,
    narrative_result: dict[str, Any],
    formatting_result: dict[str, Any],
) -> dict[str, Any]:
    """Deterministically create dataviz + pptx + csv; persist narrative markdown directly."""
    dataviz_result = _build_deterministic_dataviz_output(state)
    dataviz_errors = _validate_dataviz(dataviz_result)
    if dataviz_errors:
        raise RuntimeError(f"Deterministic DataViz generation failed validation: {dataviz_errors}")

    narrative_payload = narrative_result.get("narrative_output", {})
    narrative_markdown = str(
        narrative_payload.get("full_response", "") if isinstance(narrative_payload, dict) else ""
    ).strip()
    if not narrative_markdown:
        narrative_markdown = "# Analysis Report\n\nNo narrative markdown was generated."

    formatting_payload = formatting_result.get("formatting_output", {})
    formatting_json = _extract_json(
        formatting_payload.get("full_response", "") if isinstance(formatting_payload, dict) else ""
    )
    if not isinstance(formatting_json, dict) or not isinstance(formatting_json.get("slides", []), list):
        formatting_json = _build_fallback_formatting_from_narrative_markdown(narrative_markdown)

    dataviz_json = _extract_json(
        dataviz_result.get("dataviz_output", {}).get("full_response", "")
        if isinstance(dataviz_result.get("dataviz_output", {}), dict) else ""
    )

    chart_paths = _build_chart_paths_map(dataviz_json)
    slide_plan = _build_slide_plan_from_formatting(formatting_json, chart_paths)

    # Persist narrative markdown directly to DataStore + output path.
    output_dir = _thread_output_dir()
    output_dir.mkdir(parents=True, exist_ok=True)
    markdown_path = str(output_dir / "complete_analysis.md")
    Path(markdown_path).write_text(narrative_markdown, encoding="utf-8")

    report_key = "report_markdown"
    data_store = cl.user_session.get("data_store")
    if data_store is not None:
        report_key = data_store.store_md(
            "report_markdown",
            narrative_markdown,
            {"agent": "narrative_agent", "type": "report_markdown"},
        )

    ppt_tool = TOOL_REGISTRY["export_to_pptx"]
    ppt_raw = ppt_tool.invoke({
        "slide_plan_json": json.dumps(slide_plan, default=str),
        "chart_paths_json": json.dumps(chart_paths, default=str),
        "report_key": report_key,
    })
    ppt_data = _extract_json(str(ppt_raw))
    report_path = _resolve_existing_path(str(ppt_data.get("pptx_path", "")).strip())

    csv_tool = TOOL_REGISTRY["export_filtered_csv"]
    csv_raw = csv_tool.invoke({})
    csv_data = _extract_json(str(csv_raw))
    data_path = _resolve_existing_path(str(csv_data.get("csv_path", "")).strip())

    payload = {
        "report_markdown_key": report_key,
        "markdown_file_path": markdown_path,
        "report_file_path": report_path,
        "data_file_path": data_path,
    }
    payload_json = json.dumps(payload, indent=2)
    logger.info("Artifact writer completed deterministic exports: %s", payload)
    return {
        "messages": [AIMessage(content=payload_json)],
        "reasoning": [{
            "step_name": "Artifact Writer",
            "step_text": "Ran chart scripts, stored narrative markdown, resolved placeholders, and generated PPTX and CSV artifacts.",
            "agent": "artifact_writer_node",
        }],
        "dataviz_output": dataviz_result.get("dataviz_output", {}),
        "report_markdown_key": report_key,
        "markdown_file_path": markdown_path,
        "report_file_path": report_path,
        "data_file_path": data_path,
    }


def _resolve_existing_path(raw_path: str) -> str:
    path = str(raw_path or "").strip()
    if not path:
        return ""
    p = Path(path)
    if p.exists():
        return str(p)
    tmp_alt = _thread_tmp_dir() / p.name
    if tmp_alt.exists():
        return str(tmp_alt)
    if not p.is_absolute():
        alt = Path(DATA_DIR) / p.name
        if alt.exists():
            return str(alt)
    return path


def _stringify(value: Any, *, limit: int = 220) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        text = value.strip()
    elif isinstance(value, (int, float, bool)):
        text = str(value)
    elif isinstance(value, list):
        parts = [_stringify(v, limit=limit) for v in value]
        text = "; ".join([p for p in parts if p])
    elif isinstance(value, dict):
        parts: list[str] = []
        for k, v in value.items():
            rendered = _stringify(v, limit=limit)
            if rendered:
                label = str(k).replace("_", " ").strip().title()
                parts.append(f"{label}: {rendered}")
        text = " | ".join(parts)
    else:
        text = str(value).strip()
    if len(text) > limit:
        return text[: limit - 3].rstrip() + "..."
    return text


def _build_chart_paths_map(dataviz_json: dict[str, Any]) -> dict[str, str]:
    chart_paths: dict[str, str] = {}
    charts = dataviz_json.get("charts", []) if isinstance(dataviz_json, dict) else []
    if not isinstance(charts, list):
        return chart_paths
    for chart in charts:
        if not isinstance(chart, dict):
            continue
        chart_type = _stringify(chart.get("type", ""), limit=80)
        raw_path = _stringify(chart.get("file_path", ""), limit=400)
        resolved_path = _resolve_existing_path(raw_path)
        if chart_type and resolved_path:
            chart_paths[chart_type] = resolved_path
    return chart_paths


def _build_executive_summary_message(narrative_path_or_payload: Any) -> str:
    """Build a concise user-facing summary from the narrative markdown file."""
    # New model: narrative_path_or_payload is a file path string
    full = ""
    if isinstance(narrative_path_or_payload, str) and narrative_path_or_payload:
        full = _read_text(narrative_path_or_payload).strip()
    if not full:
        return "Executive summary is ready in the final report artifacts."

    blocks = _parse_narrative_slide_blocks(full)
    target_block = None
    for block in blocks:
        section = str(block.get("section_type", "")).lower()
        if "executive" in section or "pain_point" in section:
            target_block = block
            break
    if target_block is None and blocks:
        target_block = blocks[0]

    if target_block is None:
        return "Executive summary is ready in the final report artifacts."

    lines = [ln.strip() for ln in str(target_block.get("body", "")).splitlines()]
    cleaned: list[str] = []
    for ln in lines:
        if not ln or ln == "---" or ln.startswith("<!--"):
            continue
        text = re.sub(r"^#+\s*", "", ln)
        text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
        text = re.sub(r"\*(.*?)\*", r"\1", text)
        text = text.strip()
        if text:
            cleaned.append(text)
        if len(cleaned) >= 2:
            break

    if not cleaned:
        return "Executive summary is ready in the final report artifacts."
    return " ".join(cleaned)


def _build_friction_reasoning_entries(
    lens_ids: list[str],
    state: dict[str, Any],
    synth_result: dict[str, Any],
) -> list[dict[str, str]]:
    """Curated reasoning entries for friction-analysis composite step."""
    # Count buckets from manifest
    bucket_count = 1
    manifest_path = state.get("bucket_manifest_path", "")
    if manifest_path and Path(manifest_path).exists():
        try:
            manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
            bucket_count = len(manifest.get("buckets", [])) or 1
        except Exception:
            pass
    entries: list[dict[str, str]] = []
    for aid in lens_ids:
        title = FRICTION_SUB_AGENTS.get(aid, {}).get("title", aid.replace("_", " ").title())
        lens_name = title.replace(" Agent", "")
        entries.append({
            "step_name": title,
            "step_text": f"Running {bucket_count} theme bucket(s) through the {lens_name} lens.",
            "agent": aid,
        })

    synth_text = ""
    for r in synth_result.get("reasoning", []):
        if isinstance(r, dict):
            synth_text = str(r.get("step_text", "")).strip()
            if synth_text:
                break
    entries.append({
        "step_name": "Synthesizer Agent",
        "step_text": synth_text or "Consolidating cross-lens findings into a single executive synthesis.",
        "agent": "synthesizer_agent",
    })
    return entries


def _build_report_reasoning_entries() -> list[dict[str, str]]:
    """Curated reasoning entries for report-generation composite step."""
    return [
        {
            "step_name": "Narrative Agent",
            "step_text": "Shaping a McKinsey-style executive narrative with quantified findings and a clear decision arc.",
            "agent": "narrative_agent",
        },
        {
            "step_name": "Formatting Agent",
            "step_text": "Designing a polished slide blueprint with chart placeholders and actionable hierarchy.",
            "agent": "formatting_agent",
        },
        {
            "step_name": "DataViz Script",
            "step_text": "Firing deterministic Python scripts to generate chart outputs for the deck.",
            "agent": "dataviz_script",
        },
        {
            "step_name": "Artifact Writer",
            "step_text": "Creating PPT, data and md files by binding chart outputs into the slide placeholders.",
            "agent": "artifact_writer_node",
        },
    ]


def _validate_artifact_paths(result: dict[str, Any]) -> list[str]:
    """Validate that artifacts_dir exists and contains the markdown report."""
    errors: list[str] = []
    artifacts_dir = str(result.get("artifacts_dir", "")).strip()
    if not artifacts_dir:
        errors.append("Missing artifacts_dir.")
        return errors
    p = Path(artifacts_dir)
    if not p.is_dir():
        errors.append(f"artifacts_dir does not exist: {artifacts_dir}")
        return errors
    md = p / "complete_analysis.md"
    if not md.exists():
        errors.append(f"complete_analysis.md missing in artifacts_dir: {artifacts_dir}")
    return errors


def _build_retry_instruction(
    *,
    agent_id: str,
    attempt: int,
    max_attempts: int,
    required_tools: list[str],
    previous_errors: list[str],
) -> str:
    lines = [f"Execution contract for {agent_id} (attempt {attempt}/{max_attempts})."]
    if required_tools:
        lines.append(f"Required tool calls in this attempt: {', '.join(required_tools)}.")
    else:
        lines.append("No tool calls are required for this attempt.")
    lines.append("Do not return an empty response.")

    if agent_id == "narrative_agent":
        lines.extend([
            "Call get_findings_summary before final output.",
            "Return pure markdown with explicit `<!-- SLIDE: ... -->` boundary tags.",
            "Do not return JSON.",
        ])
    elif agent_id == "formatting_agent":
        lines.extend([
            "Return only structured deck JSON with deck metadata and detailed slide elements.",
            "Use image placeholders via image_prompt.placeholder_id (e.g., {{chart.friction_distribution}}).",
            "Do not call export tools from this node.",
        ])

    if previous_errors:
        lines.append(f"Previous attempt failed validation: {json.dumps(previous_errors)}")
        lines.append("Fix every validation error in this attempt.")

    return "\n".join(lines)


async def _run_agent_with_retries(
    *,
    agent_id: str,
    node_fn: Any,
    base_state: dict[str, Any],
    required_tools: list[str],
    validator: Any,
    max_attempts: int = MAX_REPORT_RETRIES,
) -> dict[str, Any]:
    previous_errors: list[str] = []
    for attempt in range(1, max_attempts + 1):
        attempt_state = dict(base_state)
        attempt_state["report_retry_context"] = {
            "agent": agent_id,
            "attempt": attempt,
            "max_attempts": max_attempts,
            "required_tools": required_tools,
            "previous_errors": previous_errors,
        }
        base_messages = list(base_state.get("messages", []))
        base_messages.append(HumanMessage(content=_build_retry_instruction(
            agent_id=agent_id,
            attempt=attempt,
            max_attempts=max_attempts,
            required_tools=required_tools,
            previous_errors=previous_errors,
        )))
        attempt_state["messages"] = base_messages
        result = await node_fn(attempt_state)

        errors: list[str] = []
        tools_used = _tools_used_in_call(base_state, result)
        missing_tools = [t for t in required_tools if t not in tools_used]
        if missing_tools:
            errors.append(f"Missing required tool calls: {missing_tools}")

        errors.extend(validator(result))
        if not errors:
            logger.info(
                "Report generation: %s succeeded on attempt %d/%d (tools=%s)",
                agent_id, attempt, max_attempts, tools_used,
            )
            return result

        previous_errors = errors
        logger.warning(
            "Report generation: %s attempt %d/%d failed validation: %s",
            agent_id, attempt, max_attempts, errors,
        )

    raise RuntimeError(
        f"{agent_id} failed after {max_attempts} attempts. Last validation errors: {previous_errors}"
    )


# -- Sub-agent catalog (drives TaskList UI) ------------------------------------
# Each entry maps agent_id -> {title, detail} for display in the Chainlit task list.

FRICTION_SUB_AGENTS = {
    "digital_friction_agent": {
        "title": "Digital Friction Agent",
        "detail": "Digital product & UX gap analysis",
    },
    "operations_agent": {
        "title": "Operations Agent",
        "detail": "Process & SLA breakdown analysis",
    },
    "communication_agent": {
        "title": "Communication Agent",
        "detail": "Notification & expectation gap analysis",
    },
    "policy_agent": {
        "title": "Policy Agent",
        "detail": "Regulatory & governance constraint analysis",
    },
    "synthesizer_agent": {
        "title": "Synthesizer Agent",
        "detail": "Cross-lens root cause synthesis & ranking",
    },
}

REPORTING_SUB_AGENTS = {
    "narrative_agent": {
        "title": "Narrative Agent",
        "detail": "Slide deck structure & story design",
    },
    "formatting_agent": {
        "title": "Formatting Agent",
        "detail": "Structured slide blueprint with chart placeholders",
    },
    "artifact_writer_node": {
        "title": "Artifact Writer",
        "detail": "Creating PPT, data and md files",
    },
}


def _set_task_sub_agents(
    tasks: list[dict[str, Any]],
    *,
    agent_name: str,
    sub_agents: list[dict[str, Any]],
    task_status: str | None = None,
) -> list[dict[str, Any]]:
    """Update a task's sub_agents list and optionally its status.

    Finds the task whose ``agent`` field matches *agent_name* and sets its
    ``sub_agents`` list. Returns the updated tasks list (mutates in place).
    """
    updated = [dict(t) for t in tasks]
    for task in updated:
        if task.get("agent") != agent_name:
            continue
        if task_status is not None:
            task["status"] = task_status
        task["sub_agents"] = sub_agents
        return updated
    return updated


def _make_sub_agent_entries(
    catalog: dict[str, dict[str, str]],
    agent_ids: list[str],
    status: str = "in_progress",
) -> list[dict[str, Any]]:
    """Build sub_agent dicts from the catalog for given agent IDs."""
    return [
        {
            "id": agent_id,
            "title": catalog[agent_id]["title"],
            "detail": catalog[agent_id]["detail"],
            "status": status,
        }
        for agent_id in agent_ids
        if agent_id in catalog
    ]


def _merge_parallel_outputs(outputs: list[dict[str, Any]]) -> dict[str, Any]:
    """Merge multiple parallel agent outputs into a single state delta.

    Rules:
    - messages: concatenate all
    - reasoning: concatenate all
    - execution_trace: concatenate all
    - Dedicated state fields (digital_analysis, etc.): take from whichever output has them
    - Other fields: last writer wins
    """
    merged: dict[str, Any] = {}
    list_fields = {"messages", "reasoning", "execution_trace"}
    for output in outputs:
        for key, value in output.items():
            if key in list_fields:
                merged.setdefault(key, [])
                if isinstance(value, list):
                    merged[key].extend(value)
                else:
                    merged[key].append(value)
            else:
                merged[key] = value

    return merged


async def _emit_task_list_update(tasks: list[dict[str, Any]]) -> None:
    """Push an intermediate TaskList update to Chainlit UI."""
    task_list: cl.TaskList | None = cl.user_session.get("task_list")
    task_list = await sync_task_list(task_list, tasks)
    cl.user_session.set("task_list", task_list)


async def _set_task_sub_agents_and_emit(
    tasks: list[dict[str, Any]],
    *,
    agent_name: str,
    sub_agents: list[dict[str, Any]],
    task_status: str | None = None,
) -> list[dict[str, Any]]:
    """Update task sub-agent rows and push TaskList UI update."""
    updated = _set_task_sub_agents(
        tasks,
        agent_name=agent_name,
        sub_agents=sub_agents,
        task_status=task_status,
    )
    await _emit_task_list_update(updated)
    return updated


def _make_sub_agent_entry(
    catalog: dict[str, dict[str, str]],
    agent_id: str,
    *,
    status: str,
    detail_override: str | None = None,
) -> dict[str, Any]:
    """Build one sub-agent entry from catalog metadata."""
    meta = catalog[agent_id]
    return {
        "id": agent_id,
        "title": meta["title"],
        "detail": detail_override if detail_override is not None else meta["detail"],
        "status": status,
    }


def _set_sub_agent_status(
    sub_agents: list[dict[str, Any]],
    agent_id: str,
    *,
    status: str,
    detail: str | None = None,
) -> None:
    """Mutate one sub-agent entry status/detail in place."""
    for item in sub_agents:
        if item.get("id") != agent_id:
            continue
        item["status"] = status
        if detail is not None:
            item["detail"] = detail
        return


def _merge_state_deltas(
    *sources: dict[str, Any],
    list_keys: set[str] | None = None,
    skip_keys: set[str] | None = None,
) -> dict[str, Any]:
    """Merge multiple node deltas into one dict.

    Scalar values are last-writer-wins; list keys are concatenated.
    """
    out: dict[str, Any] = {}
    merge_list_keys = list_keys or set()
    ignore = skip_keys or set()

    for src in sources:
        for key, value in src.items():
            if key in ignore:
                continue
            if key in merge_list_keys and isinstance(value, list):
                out.setdefault(key, [])
                out[key].extend(value)
            else:
                out[key] = value
    return out


def _record_plan_progress(
    state: dict[str, Any],
    result: dict[str, Any],
    *,
    agent_name: str,
    mark_analysis_complete: bool = False,
) -> None:
    """Increment and persist plan progress in result delta."""
    tasks = result.get("plan_tasks", state.get("plan_tasks", []))
    total = max(state.get("plan_steps_total", 0), len(tasks) if isinstance(tasks, list) else 0)
    done_count = len([t for t in tasks if isinstance(t, dict) and t.get("status") == "done"]) if isinstance(tasks, list) else 0
    completed = max(state.get("plan_steps_completed", 0), done_count)
    result["plan_steps_total"] = total
    result["plan_steps_completed"] = completed
    logger.info("Plan progress: %d/%d (agent=%s)", completed, total, agent_name)

    if mark_analysis_complete and total > 0 and completed >= total:
        result["analysis_complete"] = True
        result["phase"] = "qa"
        logger.info("Pipeline complete -- entering Q&A mode.")


def _persist_friction_outputs(
    lens_ids: list[str],
    results: list[dict[str, Any]],
) -> dict[str, str]:
    """No-op in the new file-pointer model: lens outputs are written directly to lens_outputs_dir."""
    return {}


# ═══════════════════════════════════════════════════════════════════════════
# Section-based formatting pipeline
# ═══════════════════════════════════════════════════════════════════════════


def _build_section_formatting_message(
    section_key: str,
    section_data: dict[str, Any],
    synthesis_summary: dict[str, Any],
) -> str:
    """Build the HumanMessage content for a single section formatting call."""
    template_spec = section_data.get("template_spec", {})
    visual_hierarchy = section_data.get("visual_hierarchy", {})
    narrative_chunk = section_data.get("narrative_chunk", "")

    chart_placeholders = [
        "{{chart.friction_distribution}}",
        "{{chart.impact_ease_scatter}}",
        "{{chart.driver_breakdown}}",
    ]

    parts = [
        f"section_key: {section_key}",
        "",
        "--- TEMPLATE SPEC ---",
        json.dumps(template_spec, indent=2, default=str),
        "",
        "--- VISUAL HIERARCHY ---",
        json.dumps(visual_hierarchy, indent=2, default=str),
        "",
        "--- CHART PLACEHOLDERS ---",
        json.dumps(chart_placeholders),
        "",
        "--- SYNTHESIS SUMMARY (verification only) ---",
        json.dumps(synthesis_summary, indent=2, default=str),
        "",
        "--- NARRATIVE CHUNK ---",
        narrative_chunk,
    ]
    return "\n".join(parts)


def _validate_section_blueprint(result: dict[str, Any]) -> list[str]:
    """Validate a single section formatting agent output."""
    payload = result.get("formatting_output", {})
    full = payload.get("full_response", "") if isinstance(payload, dict) else ""
    data = _extract_json(full)

    if not isinstance(data, dict):
        return ["Section formatting output is not valid JSON."]

    slides = data.get("slides", [])
    if not isinstance(slides, list) or len(slides) < 1:
        return ["Section formatting output must include at least 1 slide."]

    section_key = data.get("section_key", "")
    expected_counts = {"exec_summary": 2, "impact": 3}
    expected = expected_counts.get(section_key)
    if expected and len(slides) != expected:
        return [f"Section '{section_key}' expected {expected} slides but got {len(slides)}."]

    return []


def _build_fallback_section_blueprint(
    section_key: str,
    section_data: dict[str, Any],
) -> dict[str, Any]:
    """Deterministic fallback: build section blueprint from narrative slide tags."""
    slide_blocks = section_data.get("slides", [])
    template_spec = section_data.get("template_spec", {})

    # Get default layout index from template spec
    default_layout = 1
    if "slides" in template_spec:
        spec_slides = template_spec["slides"]
        if spec_slides:
            default_layout = spec_slides[0].get("layout_index", 1)
    elif "per_theme_slide" in template_spec:
        default_layout = template_spec["per_theme_slide"].get("layout_index", 19)

    result_slides: list[dict[str, Any]] = []

    if section_key == "exec_summary":
        hook_blocks = [b for b in slide_blocks if "executive" in b.get("section_type", "").lower()]
        pain_blocks = [b for b in slide_blocks if "pain" in b.get("section_type", "").lower()]
        wins_blocks = [b for b in slide_blocks if "quick" in b.get("section_type", "").lower()]

        spec_slides = template_spec.get("slides", [])

        # Slide 1: Executive Summary with quick wins
        hook_title = "EXECUTIVE SUMMARY"
        hook_subtitle = hook_blocks[0].get("body", "")[:300] if hook_blocks else ""
        quick_wins: list[dict[str, str]] = []
        if wins_blocks:
            body = wins_blocks[0].get("body", "")
            for line in body.split("\n"):
                line = line.strip().lstrip("- ").strip()
                if line and len(quick_wins) < 3:
                    quick_wins.append({"action": line[:200], "detail": ""})
        result_slides.append({
            "slide_number": 1,
            "slide_role": "executive_summary",
            "layout_index": spec_slides[0].get("layout_index", 6) if spec_slides else 6,
            "title": hook_title,
            "subtitle_lines": [{"text": hook_subtitle, "bold_part": None}] if hook_subtitle else [],
            "quick_wins": quick_wins,
        })

        # Slide 2: Pain points (structured — cards array)
        cards: list[dict[str, Any]] = []
        for i, b in enumerate(pain_blocks[:3], start=1):
            title = b.get("title", f"Pain Point {i}")
            body = b.get("body", "")[:300]
            cards.append({
                "name": title,
                "calls": 0,
                "pct": "",
                "impact": 0,
                "priority": 0,
                "issue": body,
                "fix": "To be determined",
                "owner": "Digital/UX",
            })
        result_slides.append({
            "slide_number": 2,
            "slide_role": "pain_points",
            "layout_index": spec_slides[1].get("layout_index", 1) if len(spec_slides) > 1 else 1,
            "title": "Key Pain Points",
            "cards": cards if cards else [{"name": "No pain points", "calls": 0, "pct": "", "impact": 0, "priority": 0, "issue": "Pain points to be identified.", "fix": "TBD", "owner": "TBD"}],
        })

    elif section_key == "impact":
        matrix_blocks = [b for b in slide_blocks if "matrix" in b.get("section_type", "").lower() and "bet" not in b.get("section_type", "").lower()]
        rec_blocks = [b for b in slide_blocks if "recommend" in b.get("section_type", "").lower()]

        spec_slides = template_spec.get("slides", [])

        # Slide 1: Impact ease with themes array
        result_slides.append({
            "slide_number": 1,
            "slide_role": "impact_ease",
            "layout_index": spec_slides[0].get("layout_index", 51) if spec_slides else 51,
            "title": matrix_blocks[0].get("title", "Impact vs. Ease Analysis") if matrix_blocks else "Impact vs. Ease Analysis",
            "themes": [],  # filled by LLM; fallback empty
            "chart_placeholder": {"chart_key": "impact_ease_scatter", "position": "right"},
        })

        # Slide 2: Low hanging fruit
        result_slides.append({
            "slide_number": 2,
            "slide_role": "low_hanging_fruit",
            "layout_index": spec_slides[1].get("layout_index", 1) if len(spec_slides) > 1 else 1,
            "title": "Low Hanging Fruit",
            "items": [],  # filled by LLM; fallback empty
        })

        # Slide 3: Recommendations (structured — dimensions array)
        result_slides.append({
            "slide_number": 3,
            "slide_role": "recommendations",
            "layout_index": spec_slides[2].get("layout_index", 1) if len(spec_slides) > 2 else 1,
            "title": "Recommended Actions by Owning Team",
            "dimensions": [],  # filled by LLM; fallback empty
        })

    else:  # theme_deep_dives
        per_theme = template_spec.get("per_theme_slide", {})
        theme_layout = per_theme.get("layout_index", 19)
        # Group blocks by theme
        themes: dict[str, list[dict[str, Any]]] = {}
        current_theme = ""
        for b in slide_blocks:
            if b.get("section_type", "").lower() == "theme_divider":
                current_theme = b.get("title", "").replace(" — Deep Dive", "").replace(" - Deep Dive", "").strip()
            if current_theme:
                themes.setdefault(current_theme, []).append(b)

        max_themes = template_spec.get("max_themes", 10)
        for idx, (theme_name, blocks) in enumerate(list(themes.items())[:max_themes], start=1):
            # Extract body text from narrative blocks
            narrative_body = ""
            for b in blocks:
                if b.get("section_type", "").lower() == "theme_narrative":
                    narrative_body = b.get("body", "")[:500]
                    break
            if not narrative_body:
                narrative_body = " ".join(b.get("body", "")[:100] for b in blocks[:2])

            result_slides.append({
                "slide_number": idx,
                "slide_role": "theme_card",
                "layout_index": theme_layout,
                "title": theme_name,
                "stats_bar": {"calls": 0, "pct": "", "impact": 0, "ease": 0, "priority": 0},
                "left_column": {
                    "core_issue": narrative_body,
                    "primary_driver": "",
                    "solutions": [],
                },
                "right_column": {
                    "type": "driver_table",
                    "headers": ["Driver", "Calls"],
                    "rows": [],
                },
            })

    return {
        "section_key": section_key,
        "slides": result_slides,
    }


# ═══════════════════════════════════════════════════════════════════════════
# Fixed deck blueprint builder (deterministic — no LLM)
# ═══════════════════════════════════════════════════════════════════════════


def _build_fixed_deck_blueprint(
    synthesis_result: dict[str, Any],
    findings: list[dict[str, Any]],
    classified_solutions: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Build a fixed-structure deck blueprint directly from synthesis data.

    No LLM involved. Maps synthesis themes/findings to a predictable slide
    layout that the PPTX builder renders deterministically.

    Fixed deck structure:
      exec_summary (2 slides):
        1. Executive Hook + Quick Wins
        2. Top 3 Pain Points
      impact (3 slides):
        3. Impact vs Ease Matrix (table + scatter chart)
        4. Biggest Bet / Impact Statement
        5. Recommendations by Owning Team
      theme_deep_dives (1 per theme, max 10):
        6+. Theme Card (LEFT: metrics + solutions table,
                        RIGHT: driver breakdown table)

    To customize the deck layout, edit the slide definitions below.
    Each slide's layout_index maps to a python-pptx slide layout in template.pptx.
    """
    themes: list[dict[str, Any]] = []
    if isinstance(synthesis_result, dict):
        raw = synthesis_result.get("themes", [])
        themes = raw if isinstance(raw, list) else []

    # synthesis_result is FLAT (SynthesisSummary fields at top level, no "summary" key)
    # but handle both cases: flat dict or nested under "summary"
    summary: dict[str, Any] = {}
    if isinstance(synthesis_result, dict):
        s = synthesis_result.get("summary", synthesis_result)
        summary = s if isinstance(s, dict) else synthesis_result

    if not isinstance(findings, list):
        findings = []

    # -- value helpers --
    def _s(val: Any, default: str = "") -> str:
        return str(val).strip() if val else default

    def _n(val: Any, default: int = 0) -> int:
        try:
            return int(float(val))
        except (TypeError, ValueError):
            return default

    def _f(val: Any, default: float = 0.0) -> float:
        try:
            return round(float(val), 1)
        except (TypeError, ValueError):
            return default

    def _call_text(item: dict[str, Any]) -> str:
        """Build human-readable call volume string with fallback."""
        cc = _n(item.get("call_count", 0))
        cp = _f(item.get("call_percentage", 0))
        vol = _f(item.get("volume", 0))
        if cc > 0:
            return f"{cc:,} calls" + (f" ({cp}%)" if cp > 0 else "")
        if cp > 0:
            return f"{cp}% of call volume"
        if vol > 0:
            return f"{vol}% volume"
        return "See impact score"

    def _norm_driver(d: Any) -> dict[str, Any]:
        """Normalize a single driver entry to a dict with 'driver' key."""
        if isinstance(d, str):
            # Try JSON parse first
            try:
                parsed = json.loads(d)
                if isinstance(parsed, dict):
                    d = parsed
                else:
                    return {"driver": d}
            except (json.JSONDecodeError, ValueError):
                return {"driver": d}
        if not isinstance(d, dict):
            return {"driver": str(d) if d else ""}
        # Map alternate field names → 'driver'
        if not d.get("driver"):
            d["driver"] = (
                d.get("driver_description", "")
                or d.get("finding", "")
                or d.get("description", "")
                or ""
            )
        if not d.get("call_count"):
            d["call_count"] = (
                d.get("calls")
                or d.get("call_volume")
                or d.get("n_calls")
                or d.get("volume_calls")
                or d.get("count")
                or 0
            )
        return d

    def _norm_drivers(t: dict[str, Any]) -> list[dict[str, Any]]:
        """Normalize all_drivers from a theme dict."""
        raw = t.get("all_drivers", []) or []
        return [_norm_driver(d) for d in raw if d]

    def _theme_name(t: dict[str, Any], fallback: str = "Unnamed Theme") -> str:
        """Extract theme name with multiple fallbacks."""
        name = _s(t.get("theme", "")) or _s(t.get("theme_name", "")) or _s(t.get("bucket_name", ""))
        if not name:
            drivers = _norm_drivers(t)
            if drivers:
                name = _s(drivers[0].get("driver", ""))[:60]
        return name or fallback

    def _driver_text(d: Any) -> str:
        """Extract driver description — handles dict or string."""
        if isinstance(d, dict):
            return _s(d.get("driver", "") or d.get("driver_description", ""))
        return _s(d)

    def _findings_for_theme(theme_name: str) -> list[dict[str, Any]]:
        """Return findings matching a theme name (case-insensitive, substring match)."""
        tn = theme_name.lower().strip()
        return [
            f for f in findings
            if isinstance(f, dict) and tn in _s(f.get("theme", "")).lower()
        ]

    def _cs_for_theme(theme_name: str) -> list[dict[str, Any]]:
        """Return classified solutions matching a theme name (case-insensitive)."""
        if not classified_solutions:
            return []
        tn = theme_name.lower().strip()
        return [s for s in classified_solutions if tn in _s(s.get("theme", "")).lower()]

    total_calls = _n(summary.get("total_calls_analyzed", 0))
    total_themes = _n(summary.get("total_themes", len(themes)))
    exec_narrative = _s(
        summary.get("executive_narrative", ""),
        "Friction analysis complete.",
    )
    preventability = _f(summary.get("overall_preventability", 0.0))

    # Collect quick wins across all themes (prefer quick_wins, fallback to driver solutions)
    all_quick_wins: list[str] = []
    for t in themes:
        if not isinstance(t, dict):
            continue
        t_name = _theme_name(t)
        for qw in t.get("quick_wins", []) or []:
            if qw and len(all_quick_wins) < 5:
                all_quick_wins.append(f"{str(qw)[:160]} — {t_name}")
        # If no quick_wins, pull from all_drivers recommended_solution
        if not (t.get("quick_wins", []) or []):
            for d in _norm_drivers(t)[:2]:
                if d.get("recommended_solution") and len(all_quick_wins) < 5:
                    all_quick_wins.append(f"{_s(d['recommended_solution'])[:160]} — {t_name}")

    # Sort findings by composite score — filter out findings with empty text
    sorted_findings = sorted(
        [f for f in findings if isinstance(f, dict) and _s(f.get("finding", ""))],
        key=lambda x: (_n(x.get("call_count", 0)) * 100 + _f(x.get("impact_score", 0))),
        reverse=True,
    )[:3]
    # If no usable findings, build pain points from themes + their all_drivers
    if not sorted_findings and themes:
        for t in themes[:3]:
            if not isinstance(t, dict):
                continue
            # Use top driver description as the finding text (much richer than theme name alone)
            t_drivers = _norm_drivers(t)
            top_driver = t_drivers[0] if t_drivers else {}
            finding_text = _s(top_driver.get("driver", ""), _s(t.get("theme", ""), "Issue"))
            action_text = _s(
                top_driver.get("recommended_solution", ""),
                "; ".join(str(qw) for qw in (t.get("quick_wins", []) or [])[:2]) or "Action to be determined",
            )
            sorted_findings.append({
                "finding": finding_text,
                "call_count": _n(top_driver.get("call_count", 0) if top_driver else t.get("call_count", 0)),
                "call_percentage": _f(t.get("call_percentage", 0)),
                "impact_score": _f(t.get("impact_score", 5)),
                "dominant_driver": _s(t.get("dominant_driver", ""), "digital"),
                "recommended_action": action_text,
            })


    # ================================================================
    # SECTION 1: EXECUTIVE SUMMARY (2 slides)
    # ================================================================

    pain_cards: list[dict[str, Any]] = []
    for i, f in enumerate(sorted_findings, 1):
        finding_text = _s(f.get("finding", ""), f"Finding {i}")
        impact = _f(f.get("impact_score", 0))
        action = _s(f.get("recommended_action", ""), "To be determined")
        cc = _n(f.get("call_count", 0))
        cp = _f(f.get("call_percentage", 0))
        # Shorten name to ~12 words for card title
        words = finding_text.split()
        short_name = " ".join(words[:12]) + ("..." if len(words) > 12 else "")
        # Extract owner from [Bracket] prefix in action, or use dominant_driver
        owner = _s(f.get("dominant_driver", ""), "unknown").replace("_", " ").title()
        if action.startswith("["):
            bracket_end = action.find("]")
            if bracket_end > 0:
                owner = action[1:bracket_end].strip()
                action = action[bracket_end + 1:].strip()
        pain_cards.append({
            "name": f"{i}. {short_name}",
            "calls": cc,
            "pct": f"{cp}%" if cp > 0 else "",
            "impact": impact,
            "priority": impact,
            "issue": finding_text,
            "fix": action[:200],
            "owner": owner,
        })

    # Build subtitle lines for executive summary — verbose hook + 3 key pointers
    subtitle_lines: list[dict[str, Any]] = []
    # Hook line: bold narrative
    if exec_narrative and exec_narrative != "Friction analysis complete.":
        subtitle_lines.append({"text": exec_narrative, "bold_part": None})
    elif total_calls > 0:
        subtitle_lines.append({"text": f"Analysis of {total_calls:,} friction-related customer calls across {total_themes} themes reveals significant self-service gaps and preventable call drivers.", "bold_part": None})
    # 3 key pointers from top themes
    for pi, t in enumerate(themes[:3]):
        if not isinstance(t, dict):
            continue
        t_name = _theme_name(t)
        t_calls = _n(t.get("call_count", 0))
        t_pct = _f(t.get("call_percentage", 0))
        t_impact = _f(t.get("impact_score", 0))
        pct_str = f"{t_pct}%" if t_pct > 0 else ""
        pointer = f"{t_name}: {t_calls:,} calls ({pct_str}) — Impact {t_impact}/10"
        subtitle_lines.append({"text": f"  {pi + 1}. {pointer}", "bold_part": t_name})
    # Preventability line
    if preventability > 0:
        pct_text = f"{preventability:.0%}"
        subtitle_lines.append({"text": f"{pct_text} of total volume is deflectable with easy implementations.", "bold_part": pct_text})

    # Build quick wins as {action, detail} objects
    qw_objects: list[dict[str, str]] = []
    for qw in all_quick_wins[:3]:
        # Try to split "action — theme — detail" format
        parts = str(qw).split(" — ", 1)
        if len(parts) == 2:
            qw_objects.append({"action": parts[0].strip(), "detail": parts[1].strip()})
        else:
            qw_objects.append({"action": str(qw)[:200], "detail": ""})

    exec_section = {
        "section_key": "exec_summary",
        "slides": [
            {
                "slide_number": 1,
                "slide_role": "executive_summary",
                "layout_index": 1,
                "title": "EXECUTIVE SUMMARY",
                "subtitle_lines": subtitle_lines,
                "quick_wins": qw_objects,
            },
            {
                "slide_number": 2,
                "slide_role": "pain_points",
                "layout_index": 1,
                "title": "Critical Pain Points",
                "cards": pain_cards if pain_cards else [{"name": "No significant pain points", "calls": 0, "pct": "", "impact": 0, "priority": 0, "issue": "No significant pain points identified.", "fix": "TBD", "owner": "TBD"}],
            },
        ],
    }

    # ================================================================
    # SECTION 2: IMPACT (3 slides: matrix + low-hanging fruit + recs)
    # ================================================================

    # Build impact matrix themes array
    impact_themes: list[dict[str, Any]] = []
    for t in themes[:10]:
        if not isinstance(t, dict):
            continue
        impact_themes.append({
            "name": _theme_name(t, "?")[:40],
            "calls": _n(t.get("call_count", 0)),
            "impact": _f(t.get("impact_score", 0)),
            "ease": _f(t.get("ease_score", 0)),
            "priority": _f(t.get("priority_score", 0)),
            "quadrant": _s(t.get("priority_quadrant", ""), "?").replace("_", " ").title(),
        })

    # Build low hanging fruit: pick 3 themes with highest ease score
    ease_sorted = sorted(
        [t for t in themes if isinstance(t, dict)],
        key=lambda x: _f(x.get("ease_score", 0)),
        reverse=True,
    )[:3]
    lhf_items: list[dict[str, Any]] = []
    for t in ease_sorted:
        theme_name_s = _theme_name(t)
        t_qw = (t.get("quick_wins", []) or [])
        t_drivers = _norm_drivers(t)
        # Action: prefer quick_wins, then top driver solution, then generic
        if t_qw:
            sol_action = str(t_qw[0])[:200]
        elif t_drivers and t_drivers[0].get("recommended_solution"):
            sol_action = _s(t_drivers[0]["recommended_solution"])[:200]
        else:
            sol_action = f"Address {theme_name_s} friction"
        # Detail: prefer additional quick_wins/solutions, then ease score
        extra_solutions = []
        for qw in t_qw[1:3]:
            extra_solutions.append(str(qw)[:80])
        if not extra_solutions:
            for d in t_drivers[:2]:
                if d.get("recommended_solution"):
                    extra_solutions.append(_s(d["recommended_solution"])[:80])
        sol_detail = "; ".join(extra_solutions) if extra_solutions else f"Ease score: {_f(t.get('ease_score', 0))}/10"
        lhf_items.append({
            "action": sol_action,
            "detail": sol_detail,
            "impact": f"Resolves ~{_n(t.get('call_count', 0))} calls from {theme_name_s}",
            "ease": _f(t.get("ease_score", 0)),
            "theme": theme_name_s,
        })

    # Build recommendations grouped by owning team — use all_drivers with proper dimension
    driver_groups: dict[str, list[dict[str, Any]]] = {
        "digital": [],
        "operations": [],
        "communication": [],
        "policy": [],
    }
    # Primary: use theme all_drivers grouped by their actual dimension
    for t in themes:
        if not isinstance(t, dict):
            continue
        t_drivers = _norm_drivers(t)
        for d in t_drivers:
            dim = _s(d.get("dimension", "digital")).lower()
            if dim not in driver_groups:
                dim = "digital"
            sol = _s(d.get("recommended_solution", ""))
            if sol:
                driver_groups[dim].append({
                    "recommended_action": sol,
                    "call_count": _n(d.get("call_count", 0)),
                })
        # Also add quick_wins under dominant_driver if no all_drivers provided solutions
        if not t_drivers:
            driver = _s(t.get("dominant_driver", "digital")).lower()
            if driver not in driver_groups:
                driver = "digital"
            for qw in (t.get("quick_wins", []) or [])[:2]:
                driver_groups[driver].append({"recommended_action": str(qw)})
    # Supplement with classified_solutions (curated, have explicit dimension ownership)
    for cs in (classified_solutions or []):
        if not isinstance(cs, dict):
            continue
        dim_raw = _s(cs.get("dimension", "digital")).lower()
        # Normalize common dimension variants
        if "digital" in dim_raw or "ux" in dim_raw:
            dim = "digital"
        elif "oper" in dim_raw:
            dim = "operations"
        elif "comm" in dim_raw:
            dim = "communication"
        elif "polic" in dim_raw:
            dim = "policy"
        else:
            dim = "digital"
        action = _s(cs.get("recommended_action", ""))
        if action:
            driver_groups[dim].append({
                "recommended_action": action,
                "call_count": 0,
                "classification": _s(cs.get("classification", "")),
            })
    # Fallback: use findings grouped by dominant_driver
    if not any(driver_groups.values()):
        for f in findings[:30]:
            if not isinstance(f, dict):
                continue
            action = _s(f.get("recommended_action", ""))
            if not action:
                continue
            # Parse [Dimension] prefix from action text if present
            dim = _s(f.get("dominant_driver", "digital")).lower()
            if action.startswith("["):
                bracket_end = action.find("]")
                if bracket_end > 0:
                    parsed_dim = action[1:bracket_end].strip().lower().replace(" / ux", "").replace(" ", "_")
                    if parsed_dim in driver_groups:
                        dim = parsed_dim
            if dim not in driver_groups:
                dim = "digital"
            driver_groups[dim].append(f)

    rec_dimensions: list[dict[str, Any]] = []
    dim_color_map = {
        "digital": ("Digital / UX", "006BA6"),
        "operations": ("Operations", "2C5F2D"),
        "communication": ("Communications", "E67E22"),
        "policy": ("Policy", "8E44AD"),
    }
    for driver_key, (dim_name, dim_color) in dim_color_map.items():
        items = driver_groups.get(driver_key, [])
        if not items:
            continue
        dim_actions: list[dict[str, Any]] = []
        for item in items[:2]:
            action_text = _s(item.get("recommended_action", ""), "TBD")[:200]
            # Strip [Dimension] prefix — dimension is already shown by the card
            if action_text.startswith("["):
                bracket_end = action_text.find("]")
                if bracket_end > 0:
                    action_text = action_text[bracket_end + 1:].strip()
            cc = _n(item.get("call_count", 0))
            detail = f"Resolves {cc} calls" if cc > 0 else ""
            dim_actions.append({"title": action_text, "detail": detail})
        rec_dimensions.append({
            "name": dim_name,
            "actions": dim_actions,
        })

    impact_section = {
        "section_key": "impact",
        "slides": [
            {
                "slide_number": 3,
                "slide_role": "impact_ease",
                "layout_index": 1,
                "title": "Impact vs. Ease \u2014 Full Theme Prioritization",
                "themes": impact_themes,
                "chart_placeholder": {
                    "chart_key": "impact_ease_scatter",
                    "position": "right",
                },
            },
            {
                "slide_number": 4,
                "slide_role": "low_hanging_fruit",
                "layout_index": 1,
                "title": "Low Hanging Fruit",
                "items": lhf_items,
            },
            {
                "slide_number": 5,
                "slide_role": "recommendations",
                "layout_index": 1,
                "title": "Recommended Actions by Owning Team",
                "dimensions": rec_dimensions if rec_dimensions else [],
            },
        ],
    }

    # ================================================================
    # SECTION 3: THEME DEEP DIVES (1 slide per theme, max 10)
    #   Layout: LEFT table (metrics + solutions) | RIGHT table (drivers)
    # ================================================================

    theme_slides: list[dict[str, Any]] = []
    for idx, t in enumerate(themes[:10], start=6):
        if not isinstance(t, dict):
            continue
        theme_name = _theme_name(t, f"Theme {idx - 5}")

        # -- LEFT TABLE: Theme Metrics + Key Solutions --
        metrics_rows: list[list[str]] = [
            ["Calls", _call_text(t)],
            ["Impact Score", f"{_f(t.get('impact_score', 0))}/10"],
            ["Ease Score", f"{_f(t.get('ease_score', 0))}/10"],
            ["Priority Score", str(_f(t.get("priority_score", 0)))],
            ["Quadrant", _s(t.get("priority_quadrant", ""), "?").replace("_", " ").title()],
            ["Primary Driver", _s(t.get("dominant_driver", ""), "?").replace("_", " ").title()],
            ["Preventability", f"{_f(t.get('preventability_score', 0)) * 100:.0f}%"],
        ]
        # Append contributing factors as rows
        factors = t.get("contributing_factors", [])
        if isinstance(factors, list):
            for ci, cf in enumerate(factors[:3], 1):
                metrics_rows.append([f"Factor {ci}", str(cf)[:80]])
        # Append quick wins / key solutions as rows
        theme_qw = t.get("quick_wins", [])
        if isinstance(theme_qw, list):
            for qi, qw in enumerate(theme_qw[:3], 1):
                metrics_rows.append([f"Solution {qi}", str(qw)[:80]])

        # Build structured theme card
        impact_score = _f(t.get("impact_score", 0))
        ease_score = _f(t.get("ease_score", 0))
        priority_score = _f(t.get("priority_score", 0))
        call_count = _n(t.get("call_count", 0))
        call_pct = _f(t.get("call_percentage", 0))
        primary_driver = _s(t.get("dominant_driver", ""), "").replace("_", " ").title()

        # Core issue: use findings (full narrative sentences with real call counts)
        theme_findings = _findings_for_theme(theme_name)
        core_issue_points: list[str] = []
        for f in theme_findings[:3]:
            desc = _s(f.get("finding", ""))
            fc = _n(f.get("call_count", 0))
            if desc:
                core_issue_points.append(f"{desc} ({fc} calls)" if fc > 0 else desc)
        if not core_issue_points:
            # Fallback: contributing_factors, then generic label
            factors = t.get("contributing_factors", [])
            for cf in (factors if isinstance(factors, list) else [])[:3]:
                txt = _s(cf)[:80]
                if txt:
                    core_issue_points.append(txt)
        if not core_issue_points:
            core_issue_points = [f"{theme_name} friction identified"]
        core_issue = "\n".join(f"• {pt}" for pt in core_issue_points)

        # Solutions: classified_solutions first (curated, have dimension + classification),
        # then quick_wins as fallback
        dim_label = _s(t.get("dominant_driver", "Digital")).replace("_", " ").title()
        solutions: list[dict[str, Any]] = []
        for cs in _cs_for_theme(theme_name)[:3]:
            action = _s(cs.get("recommended_action", ""))
            if action:
                dim = _s(cs.get("dimension", dim_label)).replace("_", " ").title()
                classification = _s(cs.get("classification", ""))
                solutions.append({"action": action[:200], "dimension": dim, "classification": classification})
        for qw in (t.get("quick_wins", []) or []):
            if len(solutions) >= 3:
                break
            solutions.append({"action": str(qw)[:200], "dimension": dim_label})

        # Evidence table: findings with real call counts
        evidence_rows: list[list[Any]] = []
        for f in theme_findings[:6]:
            evidence_rows.append([
                _s(f.get("finding", ""))[:65] or "?",
                _n(f.get("call_count", 0)),
                _s(f.get("dominant_driver", ""), "?").replace("_", " ").title(),
                _s(f.get("recommended_action", ""), "-")[:60],
            ])

        theme_slides.append({
            "slide_number": idx,
            "slide_role": "theme_card",
            "layout_index": 1,
            "title": theme_name,
            "stats_bar": {
                "calls": call_count,
                "pct": f"{call_pct}%" if call_pct > 0 else "",
                "impact": impact_score,
                "ease": ease_score,
                "priority": priority_score,
            },
            "left_column": {
                "core_issue": core_issue,
                "primary_driver": primary_driver,
                "solutions": solutions,
            },
            "right_column": {
                "type": "evidence_table",
                "headers": ["Evidence / Finding", "Calls", "Dimension", "Recommended Action"],
                "rows": evidence_rows,
            },
        })

    theme_section = {
        "section_key": "theme_deep_dives",
        "slides": theme_slides,
    }

    return [exec_section, impact_section, theme_section]


def _run_section_artifact_writer(
    state: AnalyticsState,
) -> dict[str, Any]:
    """Deterministic artifact writer using section-based PPTX builder.

    Reads narrative_path and blueprint_path from state (new file-pointer model).
    OPT-4: Charts and CSV export run in parallel via threads, then PPTX
    (which needs chart paths) runs after charts complete.
    """
    import concurrent.futures
    from utils.pptx_builder import build_pptx_from_sections

    # 1. Read narrative markdown from narrative_path file
    narrative_path = state.get("narrative_path", "")
    narrative_markdown = _read_text(narrative_path).strip() if narrative_path else ""
    if not narrative_markdown:
        narrative_markdown = "# Analysis Report\n\nNo narrative markdown was generated."

    # 2. Read section blueprints from blueprint_path file
    blueprint_path = state.get("blueprint_path", "")
    section_blueprints: list[dict[str, Any]] = _read_json(blueprint_path) if blueprint_path else []
    if not isinstance(section_blueprints, list):
        section_blueprints = []

    # 4. Load template catalog for visual hierarchy
    catalog_path = Path(__file__).resolve().parent.parent / "data" / "input" / "template_catalog.json"
    catalog = json.loads(catalog_path.read_text(encoding="utf-8")) if catalog_path.exists() else {}
    visual_hierarchy = catalog.get("visual_hierarchy")

    # 3. Set up output directory (artifacts_dir)
    output_dir = _thread_output_dir()
    output_dir.mkdir(parents=True, exist_ok=True)
    artifacts_dir = str(output_dir)

    # 4. Write narrative markdown to artifacts_dir/complete_analysis.md
    markdown_path = str(output_dir / "complete_analysis.md")
    Path(markdown_path).write_text(narrative_markdown, encoding="utf-8")

    # OPT-4: Run charts + CSV export in parallel threads.
    # Resolve output dirs here (main thread has Chainlit context) so that
    # spawned threads don't need cl.user_session.
    _tid = state.get("thread_id", "") or str(cl.user_session.get("thread_id") or "unknown_thread")
    _csv_output_dir = artifacts_dir

    def _generate_charts() -> dict[str, Any]:
        return _build_deterministic_dataviz_output(state)

    def _export_csv() -> str:
        csv_tool = TOOL_REGISTRY["export_filtered_csv"]
        csv_raw = csv_tool.invoke({"output_dir": _csv_output_dir})
        csv_data = _extract_json(str(csv_raw))
        return _resolve_existing_path(str(csv_data.get("csv_path", "")).strip())

    def _export_docx() -> str:
        from utils.docx_export import markdown_to_docx as _md_to_docx
        docx_path = str(output_dir / "report.docx")
        return _md_to_docx(narrative_markdown, docx_path)

    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        chart_future = pool.submit(_generate_charts)
        csv_future = pool.submit(_export_csv)
        docx_future = pool.submit(_export_docx)
        dataviz_result = chart_future.result()
        data_path = csv_future.result()
        docx_path = docx_future.result()

    dataviz_errors = _validate_dataviz(dataviz_result)
    if dataviz_errors:
        raise RuntimeError(f"Deterministic DataViz generation failed: {dataviz_errors}")

    # 5. Build chart paths map (needs charts to be done)
    dataviz_json = _extract_json(
        dataviz_result.get("dataviz_output", {}).get("full_response", "")
        if isinstance(dataviz_result.get("dataviz_output", {}), dict) else ""
    )
    chart_paths = _build_chart_paths_map(dataviz_json)

    # 6. Build PPTX from section blueprints (needs chart paths)
    from config import PPTX_TEMPLATE_PATH
    pptx_path = str(output_dir / "report.pptx")
    template_path = PPTX_TEMPLATE_PATH if Path(PPTX_TEMPLATE_PATH).exists() else ""

    build_pptx_from_sections(
        section_blueprints=section_blueprints,
        chart_paths=chart_paths,
        output_path=pptx_path,
        template_path=template_path,
        visual_hierarchy=visual_hierarchy,
    )
    report_path = pptx_path if Path(pptx_path).exists() else ""
    logger.info("Section-based PPTX built: %s", report_path)

    summary_text = (
        f"Artifacts written to {artifacts_dir}: "
        f"PPTX={Path(pptx_path).name}, "
        f"Word={Path(docx_path).name if docx_path else 'N/A'}, "
        f"CSV={Path(data_path).name if data_path else 'N/A'}, "
        f"MD=complete_analysis.md"
    )
    logger.info("Section artifact writer completed: %s", summary_text)
    return {
        "messages": [AIMessage(content=summary_text)],
        "reasoning": [{
            "step_name": "Artifact Writer",
            "step_text": "Built PPTX, Word report, markdown, and exported filtered CSV.",
            "agent": "artifact_writer_node",
        }],
        "artifacts_dir": artifacts_dir,
    }

