import uuid
import time
import logging
from datetime import datetime, timezone
from typing import Optional

from qdrant_client import QdrantClient
from qdrant_client.http import models
from qdrant_client.http.exceptions import UnexpectedResponse, ResponseHandlingException
from langchain_openai import OpenAIEmbeddings

from config import settings
from schemas import SnapshotPayload

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# EMBEDDINGS
# ─────────────────────────────────────────────────────────────────────────────
embedder = OpenAIEmbeddings(
    model="text-embedding-3-small",
    openai_api_key=settings.OPENAI_API_KEY,
)


# ─────────────────────────────────────────────────────────────────────────────
# CONNECTION
# ─────────────────────────────────────────────────────────────────────────────
def get_qdrant_client() -> QdrantClient:
    return QdrantClient(
        url=settings.QDRANT_URL,
        api_key=settings.QDRANT_API_KEY,
    )


# ─────────────────────────────────────────────────────────────────────────────
# COLLECTION SETUP
# ─────────────────────────────────────────────────────────────────────────────
def ensure_collection(client: QdrantClient, max_retries: int = 5) -> None:
    for attempt in range(1, max_retries + 1):
        try:
            client.get_collection(settings.COLLECTION_NAME)
            print(f"  [db] Collection '{settings.COLLECTION_NAME}' already exists.")
            return
        except UnexpectedResponse:
            print(f"  [db] Creating collection '{settings.COLLECTION_NAME}'...")
            client.create_collection(
                collection_name=settings.COLLECTION_NAME,
                vectors_config=models.VectorParams(
                    size=settings.VECTOR_SIZE,
                    distance=models.Distance.COSINE,
                ),
            )
            client.create_payload_index(
                collection_name=settings.COLLECTION_NAME,
                field_name="url",
                field_schema=models.PayloadSchemaType.KEYWORD,
            )
            print(f"  [db] Collection created with URL index.")
            return
        except (ResponseHandlingException, Exception) as e:
            if attempt < max_retries:
                wait = 2 ** attempt  # 2, 4, 8, 16, 32 seconds
                logger.warning(f"  [db] Connection attempt {attempt}/{max_retries} failed: {e}. Retrying in {wait}s...")
                time.sleep(wait)
            else:
                logger.error(f"  [db] All {max_retries} connection attempts failed. Last error: {e}")
                raise


def ensure_app_config_collection(client: QdrantClient, max_retries: int = 5) -> None:
    for attempt in range(1, max_retries + 1):
        try:
            client.get_collection("app_config")
            print("  [db] app_config collection already exists.")
            return
        except UnexpectedResponse:
            client.create_collection(
                collection_name="app_config",
                vectors_config=models.VectorParams(
                    size=settings.VECTOR_SIZE,
                    distance=models.Distance.COSINE,
                ),
            )
            # Add payload indexes
            client.create_payload_index(
                collection_name="app_config",
                field_name="type",
                field_schema=models.PayloadSchemaType.KEYWORD,
            )
            client.create_payload_index(
                collection_name="app_config",
                field_name="status",
                field_schema=models.PayloadSchemaType.KEYWORD,
            )
            client.create_payload_index(
                collection_name="app_config",
                field_name="thread_id",
                field_schema=models.PayloadSchemaType.KEYWORD,
            )
            print("  [db] app_config collection created with indexes.")
            return
        except (ResponseHandlingException, Exception) as e:
            if attempt < max_retries:
                wait = 2 ** attempt
                logger.warning(f"  [db] app_config connection attempt {attempt}/{max_retries} failed: {e}. Retrying in {wait}s...")
                time.sleep(wait)
            else:
                logger.error(f"  [db] All {max_retries} app_config connection attempts failed. Last error: {e}")
                raise


# ─────────────────────────────────────────────────────────────────────────────
# SAVE SNAPSHOT
# ─────────────────────────────────────────────────────────────────────────────
def save_snapshot(client: QdrantClient, url: str, content: str) -> None:
    _delete_existing_snapshot(client, url)
    vector = embedder.embed_query(content[:8000])
    payload: SnapshotPayload = {
        "url":      url,
        "content":  content,
        "saved_at": datetime.now(timezone.utc).isoformat(),
    }
    client.upsert(
        collection_name=settings.COLLECTION_NAME,
        points=[
            models.PointStruct(
                id=str(uuid.uuid4()),
                vector=vector,
                payload=payload,
            )
        ],
    )
    print(f"  [db] Snapshot saved for: {url}")


# ─────────────────────────────────────────────────────────────────────────────
# GET SNAPSHOT
# ─────────────────────────────────────────────────────────────────────────────
def get_snapshot(client: QdrantClient, url: str) -> Optional[str]:
    results, _ = client.scroll(
        collection_name=settings.COLLECTION_NAME,
        scroll_filter=models.Filter(
            must=[
                models.FieldCondition(
                    key="url",
                    match=models.MatchValue(value=url),
                )
            ]
        ),
        limit=1,
        with_payload=True,
        with_vectors=False,
    )
    if results:
        return results[0].payload.get("content")
    return None


# ─────────────────────────────────────────────────────────────────────────────
# INTERNAL HELPERS
# ─────────────────────────────────────────────────────────────────────────────
def _delete_existing_snapshot(client: QdrantClient, url: str) -> None:
    client.delete(
        collection_name=settings.COLLECTION_NAME,
        points_selector=models.FilterSelector(
            filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="url",
                        match=models.MatchValue(value=url),
                    )
                ]
            )
        ),
    )


# ─────────────────────────────────────────────────────────────────────────────
# URL STORAGE — persistent in Qdrant
# ─────────────────────────────────────────────────────────────────────────────
def save_monitored_urls(client: QdrantClient, urls: list[str]) -> None:
    """Save monitored URLs persistently in Qdrant."""
    try:
        client.upsert(
            collection_name="app_config",
            points=[
                models.PointStruct(
                    id="00000000-0000-0000-0000-000000000001",
                    vector=[0.0] * settings.VECTOR_SIZE,
                    payload={"type": "monitored_urls", "urls": urls}
                )
            ]
        )
        logger.info(f"  [db] Monitored URLs saved: {urls}")
    except Exception as e:
        logger.error(f"  [db] Failed to save monitored URLs: {e}")
        # Re-ensure the collection exists (may have been deleted)
        ensure_app_config_collection(client)
        # Retry once
        client.upsert(
            collection_name="app_config",
            points=[
                models.PointStruct(
                    id="00000000-0000-0000-0000-000000000001",
                    vector=[0.0] * settings.VECTOR_SIZE,
                    payload={"type": "monitored_urls", "urls": urls}
                )
            ]
        )
        logger.info(f"  [db] Monitored URLs saved on retry: {urls}")


def get_monitored_urls(client: QdrantClient) -> list[str]:
    """Get monitored URLs from Qdrant."""
    try:
        results, _ = client.scroll(
            collection_name="app_config",
            scroll_filter=models.Filter(
                must=[models.FieldCondition(
                    key="type",
                    match=models.MatchValue(value="monitored_urls")
                )]
            ),
            limit=1,
            with_payload=True,
            with_vectors=False,
        )
        if results:
            return results[0].payload.get("urls", [])
        return []
    except Exception as e:
        print(f"  [db] Failed to get URLs: {e}")
        return []


# ─────────────────────────────────────────────────────────────────────────────
# PENDING REVIEWS STORAGE — persistent in Qdrant
# ─────────────────────────────────────────────────────────────────────────────
def save_pending_review(client: QdrantClient, review: dict) -> None:
    """Save a pending review to Qdrant."""
    client.upsert(
        collection_name="app_config",
        points=[
            models.PointStruct(
                id=str(uuid.uuid4()),
                vector=[0.0] * settings.VECTOR_SIZE,
                payload={"type": "pending_review", **review}
            )
        ]
    )
    print(f"  [db] Pending review saved: {review.get('thread_id')}")


def get_pending_reviews(client: QdrantClient) -> list[dict]:
    """Get all pending reviews from Qdrant."""
    try:
        results, _ = client.scroll(
            collection_name="app_config",
            scroll_filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="type",
                        match=models.MatchValue(value="pending_review")
                    ),
                    models.FieldCondition(
                        key="status",
                        match=models.MatchValue(value="pending")
                    )
                ]
            ),
            limit=100,
            with_payload=True,
            with_vectors=False,
        )
        return [r.payload for r in results]
    except Exception as e:
        print(f"  [db] Failed to get pending reviews: {e}")
        return []


def update_pending_review(client: QdrantClient, thread_id: str, status: str, approved: bool = False) -> None:
    """Update review status in Qdrant."""
    try:
        results, _ = client.scroll(
            collection_name="app_config",
            scroll_filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="type",
                        match=models.MatchValue(value="pending_review")
                    ),
                    models.FieldCondition(
                        key="thread_id",
                        match=models.MatchValue(value=thread_id)
                    )
                ]
            ),
            limit=1,
            with_payload=False,
            with_vectors=False,
        )
        if results:
            client.set_payload(
                collection_name="app_config",
                payload={"status": status, "approved": approved},
                points=[results[0].id]
            )
            print(f"  [db] Review updated: {thread_id} → {status}")
    except Exception as e:
        print(f"  [db] Failed to update review: {e}")