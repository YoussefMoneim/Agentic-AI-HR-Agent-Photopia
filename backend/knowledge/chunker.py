"""
Document chunking for the feeder/design agent.

Two strategies:
1. Section-based (primary): splits on ## headings and numbered sections.
   Matches the existing ingest_policies.py behavior but handles Arabic headers too.
   Each section = one chunk = one complete semantic unit.

2. Fixed-size with overlap (fallback): when no section structure detected.
   Respects sentence boundaries (English and Arabic).

MAX_CHUNK_CHARS = 3200 matches the existing ingest_policies.py constant
so behavior is consistent with what's already running.
"""
from __future__ import annotations
import os
import re
import logging

_log = logging.getLogger(__name__)

MAX_CHUNK_CHARS = 3200
OVERLAP_CHARS = 150
MIN_CHUNK_CHARS = 50


def canonical_document_id(source_path_or_name: str) -> str:
    """
    Canonical document ID — strip path, extension, normalize.

    Ingestion paths (local policies/, SharePoint) each pass a different raw
    string as document_name (filename stem, human-readable title, etc.).
    Without normalizing to a single canonical form, the same logical document
    ingested via two paths gets two different document_ids, so re-ingestion
    never deduplicates and chunks accumulate.

    'policies/public/03_leave_policy.md' -> '03_leave_policy'
    'WIN Holding Leave Policy 2025'      -> 'win_holding_leave_policy_2025'
    'leaves_policy_egypt_v2.pdf'         -> 'leaves_policy_egypt_v2'
    """
    name = os.path.basename(source_path_or_name)
    name = os.path.splitext(name)[0]
    name = name.lower().strip()
    name = re.sub(r'[^a-z0-9]+', '_', name)
    name = name.strip('_')
    return name


def chunk_document(content: str, document_name: str) -> list[str]:
    """
    Split document into semantically meaningful chunks.
    Returns list of non-empty text strings.
    """
    content = content.strip()
    if not content:
        return []

    # Try section-based first (matches existing ingest_policies.py approach)
    chunks = _chunk_by_sections(content)
    if len(chunks) >= 2:
        _log.info("chunker: '%s' → %d section-based chunks", document_name, len(chunks))
        return chunks

    chunks = _chunk_fixed_size(content)
    _log.info(
        "chunker: '%s' → %d fixed-size chunks (no headings detected)",
        document_name, len(chunks)
    )
    return chunks


def _chunk_by_sections(content: str) -> list[str]:
    """Split on ## headings — same boundary as ingest_policies.py."""
    # Matches ## Markdown headers and numbered sections (Latin + Arabic chars)
    pattern = re.compile(
        r'^(?:'
        r'#{1,4}\s+.+|'
        r'\d+(?:\.\d+)*\.?\s+[\w؀-ۿ].+'
        r')',
        re.MULTILINE
    )
    matches = list(pattern.finditer(content))
    if len(matches) < 2:
        return []

    chunks = []
    for i, match in enumerate(matches):
        start = match.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
        text = content[start:end].strip()
        if len(text) < MIN_CHUNK_CHARS:
            continue
        if len(text) > MAX_CHUNK_CHARS:
            chunks.extend(_split_long_section(text))
        else:
            chunks.append(text)

    return [c for c in chunks if len(c) >= MIN_CHUNK_CHARS]


def _split_long_section(text: str) -> list[str]:
    paragraphs = re.split(r'\n{2,}', text)
    chunks, current = [], ""
    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        if len(current) + len(para) + 2 <= MAX_CHUNK_CHARS:
            current = (current + "\n\n" + para).strip()
        else:
            if current:
                chunks.append(current)
            if len(para) > MAX_CHUNK_CHARS:
                chunks.extend(_split_by_sentences(para))
                current = ""
            else:
                current = para
    if current:
        chunks.append(current)
    return chunks


def _split_by_sentences(text: str) -> list[str]:
    sentences = re.split(r'(?<=[.!?؟])\s+', text)
    chunks, current = [], ""
    for sent in sentences:
        if len(current) + len(sent) + 1 <= MAX_CHUNK_CHARS:
            current = (current + " " + sent).strip()
        else:
            if current:
                chunks.append(current)
            current = sent
    if current:
        chunks.append(current)
    return chunks


def _chunk_fixed_size(content: str) -> list[str]:
    chunks, start = [], 0
    while start < len(content):
        end = start + MAX_CHUNK_CHARS
        if end >= len(content):
            chunk = content[start:].strip()
        else:
            for delim in ['. ', '.\n', '؟ ', '! ']:
                cutoff = content.rfind(delim, start, end)
                if cutoff > start:
                    end = cutoff + len(delim)
                    break
            chunk = content[start:end].strip()
        if len(chunk) >= MIN_CHUNK_CHARS:
            chunks.append(chunk)
        start = end - OVERLAP_CHARS if end < len(content) else len(content)
    return chunks
