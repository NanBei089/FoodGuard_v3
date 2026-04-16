from __future__ import annotations

import re
import threading
from typing import Any

import chromadb
from chromadb.errors import ChromaError
import httpx
import structlog

from app.core.config import get_settings
from app.core.errors import EmbeddingServiceError

logger = structlog.get_logger(__name__)
_HTTP_CLIENT: httpx.Client | None = None
_http_client_lock = None
_CHROMA_CLIENT: chromadb.Client | None = None
_CHROMA_CLIENT_PATH: str | None = None
_CHROMA_COLLECTIONS: dict[tuple[str, str], chromadb.Collection] = {}
_chroma_client_lock = threading.Lock()
_chroma_collection_lock = threading.Lock()
MAX_RAG_TERMS = 30


def _get_http_client() -> httpx.Client:
    global _HTTP_CLIENT, _http_client_lock
    if _http_client_lock is None:
        import threading

        _http_client_lock = threading.Lock()

    if _HTTP_CLIENT is None:
        with _http_client_lock:
            if _HTTP_CLIENT is None:
                settings = get_settings()
                _HTTP_CLIENT = httpx.Client(
                    timeout=float(settings.OLLAMA_EMBEDDING_TIMEOUT_S)
                )
    return _HTTP_CLIENT


def _normalize_text(value: Any) -> str:
    import unicodedata

    text = "" if value is None else str(value)
    text = unicodedata.normalize("NFKC", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _coerce_embedding_vector(vector: Any) -> list[float]:
    if not isinstance(vector, list) or not vector:
        raise EmbeddingServiceError(
            "Ollama embedding response contains an invalid vector"
        )

    try:
        return [float(item) for item in vector]
    except (TypeError, ValueError) as exc:
        raise EmbeddingServiceError(
            "Ollama embedding vector contains non-numeric values"
        ) from exc


def _embed_batch(texts: list[str]) -> list[list[float]]:
    clean_texts = [_normalize_text(text) for text in texts]
    if not clean_texts or any(not text for text in clean_texts):
        raise EmbeddingServiceError("Embedding input is empty")

    settings = get_settings()
    endpoint = f"{settings.OLLAMA_BASE_URL.rstrip('/')}/api/embed"
    payload = {
        "model": settings.OLLAMA_EMBEDDING_MODEL,
        "input": clean_texts,
        "truncate": True,
    }

    try:
        client = _get_http_client()
        response = client.post(
            endpoint,
            json=payload,
            timeout=float(settings.OLLAMA_EMBEDDING_TIMEOUT_S),
        )
        response.raise_for_status()
        data = response.json()
    except httpx.HTTPError as exc:
        raise EmbeddingServiceError("Ollama embedding request failed") from exc
    except ValueError as exc:
        raise EmbeddingServiceError(
            "Ollama embedding response is not valid JSON"
        ) from exc

    embeddings = data.get("embeddings")
    if not isinstance(embeddings, list) or len(embeddings) != len(clean_texts):
        raise EmbeddingServiceError("Ollama embedding response is missing embeddings")

    return [_coerce_embedding_vector(vector) for vector in embeddings]


def _embed(text: str) -> list[float]:
    return _embed_batch([text])[0]


def _embed_text(text: str) -> list[float]:
    return _embed(text)


def _normalize_term(term: str) -> str:
    return _normalize_text(term)


def _similarity_from_distance(distance: Any) -> float:
    try:
        score = 1.0 - float(distance)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, round(score, 4)))


def _coerce_aliases(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [item.strip() for item in value.split(",") if item.strip()]
    return []


def _extract_match_term(meta: dict[str, Any], fallback: str) -> str:
    for key in ("term", "name", "ingredient", "raw_term"):
        value = meta.get(key)
        if isinstance(value, str) and value.strip():
            return _normalize_text(value)
    return fallback


def _extract_function_category(meta: dict[str, Any]) -> str:
    for key in ("function_category", "category", "function", "type"):
        value = meta.get(key)
        if isinstance(value, str) and value.strip():
            return _normalize_text(value)
    return "unknown"


def _build_rag_match(item: dict[str, Any], term: str, index: int) -> dict[str, Any]:
    meta = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    normalized_term = _normalize_term(term)
    return {
        "id": str(item.get("id", "")),
        "term": _extract_match_term(meta, normalized_term),
        "normalized_term": _normalize_text(
            meta.get("normalized_term", normalized_term)
        ),
        "aliases": _coerce_aliases(meta.get("aliases")),
        "function_category": _extract_function_category(meta),
        "is_primary": (
            bool(meta.get("is_primary")) if "is_primary" in meta else index == 0
        ),
        "similarity_score": _similarity_from_distance(item.get("distance")),
    }


def _match_quality(matches: list[dict[str, Any]]) -> str:
    if not matches:
        return "empty"
    best_score = matches[0]["similarity_score"]
    if best_score >= 0.8:
        return "high"
    return "weak"


def _rank_and_dedupe_matches(
    items: list[dict[str, Any]], term: str
) -> list[dict[str, Any]]:
    best_by_id: dict[str, dict[str, Any]] = {}
    unkeyed: list[dict[str, Any]] = []
    for index, item in enumerate(items):
        match = _build_rag_match(item, term, index)
        match_id = match["id"].strip()
        if not match_id:
            unkeyed.append(match)
            continue
        current = best_by_id.get(match_id)
        if current is None or match["similarity_score"] > current["similarity_score"]:
            best_by_id[match_id] = match

    ranked = list(best_by_id.values()) + unkeyed
    ranked.sort(key=lambda item: item["similarity_score"], reverse=True)
    return ranked


def _get_result_value(
    results: dict[str, Any],
    key: str,
    query_index: int,
    item_index: int,
    default: Any,
) -> Any:
    rows = results.get(key)
    if not isinstance(rows, list) or query_index >= len(rows):
        return default
    row = rows[query_index]
    if not isinstance(row, list) or item_index >= len(row):
        return default
    return row[item_index]


def _extract_query_results(
    results: dict[str, Any] | None,
    query_index: int,
) -> list[dict[str, Any]]:
    if not results:
        return []

    ids_by_query = results.get("ids")
    if not isinstance(ids_by_query, list) or query_index >= len(ids_by_query):
        return []

    ids = ids_by_query[query_index]
    if not isinstance(ids, list) or not ids:
        return []

    retrieved: list[dict[str, Any]] = []
    for item_index, item_id in enumerate(ids):
        retrieved.append(
            {
                "id": item_id,
                "document": _get_result_value(
                    results, "documents", query_index, item_index, ""
                ),
                "metadata": _get_result_value(
                    results, "metadatas", query_index, item_index, {}
                ),
                "distance": _get_result_value(
                    results, "distances", query_index, item_index, 1.0
                ),
            }
        )
    return retrieved


def _empty_query_batch(size: int) -> list[list[dict[str, Any]]]:
    return [[] for _ in range(size)]


def _query_collection_by_embeddings(
    collection_getter: Any,
    embeddings: list[list[float]],
    top_k: int,
) -> list[list[dict[str, Any]]]:
    if not embeddings:
        return []

    try:
        collection = collection_getter()
    except ChromaError as exc:
        logger.warning("chroma_collection_not_found", error=str(exc))
        return _empty_query_batch(len(embeddings))

    try:
        results = collection.query(
            query_embeddings=embeddings,
            n_results=top_k,
            include=["documents", "metadatas", "distances"],
        )
    except ChromaError as exc:
        logger.warning("chroma_query_failed", error=str(exc))
        return _empty_query_batch(len(embeddings))

    return [
        _extract_query_results(results, query_index)
        for query_index in range(len(embeddings))
    ]


def _build_retrieval_item(
    term: str,
    ingredient_matches: list[dict[str, Any]],
    standard_matches: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    combined = ingredient_matches + (standard_matches or [])
    matches = _rank_and_dedupe_matches(combined, term)
    return {
        "raw_term": term,
        "normalized_term": term,
        "retrieved": bool(matches),
        "match_quality": _match_quality(matches),
        "matches": matches,
    }


def _get_chroma_client() -> chromadb.Client:
    global _CHROMA_CLIENT, _CHROMA_CLIENT_PATH
    settings = get_settings()
    chroma_data_path = str(settings.CHROMADB_PATH)
    if _CHROMA_CLIENT is None or _CHROMA_CLIENT_PATH != chroma_data_path:
        with _chroma_client_lock:
            if _CHROMA_CLIENT is None or _CHROMA_CLIENT_PATH != chroma_data_path:
                _CHROMA_CLIENT = chromadb.PersistentClient(path=chroma_data_path)
                _CHROMA_CLIENT_PATH = chroma_data_path
                _CHROMA_COLLECTIONS.clear()
    return _CHROMA_CLIENT


def _get_cached_collection(name: str) -> chromadb.Collection:
    client = _get_chroma_client()
    cache_key = (_CHROMA_CLIENT_PATH or "", name)
    cached = _CHROMA_COLLECTIONS.get(cache_key)
    if cached is not None:
        return cached
    with _chroma_collection_lock:
        cached = _CHROMA_COLLECTIONS.get(cache_key)
        if cached is not None:
            return cached
        collection = client.get_collection(name=name)
        _CHROMA_COLLECTIONS[cache_key] = collection
        return collection


def _get_ingredients_collection() -> chromadb.Collection:
    settings = get_settings()
    return _get_cached_collection(settings.CHROMADB_COLLECTION_INGREDIENTS)


def _get_standards_collection() -> chromadb.Collection:
    settings = get_settings()
    return _get_cached_collection(settings.CHROMADB_COLLECTION_STANDARDS)


def warmup() -> None:
    _get_ingredients_collection()
    _get_standards_collection()
    current_settings = get_settings()
    if not current_settings.HEALTH_CHECK_EXTERNAL:
        return
    try:
        _embed("食品配料")
    except EmbeddingServiceError as exc:
        logger.warning("rag_embedding_warmup_failed", error=str(exc))


def retrieve_all_ingredients(query_text: str, top_k: int = 5) -> list[dict[str, Any]]:
    if not query_text or not query_text.strip():
        return []

    try:
        query_embeddings = _embed_batch([query_text])
    except EmbeddingServiceError as exc:
        logger.warning("chroma_query_failed", error=str(exc))
        return []

    results = _query_collection_by_embeddings(
        _get_ingredients_collection,
        query_embeddings,
        top_k,
    )
    return results[0] if results else []


def query_gb2760_by_keyword(keyword: str, top_k: int = 3) -> list[dict[str, Any]]:
    if not keyword or not keyword.strip():
        return []

    try:
        query_embeddings = _embed_batch([keyword])
    except EmbeddingServiceError as exc:
        logger.warning("chroma_query_failed", error=str(exc))
        return []

    results = _query_collection_by_embeddings(
        _get_standards_collection,
        query_embeddings,
        top_k,
    )
    return results[0] if results else []


def retrieve_all(
    ingredient_terms: list[str],
    ingredients_text: str,
    top_k_ingredients: int = 5,
    top_k_per_term: int = 2,
) -> dict[str, Any]:
    if not ingredient_terms and not ingredients_text:
        return {
            "source_file": "chromadb",
            "ingredients_text": "",
            "items_total": 0,
            "retrieval_results": [],
        }

    normalized_terms: list[str] = []
    for term in ingredient_terms:
        normalized = _normalize_term(term)
        if normalized and normalized not in normalized_terms:
            normalized_terms.append(normalized)

    normalized_terms = normalized_terms[:MAX_RAG_TERMS]
    retrieval_items: list[dict[str, Any]] = []
    if normalized_terms:
        try:
            query_embeddings = _embed_batch(normalized_terms)
        except EmbeddingServiceError as exc:
            logger.warning("rag_embedding_batch_failed", error=str(exc))
            retrieval_items = [
                _build_retrieval_item(term, []) for term in normalized_terms
            ]
        else:
            ingredient_results = _query_collection_by_embeddings(
                _get_ingredients_collection,
                query_embeddings,
                top_k_ingredients,
            )
            standard_results = _query_collection_by_embeddings(
                _get_standards_collection,
                query_embeddings,
                top_k_per_term,
            )
            for index, term in enumerate(normalized_terms):
                retrieval_items.append(
                    _build_retrieval_item(
                        term,
                        (
                            ingredient_results[index]
                            if index < len(ingredient_results)
                            else []
                        ),
                        (
                            standard_results[index]
                            if index < len(standard_results)
                            else []
                        ),
                    )
                )

    if not retrieval_items and ingredients_text.strip():
        fallback_term = _normalize_term(ingredients_text)
        fallback_matches = retrieve_all_ingredients(
            fallback_term, top_k=top_k_ingredients
        )
        matches = [
            _build_rag_match(item, fallback_term, index)
            for index, item in enumerate(fallback_matches)
        ]
        retrieval_items.append(
            {
                "raw_term": fallback_term,
                "normalized_term": fallback_term,
                "retrieved": bool(matches),
                "match_quality": _match_quality(matches),
                "matches": matches,
            }
        )

    return {
        "source_file": "chromadb",
        "ingredients_text": ingredients_text,
        "items_total": len(retrieval_items),
        "retrieval_results": retrieval_items,
    }


def check_additive_safety(
    additive_name: str,
    food_category: str | None = None,
) -> dict[str, Any]:
    retrieved = retrieve_all_ingredients(query_text=additive_name, top_k=3)

    if not retrieved:
        return {
            "additive": additive_name,
            "found": False,
            "safety_status": "unknown",
            "details": [],
        }

    details: list[dict[str, Any]] = []
    for item in retrieved:
        doc = item.get("document", "")
        meta = item.get("metadata", {})
        distance = item.get("distance", 1.0)

        details.append(
            {
                "id": item.get("id"),
                "description": doc[:500] if doc else "",
                "category": meta.get("category", ""),
                "usage_limit": meta.get("usage_limit", ""),
                "similarity_score": round(1.0 - distance, 4) if distance else 0.0,
            }
        )

    best_match = details[0] if details else {}
    safety_status = (
        "permitted"
        if (best_match.get("similarity_score", 0) > 0.8)
        else "review_required"
    )

    return {
        "additive": additive_name,
        "found": bool(retrieved),
        "safety_status": safety_status,
        "details": details,
    }


__all__ = [
    "retrieve_all",
    "retrieve_all_ingredients",
    "query_gb2760_by_keyword",
    "check_additive_safety",
    "warmup",
    "_get_ingredients_collection",
    "_get_standards_collection",
    "_embed",
    "_embed_batch",
]
