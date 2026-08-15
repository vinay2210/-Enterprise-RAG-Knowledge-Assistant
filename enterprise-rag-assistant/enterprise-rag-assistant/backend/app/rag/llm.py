"""
LLM provider abstraction for answer generation.
Supports OpenAI, Anthropic, and Ollama (fully local/free) behind one
generate(prompt) -> str interface, and a streaming variant for the bonus
"streaming responses" feature.
"""
from typing import Iterator

import tiktoken

from app.config import get_settings
from app.utils.logger import logger

settings = get_settings()
_encoding = tiktoken.get_encoding("cl100k_base")

SYSTEM_PROMPT = """You are an enterprise knowledge assistant. Answer the user's question
using ONLY the information in the provided context chunks. Each chunk is labeled with
its source document and page number.

Rules:
- If the answer is not contained in the context, say you don't have enough information -
  do not make anything up.
- Cite sources inline like this: (DocumentName, p.PageNumber) right after each claim.
- Be concise and directly answer the question first, then add supporting detail.
- When the context contains information from multiple pages or sections, synthesize
  a coherent answer that draws from all relevant parts.
- If a question asks about a specific topic, focus your answer on that topic even if
  the context contains other information.
"""

# Maximum tokens of context to feed to the LLM to avoid overwhelming the model
# or exceeding context windows. Prioritize high-scoring chunks.
_MAX_CONTEXT_TOKENS = 6000


def _build_prompt(question: str, context_chunks: list[dict]) -> str:
    """Build a prompt with smart context assembly:
    - Deduplicates identical parent_text content (multiple child chunks from the same page)
    - Prioritizes parent_text for highest-scoring chunks, child text for lower-scoring ones
    - Caps total context to _MAX_CONTEXT_TOKENS to stay within model limits
    """
    formatted_excerpts = []
    seen_parent_texts = set()
    total_tokens = 0

    for c in context_chunks:
        # For higher-scoring chunks, prefer parent_text (richer context).
        # Deduplicate identical parent_text (multiple chunks from same page produce same parent).
        parent_text = c.get("parent_text") or ""
        child_text = c.get("text", "")
        sec = f" | Section: {c['section_title']}" if c.get("section_title") else ""
        header = f"[Source: {c['file_name']}, Page {c['page_number']}{sec}]"

        # Decide which text to use: parent_text gives more context but may be repeated
        # Use the complete context as the deduplication key.  Prefix-only
        # hashes can collapse different parts of a long page that happen to
        # start alike, hiding the answer after retrieval found it.
        parent_hash = parent_text if parent_text else None

        if parent_text and parent_hash not in seen_parent_texts:
            text_to_use = parent_text
            seen_parent_texts.add(parent_hash)
        else:
            # Either parent_text is empty, or we already included it from another chunk
            # on the same page. Use the child text instead (it's unique per chunk).
            text_to_use = child_text

        # Check token budget
        excerpt = f"{header}\n{text_to_use}"
        excerpt_tokens = len(_encoding.encode(excerpt))

        if total_tokens + excerpt_tokens > _MAX_CONTEXT_TOKENS:
            # Try with just child text (smaller) if parent was too big
            if text_to_use == parent_text and child_text:
                excerpt = f"{header}\n{child_text}"
                excerpt_tokens = len(_encoding.encode(excerpt))
                if total_tokens + excerpt_tokens > _MAX_CONTEXT_TOKENS:
                    break
            else:
                break

        formatted_excerpts.append(excerpt)
        total_tokens += excerpt_tokens

    context_block = "\n\n---\n\n".join(formatted_excerpts)
    return f"CONTEXT:\n{context_block}\n\nQUESTION: {question}\n\nANSWER:"


def _fallback_answer(context_chunks: list[dict], reason: str | None = None) -> str:
    if not context_chunks:
        return "I couldn't find anything relevant in the indexed documents."

    intro = "I couldn't use the configured language model right now, so here are the most relevant excerpts I found."
    if reason:
        intro = f"{intro} ({reason})"

    excerpts = []
    for chunk in context_chunks[:3]:
        text = " ".join(chunk["text"].split())
        if len(text) > 320:
            text = text[:320].rstrip() + "..."
        page = chunk.get("page_number")
        page_label = f" p.{page}" if page is not None else ""
        excerpts.append(f"- {chunk.get('file_name', 'Document')}{page_label}: {text}")

    return "\n".join([intro, *excerpts])


def generate(question: str, context_chunks: list[dict]) -> str:
    prompt = _build_prompt(question, context_chunks)

    if settings.llm_provider == "gemini":
        if not settings.gemini_api_key:
            return _fallback_answer(context_chunks, "GEMINI_API_KEY is not set")
        try:
            return _generate_gemini(question, context_chunks)
        except Exception as e:
            logger.warning(f"Gemini generation failed, falling back to excerpts: {e}")
            return _fallback_answer(context_chunks, str(e))

    if settings.llm_provider == "anthropic":
        if not settings.anthropic_api_key:
            return _fallback_answer(context_chunks, "ANTHROPIC_API_KEY is not set")
        try:
            return _generate_anthropic(prompt)
        except Exception as e:
            logger.warning(f"Anthropic generation failed, falling back to excerpts: {e}")
            return _fallback_answer(context_chunks, str(e))
    if settings.llm_provider == "ollama":
        try:
            return _generate_ollama(prompt)
        except Exception as e:
            logger.warning(f"Ollama generation failed, falling back to excerpts: {e}")
            return _fallback_answer(context_chunks, str(e))
    if not settings.openai_api_key:
        return _fallback_answer(context_chunks, "OPENAI_API_KEY is not set")
    try:
        return _generate_openai(prompt)
    except Exception as e:
        logger.warning(f"OpenAI generation failed, falling back to excerpts: {e}")
        return _fallback_answer(context_chunks, str(e))


def _generate_openai(prompt: str) -> str:
    from openai import OpenAI
    client = OpenAI(api_key=settings.openai_api_key)
    resp = client.chat.completions.create(
        model=settings.llm_model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        temperature=0.2,
    )
    return resp.choices[0].message.content


def _generate_anthropic(prompt: str) -> str:
    import anthropic
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    resp = client.messages.create(
        model=settings.anthropic_model,
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    return resp.content[0].text


def _generate_ollama(prompt: str) -> str:
    import httpx
    headers = {}
    if settings.ollama_api_key:
        # Used for Ollama's hosted/cloud API (ollama.com) or any Ollama-compatible
        # endpoint that sits behind auth. A purely local `ollama serve` install
        # needs no key at all - leave OLLAMA_API_KEY blank in that case.
        headers["Authorization"] = f"Bearer {settings.ollama_api_key}"

    resp = httpx.post(
        f"{settings.ollama_base_url}/api/generate",
        json={
            "model": settings.ollama_model,
            "prompt": f"{SYSTEM_PROMPT}\n\n{prompt}",
            "stream": False,
        },
        headers=headers,
        timeout=120,
    )
    resp.raise_for_status()
    return resp.json()["response"]


def _generate_gemini(question: str, context_chunks: list[dict]) -> str:
    from openai import OpenAI

    client = OpenAI(
        api_key=settings.gemini_api_key,
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
    )
    resp = client.chat.completions.create(
        model=settings.gemini_model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": _build_prompt(question, context_chunks)},
        ],
        temperature=0.2,
    )
    return resp.choices[0].message.content


def generate_stream(question: str, context_chunks: list[dict]) -> Iterator[str]:
    """Bonus: streaming responses. Currently implemented for OpenAI; other
    providers fall back to yielding the full answer in one chunk."""
    prompt = _build_prompt(question, context_chunks)

    if settings.llm_provider == "openai":
        if not settings.openai_api_key:
            yield _fallback_answer(context_chunks, "OPENAI_API_KEY is not set")
            return
        from openai import OpenAI
        try:
            client = OpenAI(api_key=settings.openai_api_key)
            stream = client.chat.completions.create(
                model=settings.llm_model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.2,
                stream=True,
            )
            for chunk in stream:
                delta = chunk.choices[0].delta.content
                if delta:
                    yield delta
            return
        except Exception as e:
            logger.warning(f"OpenAI streaming failed, falling back to excerpts: {e}")
    if settings.llm_provider == "gemini":
        if not settings.gemini_api_key:
            yield _fallback_answer(context_chunks, "GEMINI_API_KEY is not set")
            return
        from openai import OpenAI
        try:
            client = OpenAI(
                api_key=settings.gemini_api_key,
                base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
            )
            stream = client.chat.completions.create(
                model=settings.gemini_model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.2,
                stream=True,
            )
            for chunk in stream:
                delta = chunk.choices[0].delta.content
                if delta:
                    yield delta
            return
        except Exception as e:
            logger.warning(f"Gemini streaming failed, falling back to excerpts: {e}")

    yield generate(question, context_chunks)
