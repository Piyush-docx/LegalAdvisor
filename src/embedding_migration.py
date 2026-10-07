"""Re-embed stored vectors after the embedding model (or its vector size) changes.

Every stored vector records the model that made it (`embedding_model`, see embeddings.embedding_id()).
Searches only compare vectors with the current id, so after a switch old rows are simply invisible
until they are re-embedded here. Chunks are re-embedded from their stored text and cached questions
from their stored question text, so nothing is re-fetched from IKanoon and answers stay valid.

Resumable: a run that stops (quota, crash) leaves a mix of old and new rows; run it again to continue.
"""

from dataclasses import dataclass, field
import logging

from pgvector import Vector

from src import embeddings
from src.db import VECTOR_INDEXES, transaction, using_postgres

logger = logging.getLogger(__name__)

# table -> (vector column, text column, embedding kind, index name)
TABLES = {
    "chunks": ("embedding", "text", "document", "idx_chunks_embedding"),
    "answer_cache": ("question_embedding", "question", "query", "idx_answer_cache_embedding"),
}


@dataclass
class MigrationPlan:
    current_id: str
    target_dim: int
    stale_rows: dict[str, int] = field(default_factory=dict)
    column_dims: dict[str, int | None] = field(default_factory=dict)
    estimated_tokens: int = 0

    @property
    def needs_dimension_change(self) -> bool:
        return any(d is not None and d != self.target_dim for d in self.column_dims.values())

    @property
    def nothing_to_do(self) -> bool:
        return not any(self.stale_rows.values()) and not self.needs_dimension_change


def _require_postgres() -> None:
    if not using_postgres():
        raise NotImplementedError("re-embedding applies to the PostgreSQL vector tables (DATABASE_URL)")


def _column_dim(conn, table: str, column: str) -> int | None:
    row = conn.execute(
        "SELECT atttypmod AS dim FROM pg_attribute WHERE attrelid = ?::regclass AND attname = ?",
        (table, column),
    ).fetchone()
    return int(row["dim"]) if row and row["dim"] and row["dim"] > 0 else None


def make_plan() -> MigrationPlan:
    _require_postgres()
    plan = MigrationPlan(current_id=embeddings.embedding_id(), target_dim=embeddings.EMBEDDING_DIM)
    with transaction() as conn:
        for table, (vec_col, text_col, _kind, _idx) in TABLES.items():
            plan.column_dims[table] = _column_dim(conn, table, vec_col)
            row = conn.execute(
                f"SELECT COUNT(*) AS n, COALESCE(SUM(LENGTH({text_col})), 0) AS chars "
                f"FROM {table} WHERE embedding_model != ?",
                (plan.current_id,),
            ).fetchone()
            plan.stale_rows[table] = int(row["n"])
            plan.estimated_tokens += int(row["chars"]) // 3
    return plan


def _alter_dimension(target_dim: int) -> None:
    """Change the vector column size. Old vectors cannot be converted, so they are cleared and
    their rows marked stale (embedding_model = ''); the re-embed loop then refills them."""
    with transaction() as conn:
        for index_name in VECTOR_INDEXES:
            conn.execute(f"DROP INDEX IF EXISTS {index_name}")
        for table, (vec_col, *_rest) in TABLES.items():
            conn.execute(f"ALTER TABLE {table} ALTER COLUMN {vec_col} DROP NOT NULL")
            conn.execute(f"ALTER TABLE {table} ALTER COLUMN {vec_col} TYPE vector({target_dim}) USING NULL")
            conn.execute(f"UPDATE {table} SET embedding_model = ''")


def _finalise(table: str) -> None:
    vec_col, _text, _kind, index_name = TABLES[table]
    with transaction() as conn:
        conn.execute(f"ALTER TABLE {table} ALTER COLUMN {vec_col} SET NOT NULL")
        conn.execute(VECTOR_INDEXES[index_name])


def migrate(batch_size: int = 50, embed_texts=None) -> dict:
    """Re-embed every stale row. `embed_texts(texts, kind) -> vectors` is injectable for tests.

    Returns {"chunks": n, "answer_cache": n, "completed": bool}. Stops cleanly (completed=False)
    if the embedding service becomes unavailable; run again to resume."""
    _require_postgres()
    embed = embed_texts or (lambda texts, kind: embeddings.embed_texts(texts, kind, max_wait_seconds=600))
    plan = make_plan()
    if plan.needs_dimension_change:
        logger.warning("changing vector columns to %d dimensions; existing vectors will be rebuilt", plan.target_dim)
        _alter_dimension(plan.target_dim)

    done = {"chunks": 0, "answer_cache": 0, "completed": True}
    current_id = embeddings.embedding_id()
    for table, (vec_col, text_col, kind, _idx) in TABLES.items():
        while True:
            with transaction() as conn:
                rows = conn.execute(
                    f"SELECT id, {text_col} AS body FROM {table} WHERE embedding_model != ? ORDER BY id LIMIT ?",
                    (current_id, batch_size),
                ).fetchall()
            if not rows:
                _finalise(table)
                break
            try:
                vectors = embed([r["body"] for r in rows], kind)
            except embeddings.EmbeddingUnavailable as exc:
                logger.error("stopping: embeddings unavailable (%s); rerun to resume", exc)
                done["completed"] = False
                return done
            with transaction() as conn:
                for row, vector in zip(rows, vectors):
                    conn.execute(
                        f"UPDATE {table} SET {vec_col} = ?, embedding_model = ? WHERE id = ?",
                        (Vector(vector), current_id, row["id"]),
                    )
            done[table] += len(rows)
    return done
