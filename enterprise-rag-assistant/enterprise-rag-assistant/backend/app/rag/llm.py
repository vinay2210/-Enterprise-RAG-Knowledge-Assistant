"""
LLM provider abstraction for answer generation.
Supports OpenAI, Anthropic, and Ollama (fully local/free) behind one
generate(prompt) -> str interface, and a streaming variant for the bonus
"streaming responses" feature.
"""
from typing import Iterator

from app.config import get_settings
from app.utils.logger import logger

settings = get_settings()

SYSTEM_PROMPT = """You are an enterprise knowledge assistant. Answer the user's question
using ONLY the information in the provided context chunks. Each chunk is labeled with
its source document and page number.

Rules:
- If the answer is not contained in the context, say you don't have enough information -
  do not make anything up.
- Cite sources inline like this: (DocumentName, p.PageNumber) right after each claim.
- Be concise and directly answer the question first, then add supporting detail.
"""


def _build_prompt(question: str, context_chunks: list[dict]) -> str:
    context_block = "\n\n".join(
        f"[Source: {c['file_name']}, Page {c['page_number']}]\n{c['text']}"
        for c in context_chunks
    )
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
