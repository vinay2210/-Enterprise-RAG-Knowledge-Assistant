"""Chat endpoints: send a message, get grounded answer + citations."""
import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import ChatSession, ChatMessage, Document, DocumentStatus
from app.rag.retriever import retrieve
from app.rag import llm
from app.schemas import ChatRequest, ChatResponse, Citation
from app.utils.logger import logger

router = APIRouter(prefix="/api/chat", tags=["chat"])


def _resolve_file_filter(db: Session, file_filter: list[str] | None) -> list[str] | None:
    """Turns @mentioned names (possibly partial) into exact file_name values
    that exist in the index, so the vector store filter actually matches."""
    if not file_filter:
        return None
    all_names = [
        d.file_name
        for d in db.query(Document.file_name)
        .filter(Document.status != DocumentStatus.DELETED)
        .all()
    ]
    resolved = []
    for mention in file_filter:
        matches = [n for n in all_names if mention.lower() in n.lower()]
        resolved.extend(matches)
    return list(set(resolved)) or None


@router.post("", response_model=ChatResponse)
def chat(req: ChatRequest, db: Session = Depends(get_db)):
    session = None
    if req.session_id:
        session = db.query(ChatSession).filter(ChatSession.id == req.session_id).first()
    if session is None:
        session = ChatSession(title=req.message[:60])
        db.add(session)
        db.commit()
        db.refresh(session)

    db.add(ChatMessage(session_id=session.id, role="user", content=req.message))
    db.commit()

    file_filter = _resolve_file_filter(db, req.file_filter)
    try:
        hits = retrieve(req.message, top_k=req.top_k, file_filter=file_filter, strategy=req.strategy)
    except Exception as e:
        logger.warning(f"Retrieval failed, returning no results: {e}")
        hits = []

    if not hits:
        answer = "I couldn't find anything relevant in the indexed documents to answer that."
        citations: list[Citation] = []
    else:
        try:
            answer = llm.generate(req.message, hits)
        except Exception as e:
            logger.warning(f"LLM generation failed, falling back to excerpts: {e}")
            answer = llm._fallback_answer(hits, str(e))

        citations = [
            Citation(
                document_id=h["document_id"],
                file_name=h["file_name"],
                page_number=h["page_number"],
                chunk_index=h["chunk_index"],
                snippet=(h.get("parent_text") or h["text"])[:280],
                score=round(h.get("rrf_score") or h.get("score", 0.0), 4),
            )
            for h in hits
        ]

    db.add(ChatMessage(
        session_id=session.id,
        role="assistant",
        content=answer,
        citations_json=json.dumps([c.model_dump() for c in citations]),
    ))
    db.commit()

    return ChatResponse(session_id=session.id, answer=answer, citations=citations)


@router.post("/stream")
def chat_stream(req: ChatRequest, db: Session = Depends(get_db)):
    """Bonus: streaming responses (Server-Sent-Events-style chunked text)."""
    file_filter = _resolve_file_filter(db, req.file_filter)
    hits = retrieve(req.message, top_k=req.top_k, file_filter=file_filter, strategy=req.strategy)

    def event_generator():
        if not hits:
            yield "I couldn't find anything relevant in the indexed documents."
            return
        for token in llm.generate_stream(req.message, hits):
            yield token

    return StreamingResponse(event_generator(), media_type="text/plain")


@router.get("/sessions/{session_id}/history")
def history(session_id: str, db: Session = Depends(get_db)):
    msgs = db.query(ChatMessage).filter(ChatMessage.session_id == session_id).order_by(ChatMessage.created_at).all()
    return [
        {
            "role": m.role,
            "content": m.content,
            "citations": json.loads(m.citations_json) if m.citations_json else [],
            "created_at": m.created_at,
        }
        for m in msgs
    ]
