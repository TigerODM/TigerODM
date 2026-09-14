import numpy as np
from copy import deepcopy


def cosine_similarity(a, b):
    """
    Compute cosine similarity between two vectors.
    """

    a = np.array(a)
    b = np.array(b)

    return np.dot(a, b) / (
        np.linalg.norm(a) * np.linalg.norm(b)
    )


def retrieve_chunks_cosine(question_embedding, chunks, top_k=5, restrict_to_path=False, path=None):
    """
    Retrieve top-k chunks by cosine similarity.

    Args:
        question_embedding: list[float]
        chunks: list of dicts:
            {
                "id": "...",
                "text": "...",
                "embeddings": [...],
                "path": "..."
            }
        top_k: Number of chunks to retrieve.
        restrict_to_path: If True, only search chunks whose path
            matches `path`.
        path: Path to restrict the search to.

    Returns:
        Ranked list of chunks with scores.
    """

    results = []

    for chunk in chunks:
        # Restrict search to the requested document
        if restrict_to_path and chunk["path"] != path:
            continue

        score = cosine_similarity(
            question_embedding,
            chunk["embeddings"]
        )

        results.append(
            {
                "id": chunk["id"],
                "score": float(score),
                "text": chunk["text"],
                "path": chunk["path"],
                "index": chunk["index"]
            }
        )

    results.sort(
        key=lambda x: x["score"],
        reverse=True
    )

    return results[:top_k]


def rerank_chunks(question, chunks, reranker):
    """
    Rerank chunks with a CrossEncoder.

    Args:
        question: str
        chunks: list of dicts:
            {
                "chunk_id": "...",
                "text": "...",
                "embedding": [...]
            }
        reranker: sentence_transformers.CrossEncoder

    Returns:
        Same list of dicts, sorted by CrossEncoder score.
    """

    if len(chunks) == 0:
        return chunks

    pairs = [
        (question, chunk["text"])
        for chunk in chunks
    ]

    scores = reranker.predict(
        pairs,
        show_progress_bar=False,
    )

    reranked = deepcopy(chunks)

    for result, score in zip(reranked, scores):
        result["embedding_score"] = result["score"]
        result["reranker_score"] = float(score)
        result["score"] = float(score)

    reranked.sort(
        key=lambda x: x["score"],
        reverse=True,
    )

    return reranked


def chunk_table_to_dict(chunk_table):
    """
    Convert a table containing the following columns to a dict.
    "path"
    "Row number"
    "Chunks"
    "embedding_0", "embedding_1", ... "embedding_n"
    """
    chunks_as_dict = []

    for row in chunk_table:
        path = row["path"].value
        ID = row["Unique ID"].value
        text = row["Chunks"].value
        index = row["Chunks index"].value
        embeddings = [row[var].value for var in chunk_table.domain if "embedding_" in var.name]

        data = {
            "id": ID,
            "path": path,
            "text": text,
            "index": index,
            "embeddings": embeddings
        }
        chunks_as_dict.append(data)

    return chunks_as_dict