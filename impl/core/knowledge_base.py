"""Project knowledge base using agno memory to manage long context.
Stores field definitions, intent labels, and project docs once,
then retrieves relevant entries per query with semantic vector search."""

from __future__ import annotations

import logging
import math
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

try:
    import dashscope
except ImportError:  # pragma: no cover - optional in test env
    dashscope = None
import yaml
from impl.core.config import get_embedding_config
try:
    from agno.knowledge.document import Document
    from agno.knowledge.embedder import Embedder
    from agno.vectordb.base import VectorDb
except ImportError:  # pragma: no cover - optional in local schema/test env
    class Document:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    class Embedder:
        def __init__(self, dimensions: int = 0, **kwargs):
            self.dimensions = dimensions

    class VectorDb:
        pass

ROOT = Path(__file__).resolve().parents[2]
KNOWLEDGE_ROOT = ROOT / "impl" / ".disabled_knowledge"  # Disabled to prevent Agno auto-persistence
class BailianEmbedder(Embedder):
    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        *,
        trust_env_proxy: Optional[bool] = None,
    ):
        embedding_config = get_embedding_config()
        super().__init__(dimensions=embedding_config.dimensions)
        self.api_key = embedding_config.api_key if api_key is None else api_key
        self.id = model or embedding_config.model
        if trust_env_proxy is None:
            trust_env_proxy = embedding_config.trust_env_proxy
        # requests also inherits macOS system proxies via urllib.getproxies().
        # Embeddings use an explicit session so an unrelated desktop proxy cannot
        # silently become part of the ContextUnit evidence path. Deployments that
        # require such a proxy can opt in with BAILIAN_EMBEDDING_TRUST_ENV_PROXY=1.
        self._session = requests.Session()
        self._session.trust_env = bool(trust_env_proxy)

    def get_embedding(self, text: str) -> List[float]:
        embedding, _ = self.get_embedding_and_usage(text)
        return embedding

    def get_embedding_and_usage(self, text: str) -> tuple[List[float], Optional[Dict[str, Any]]]:
        embeddings, usage = self.get_embeddings_and_usage([text])
        return (embeddings[0] if embeddings else []), usage

    def get_embeddings_and_usage(
        self,
        texts: List[str],
    ) -> tuple[List[List[float]], Optional[Dict[str, Any]]]:
        if not self.api_key:
            return [], {"error": "missing_bailian_api_key"}
        if dashscope is None:
            return [], {"error": "missing_dashscope_dependency"}
        normalized = [str(text) for text in texts]
        if not normalized:
            return [], {"error": "empty_embedding_input"}
        response = dashscope.TextEmbedding.call(
            model=self.id,
            input=normalized,
            api_key=self.api_key,
            session=self._session,
        )
        if response.status_code != 200:
            return [], {"error": getattr(response, "code", "embedding_failed"), "message": getattr(response, "message", "")}
        embeddings = response.output.get("embeddings") or []
        if not embeddings:
            return [], {"error": "empty_embedding"}
        ordered: List[Optional[List[float]]] = [None] * len(normalized)
        for position, item in enumerate(embeddings):
            index = item.get("text_index", position)
            try:
                index = int(index)
            except (TypeError, ValueError):
                return [], {"error": "invalid_embedding_text_index"}
            if index < 0 or index >= len(ordered) or ordered[index] is not None:
                return [], {"error": "invalid_embedding_text_index"}
            ordered[index] = item.get("embedding") or []
        if any(item is None for item in ordered):
            return [], {"error": "mismatched_embedding_batch"}
        return [list(item or []) for item in ordered], getattr(response, "usage", None)


class SemanticVectorDb(VectorDb):
    def __init__(self, embedder: Optional[Embedder] = None, retrieval_top_k: Optional[int] = None):
        self.documents: List[Document] = []
        self._created = False
        self.embedder = embedder or BailianEmbedder()
        self.retrieval_top_k = retrieval_top_k or get_embedding_config().retrieval_top_k

    def create(self) -> None:
        self._created = True

    async def async_create(self) -> None:
        self.create()

    def id_exists(self, id: str) -> bool:
        return any(doc.id == id for doc in self.documents)

    async def async_id_exists(self, id: str) -> bool:
        return self.id_exists(id)

    def content_hash_exists(self, content_hash: str) -> bool:
        return any(doc.content_id == content_hash for doc in self.documents)

    def doc_exists(self, document: Document) -> bool:
        return any(doc.id == document.id for doc in self.documents)

    async def async_doc_exists(self, document: Document) -> bool:
        return self.doc_exists(document)

    def name_exists(self, name: str) -> bool:
        return any(doc.name == name for doc in self.documents)

    async def async_name_exists(self, name: str) -> bool:
        return self.name_exists(name)

    def insert(self, content_hash: str, documents: List[Document], filters: Optional[Dict[str, Any]] = None) -> None:
        for document in documents:
            if not document.embedding:
                document.embed(self.embedder)
            if not document.content_id:
                document.content_id = content_hash
            self.documents.append(document)

    async def async_insert(self, content_hash: str, documents: List[Document], filters: Optional[Dict[str, Any]] = None) -> None:
        self.insert(content_hash, documents, filters)

    def upsert_available(self) -> bool:
        return True

    def upsert(self, content_hash: str, documents: List[Document], filters: Optional[Dict[str, Any]] = None) -> None:
        for document in documents:
            self.documents = [doc for doc in self.documents if doc.id != document.id]
        self.insert(content_hash, documents, filters)

    async def async_upsert(self, content_hash: str, documents: List[Document], filters: Optional[Dict[str, Any]] = None) -> None:
        self.upsert(content_hash, documents, filters)

    def search(self, query: str, limit: Optional[int] = None, filters: Optional[Dict[str, Any]] = None) -> List[Document]:
        effective_limit = self.retrieval_top_k if limit is None else int(limit)
        query_embedding = self.embedder.get_embedding(query)
        if not query_embedding:
            return []
        scored = []
        for document in self.documents:
            if filters and any(document.meta_data.get(key) != value for key, value in filters.items()):
                continue
            if document.embedding:
                scored.append((_cosine_similarity(query_embedding, document.embedding), document))
        scored.sort(key=lambda item: -item[0])
        return [document for _, document in scored[:effective_limit]]

    async def async_search(self, query: str, limit: Optional[int] = None, filters: Optional[Dict[str, Any]] = None) -> List[Document]:
        return self.search(query, limit, filters)

    def drop(self) -> None:
        self.documents = []
        self._created = False

    async def async_drop(self) -> None:
        self.drop()

    def exists(self) -> bool:
        return self._created

    async def async_exists(self) -> bool:
        return self.exists()

    def delete(self) -> bool:
        self.drop()
        return True

    def delete_by_id(self, id: str) -> bool:
        before = len(self.documents)
        self.documents = [doc for doc in self.documents if doc.id != id]
        return len(self.documents) != before

    def delete_by_name(self, name: str) -> bool:
        before = len(self.documents)
        self.documents = [doc for doc in self.documents if doc.name != name]
        return len(self.documents) != before

    def delete_by_metadata(self, metadata: Dict[str, Any]) -> bool:
        before = len(self.documents)
        self.documents = [doc for doc in self.documents if any(doc.meta_data.get(key) != value for key, value in metadata.items())]
        return len(self.documents) != before

    def delete_by_content_id(self, content_id: str) -> bool:
        before = len(self.documents)
        self.documents = [doc for doc in self.documents if doc.content_id != content_id]
        return len(self.documents) != before

    def get_supported_search_types(self) -> List[str]:
        return ["vector"]



def _cosine_similarity(left: List[float], right: List[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if not left_norm or not right_norm:
        return 0.0
    return sum(l_value * r_value for l_value, r_value in zip(left, right)) / (left_norm * right_norm)


class FieldKnowledgeEntry:
    def __init__(self, data: Dict[str, Any]):
        self.field = data.get("field", "")
        self.operator = data.get("operator", "")
        self.value_type = data.get("value_type", "")
        self.description = data.get("description", "") or ""
        self.examples = data.get("examples") or []
        self.negative_examples = data.get("negative_examples") or []
        self.notes = data.get("notes", "") or ""
        self.retrieval_text = data.get("retrieval_text", "") or ""
        self.enums = data.get("enum") or []
        self.search_text = self._build_search_text()

    def _build_search_text(self) -> str:
        parts = [self.field, self.description, self.notes, self.retrieval_text]
        for example in self.examples or []:
            if isinstance(example, dict):
                parts.append(example.get("query", ""))
                parts.append(str(example.get("output", "")))
        for negative_example in self.negative_examples or []:
            if isinstance(negative_example, dict):
                parts.append(negative_example.get("query", ""))
                parts.append(negative_example.get("reason", ""))
        for value in self.enums or []:
            parts.append(str(value))
        return "\n".join(str(part) for part in parts if part)

    def to_context(self) -> str:
        lines = [f"field: {self.field} ({self.operator}, {self.value_type})"]
        if self.description:
            lines.append(f"  desc: {self.description}")
        if self.retrieval_text:
            lines.append(f"  retrieval: {self.retrieval_text}")
        if self.notes:
            lines.append(f"  notes: {self.notes}")
        for example in self.examples or []:
            if isinstance(example, dict):
                lines.append(f"  example: query={example.get('query','')} → {example.get('output','')}")
        for negative_example in self.negative_examples or []:
            if isinstance(negative_example, dict):
                lines.append(f"  NOT: {negative_example.get('query','')} — {negative_example.get('reason','')}")
        if self.enums:
            lines.append(f"  enum: {', '.join(str(value) for value in self.enums)}")
        return "\n".join(lines)


logger = logging.getLogger(__name__)


class ProjectKnowledgeBase:
    """Project-scoped semantic knowledge for Agno agents."""

    KNOWLEDGE_ROOT = KNOWLEDGE_ROOT

    def __init__(self, project_id: str, config_root: Optional[Path] = None):
        self.project_id = project_id
        self.entries: List[FieldKnowledgeEntry] = []
        self._built = False
        self.config_root = config_root
        self.storage_dir = KNOWLEDGE_ROOT / project_id
        self.max_results = get_embedding_config().retrieval_top_k
        self.vector_db = SemanticVectorDb(retrieval_top_k=self.max_results)

    def _path_exists(self, path: Path) -> bool:
        return path.exists()

    def _read_text(self, path: Path) -> str:
        return path.read_text(encoding="utf-8", errors="ignore")

    def _resolve_project_path(self, spec: Any, path_value: str) -> Path:
        path = Path(path_value)
        if path.is_absolute():
            return path
        return Path(getattr(spec, "root", "") or ".") / path

    def _field_documents(self, field_definitions_path: Path) -> List[Document]:
        if not self._path_exists(field_definitions_path):
            return []
        data = yaml.safe_load(self._read_text(field_definitions_path)) or {}
        intents = data.get("intents", [])
        self.entries = [FieldKnowledgeEntry(item) for item in intents if item.get("field")]
        return [
            Document(
                id=f"{self.project_id}:field:{entry.field}:{entry.operator}:{index}",
                name=f"field:{entry.field}",
                content=entry.search_text,
                meta_data={"source": "field_definitions", "field": entry.field, "operator": entry.operator, "value_type": entry.value_type},
            )
            for index, entry in enumerate(self.entries)
        ]

    def _project_documents(self, spec: Any) -> List[Document]:
        documents = []
        for key, path_value in (getattr(spec, "documents", None) or {}).items():
            path = self._resolve_project_path(spec, str(path_value))
            if not self._path_exists(path):
                continue
            content = self._read_text(path).strip()
            if not content:
                continue
            documents.append(
                Document(
                    id=f"{self.project_id}:doc:{key}",
                    name=f"project_doc:{key}",
                    content=f"{key}\n{content}",
                    meta_data={"source": "project_document", "document_key": key, "path": str(path)},
                )
            )
        return documents

    def build_from_project(self, spec: Any) -> None:
        if self._built:
            return
        try:
            self.storage_dir.mkdir(parents=True, exist_ok=True)
            documents = self._project_documents(spec)
            field_path = (getattr(spec, "documents", None) or {}).get("source_field_definitions")
            if field_path:
                documents.extend(self._field_documents(self._resolve_project_path(spec, str(field_path))))
            self.vector_db.create()
            if documents:
                self.vector_db.upsert(f"{self.project_id}:project_knowledge", documents)
            self._built = True
        except Exception as e:
            logger.warning(f"[knowledge_base] build_from_project failed for {self.project_id}: {e} — retrieve() will return empty results")

    def build(self, field_definitions_path: str) -> None:
        if self._built:
            return
        path = Path(field_definitions_path)
        if not path.exists():
            return
        try:
            with open(path, encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            intents = data.get("intents", [])
            self.entries = [FieldKnowledgeEntry(item) for item in intents if item.get("field")]
            documents = [
                Document(
                    id=f"{self.project_id}:{entry.field}:{entry.operator}:{index}",
                    name=entry.field,
                    content=entry.search_text,
                    meta_data={"field": entry.field, "operator": entry.operator, "value_type": entry.value_type},
                )
                for index, entry in enumerate(self.entries)
            ]
            self.vector_db.create()
            self.vector_db.upsert(f"{self.project_id}:field_definitions", documents)
            self._built = True
        except Exception as e:
            logger.warning(f"[knowledge_base] build failed for {self.project_id} from {field_definitions_path}: {e} — retrieve() will return empty results")

    def retrieve(self, query: str, num_documents: Optional[int] = None, **_: Any) -> List[Dict[str, Any]]:
        limit = int(num_documents or self.max_results)
        documents = self.vector_db.search(query=query, limit=limit)
        return [
            {
                "name": document.name,
                "content": document.content,
                "metadata": document.meta_data,
            }
            for document in documents
        ]

    def search(self, query: str, top_k: Optional[int] = None) -> List[FieldKnowledgeEntry]:
        if not self.entries:
            return []
        documents = self.vector_db.search(query=query, limit=top_k or self.max_results)
        fields = [document.meta_data.get("field") for document in documents if document.meta_data.get("field")]
        matched = []
        seen = set()
        for field in fields:
            for entry in self.entries:
                if entry.field == field and (entry.field, entry.operator, entry.value_type) not in seen:
                    matched.append(entry)
                    seen.add((entry.field, entry.operator, entry.value_type))
                    break
        return matched

    def to_context(self, query: str, top_k: Optional[int] = None) -> str:
        entries = self.search(query, top_k)
        if not entries:
            return ""
        lines = [f"// Relevant field definitions for query '{query}':"]
        for entry in entries:
            lines.append(entry.to_context())
        return "\n".join(lines)


_knowledge_bases: Dict[str, ProjectKnowledgeBase] = {}


def get_knowledge_base(project_id: str) -> Optional[ProjectKnowledgeBase]:
    return _knowledge_bases.get(project_id)


def load_knowledge_base(spec_or_project_id: Any, field_definitions_path: Optional[str] = None) -> ProjectKnowledgeBase:
    if hasattr(spec_or_project_id, "project_id"):
        project_id = str(spec_or_project_id.project_id)
        if project_id not in _knowledge_bases:
            kb = ProjectKnowledgeBase(project_id)
            kb.build_from_project(spec_or_project_id)
            _knowledge_bases[project_id] = kb
        return _knowledge_bases[project_id]

    project_id = str(spec_or_project_id)
    if project_id not in _knowledge_bases:
        kb = ProjectKnowledgeBase(project_id)
        if field_definitions_path:
            kb.build(field_definitions_path)
        _knowledge_bases[project_id] = kb
    return _knowledge_bases[project_id]
