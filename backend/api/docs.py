"""
backend/api/docs.py — document intelligence HTTP API (Phase 8), mounted at /docs.
  POST   /docs/upload            multipart file → parse, embed, store (dedup by SHA-256)
  POST   /docs/query             {query, top_k} → semantic search + grounded answer
  GET    /docs/list              all documents
  DELETE /docs/{doc_id}          remove a document + its chunks
  POST   /docs/{doc_id}/extract  structured field extraction over a stored document

Read-only over trading data by construction: this only touches JARVIS's own document
store. If the document store is disabled (no JARVIS_DATABASE_URL), endpoints return 503.
"""
from __future__ import annotations

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field

from ..docs.parser import ParseError, doc_type_for, parse_bytes, sha256_bytes
from ..logging_setup import get_logger

router = APIRouter(prefix="/docs", tags=["docs"])
log = get_logger("jarvis.api.docs")

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
ALLOWED_EXT = {"pdf", "docx", "xlsx", "csv", "txt", "md"}


class QueryIn(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000)
    top_k: int = Field(5, ge=1, le=20)


def _store(request: Request):
    store = getattr(request.app.state, "docs", None)
    if store is None:
        raise HTTPException(status_code=503,
                            detail="document store disabled (set JARVIS_DATABASE_URL and run Postgres)")
    return store


@router.post("/upload")
async def upload(request: Request, file: UploadFile = File(...)):
    store = _store(request)
    filename = file.filename or "upload"
    dtype = doc_type_for(filename)
    if dtype is None or dtype not in ALLOWED_EXT:
        raise HTTPException(status_code=400,
                            detail=f"unsupported type; allowed: {sorted(ALLOWED_EXT)}")

    data = await file.read()
    if len(data) == 0:
        raise HTTPException(status_code=400, detail="empty file")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail=f"file exceeds {MAX_UPLOAD_BYTES // (1024*1024)}MB limit")

    try:
        chunks = parse_bytes(data, filename)
    except ParseError as e:
        raise HTTPException(status_code=422, detail=f"could not parse document: {e}")
    if not chunks:
        raise HTTPException(status_code=422, detail="no extractable text in document")

    res = await store.add_document(filename, chunks, file_hash=sha256_bytes(data), doc_type=dtype)
    return {"ok": True, "doc_id": str(res["doc_id"]), "filename": filename,
            "chunk_count": res["chunk_count"], "embedded": res.get("embedded"),
            "deduplicated": res.get("skipped", False)}


@router.post("/query")
async def query(body: QueryIn, request: Request):
    store = _store(request)
    qa = request.app.state.docqa
    hits = await store.search(body.query, top_k=body.top_k)
    result = await qa.answer(body.query, hits)
    return {"query": body.query, "answer": result["answer"], "sources": result["sources"],
            "matches": len(hits)}


@router.get("/list")
async def list_docs(request: Request):
    return {"documents": _store(request).list_documents()}


@router.delete("/{doc_id}")
async def delete_doc(doc_id: str, request: Request):
    n = _store(request).delete_document(doc_id)
    if n == 0:
        raise HTTPException(status_code=404, detail="document not found")
    return {"ok": True, "deleted": doc_id}


@router.post("/{doc_id}/extract")
async def extract(doc_id: str, request: Request):
    store = _store(request)
    text = store.get_document_text(doc_id)
    if text is None:
        raise HTTPException(status_code=404, detail="document not found")
    fields = await request.app.state.docqa.extract_fields(text)
    return {"doc_id": doc_id, "fields": fields}
