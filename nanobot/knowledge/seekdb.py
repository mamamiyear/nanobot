
import os
import uuid
import asyncio
import jieba
import pyseekdb
from loguru import logger
from typing import List, Optional, Dict, Any
from .base import KnowledgeBase, Collection, Document, SearchResult

class SeekCollection(Collection):
    def __init__(self, name: str, collection: Any):
        self._name = name
        self._collection = collection

    @property
    def name(self) -> str:
        return self._name

    async def add_documents(self, documents: List[Document]) -> None:
        if not documents:
            return

        ids = []
        doc_contents = []
        metadatas = []

        for doc in documents:
            if not doc.id:
                doc.id = str(uuid.uuid4())
            ids.append(doc.id)
            doc_contents.append(doc.content)
            # Ensure metadata is flat or handle nesting if seekdb supports it
            # pyseekdb metadata usually supports simple key-value pairs
            metadatas.append(doc.metadata if doc.metadata else {})

        # pyseekdb collection.add
        await asyncio.to_thread(
            self._collection.add,
            ids=ids,
            documents=doc_contents,
            metadatas=metadatas
        )

    async def update_documents(self, documents: List[Document]) -> None:
        if not documents:
            return

        # Prepare data
        ids = []
        doc_contents = []
        metadatas = []

        for doc in documents:
            if not doc.id:
                continue
            ids.append(doc.id)
            doc_contents.append(doc.content)
            metadatas.append(doc.metadata if doc.metadata else {})

        if not ids:
            return

        def _update_sync():
            # Try upsert first
            try:
                if hasattr(self._collection, 'upsert'):
                    self._collection.upsert(
                        ids=ids,
                        documents=doc_contents,
                        metadatas=metadatas
                    )
                    return
            except Exception as e:
                logger.warning(f"SeekDB upsert failed, falling back to delete-then-add: {e}")

            # Fallback: Delete then Add
            try:
                self._collection.delete(ids=ids)
            except Exception:
                pass
            
            self._collection.add(
                ids=ids,
                documents=doc_contents,
                metadatas=metadatas
            )

        await asyncio.to_thread(_update_sync)

    async def delete_documents(self, document_ids: List[str]) -> None:
        if not document_ids:
            return
        await asyncio.to_thread(self._collection.delete, ids=document_ids)

    async def get_document(self, document_id: str) -> Optional[Document]:
        if not document_id:
            return None
        
        # collection.get(ids=[...])
        try:
            res = await asyncio.to_thread(self._collection.get, ids=[document_id])
            if res and res['ids']:
                content = res['documents'][0] if res.get('documents') else ""
                metadata = res['metadatas'][0] if res.get('metadatas') else {}
                return Document(id=document_id, content=content, metadata=metadata)
        except Exception:
            pass
        return None

    async def search(self, query: str, top_k: int = 5, **kwargs) -> List[SearchResult]:
        """
        Multi-path recall:
        1. Semantic Search (Vector)
        2. Keyword Search (Jieba segmentation + Full-text filter)
        3. RRF Fusion
        """
        # 1. Semantic Search
        try:
            vec_res = await asyncio.to_thread(
                self._collection.query,
                query_texts=[query],
                n_results=top_k * 2
            )
        except Exception as e:
            logger.error(f"SeekDB Vector Search Error: {e}")
            vec_res = {'ids': [[]], 'distances': [[]], 'documents': [[]], 'metadatas': [[]]}

        # Parse Vector Results
        vec_docs = {} # id -> {'doc': Document, 'rank': int, 'score': float}
        if vec_res.get('ids') and vec_res['ids'][0]:
            ids = vec_res['ids'][0]
            dists = vec_res['distances'][0] if vec_res.get('distances') else [0]*len(ids)
            docs = vec_res['documents'][0] if vec_res.get('documents') else [""]*len(ids)
            metas = vec_res['metadatas'][0] if vec_res.get('metadatas') else [{}]*len(ids)
            
            for rank, (doc_id, dist, content, meta) in enumerate(zip(ids, dists, docs, metas)):
                doc = Document(id=doc_id, content=content, metadata=meta)
                # Distance in Chroma/SeekDB usually: smaller is better.
                # RRF uses rank, so raw distance doesn't matter much for fusion logic,
                # but we store it for reasoning.
                vec_docs[doc_id] = {'doc': doc, 'rank': rank, 'dist': dist}

        # 2. Keyword Search (Jieba + Filter)
        kw_docs = {}
        try:
            keywords = list(jieba.cut(query))
            keywords = [k.strip() for k in keywords if k.strip()]
            
            if keywords:
                # Construct $or filter
                # where_document={"$or": [{"$contains": k} for k in keywords]}
                # If only one keyword, direct dict.
                if len(keywords) == 1:
                    where_doc = {"$contains": keywords[0]}
                else:
                    where_doc = {"$or": [{"$contains": k} for k in keywords]}
                
                # Use query_texts=[query] to rank by semantic similarity even for keyword matches
                kw_res = await asyncio.to_thread(
                    self._collection.query,
                    query_texts=[query],
                    where_document=where_doc,
                    n_results=top_k * 2
                )
                
                if kw_res.get('ids') and kw_res['ids'][0]:
                    ids = kw_res['ids'][0]
                    dists = kw_res['distances'][0] if kw_res.get('distances') else [0]*len(ids)
                    docs = kw_res['documents'][0] if kw_res.get('documents') else [""]*len(ids)
                    metas = kw_res['metadatas'][0] if kw_res.get('metadatas') else [{}]*len(ids)
                    
                    for rank, (doc_id, dist, content, meta) in enumerate(zip(ids, dists, docs, metas)):
                        doc = Document(id=doc_id, content=content, metadata=meta)
                        kw_docs[doc_id] = {'doc': doc, 'rank': rank, 'dist': dist}
        except Exception as e:
            logger.error(f"SeekDB Keyword Search Error: {e}")

        # 3. RRF Fusion
        k = 60
        combined_scores = {}
        all_docs_map = {}

        for doc_id, info in vec_docs.items():
            all_docs_map[doc_id] = info['doc']
            combined_scores[doc_id] = combined_scores.get(doc_id, 0) + (1 / (k + info['rank']))
            
        for doc_id, info in kw_docs.items():
            all_docs_map[doc_id] = info['doc']
            combined_scores[doc_id] = combined_scores.get(doc_id, 0) + (1 / (k + info['rank']))

        sorted_ids = sorted(combined_scores.items(), key=lambda x: x[1], reverse=True)
        
        final_results = []
        for doc_id, score in sorted_ids[:top_k]:
            doc = all_docs_map[doc_id]
            reasoning_parts = []
            if doc_id in vec_docs:
                reasoning_parts.append(f"Vector(dist={vec_docs[doc_id]['dist']:.4f})")
            if doc_id in kw_docs:
                reasoning_parts.append(f"Keyword(dist={kw_docs[doc_id]['dist']:.4f})")
            
            reasoning = ", ".join(reasoning_parts)
            final_results.append(SearchResult(document=doc, score=score, reasoning=reasoning))

        return final_results


class SeekKnowledgeBase(KnowledgeBase):
    def __init__(self, persist_path: str, **kwargs):
        self.persist_path = os.path.expanduser(persist_path)
        # Assuming database name is fixed or derived from path
        # In pyseekdb embedded, path is the db file.
        # But Client needs database name.
        # We can use a default database name "nanobot_kb"
        self.db_name = "nanobot_kb"
        
        # Ensure directory exists
        db_dir = os.path.dirname(self.persist_path)
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir, exist_ok=True)
            
        # Initialize Admin to create DB if needed
        try:
            admin = pyseekdb.AdminClient(path=self.persist_path)
            try:
                admin.create_database(self.db_name)
            except Exception:
                # Likely exists
                pass
        except Exception as e:
            # Maybe path issue or other error
            logger.warning(f"SeekDB Admin Init Warning: {e}")

        # Initialize Client
        self.client = pyseekdb.Client(path=self.persist_path, database=self.db_name)

    async def create_collection(self, name: str, dimension: Optional[int] = None, **kwargs) -> Collection:
        # pyseekdb create_collection
        # dimension is optional, handled by embedding function (default)
        col = await asyncio.to_thread(self.client.create_collection, name=name)
        return SeekCollection(name, col)

    async def get_collection(self, name: str) -> Optional[Collection]:
        try:
            # Try get_collection
            # If pyseekdb raises error for non-existent, catch it
            # But requirements say "automatically create if not exists"
            # Some SDKs have get_or_create_collection, let's try that or fallback
            try:
                col = await asyncio.to_thread(self.client.get_collection, name=name)
            except (ValueError, Exception):
                col = await asyncio.to_thread(self.client.create_collection, name=name)
            
            return SeekCollection(name, col)
        except Exception as e:
            # Fallback for safety
            logger.error(f"Error getting collection {name}: {e}")
            # Try create just in case
            try:
                col = await asyncio.to_thread(self.client.create_collection, name=name)
                return SeekCollection(name, col)
            except:
                return None

    async def list_collections(self) -> List[str]:
        cols = await asyncio.to_thread(self.client.list_collections)
        # cols might be list of objects or strings
        return [c.name for c in cols]

    async def delete_collection(self, name: str) -> None:
        try:
            await asyncio.to_thread(self.client.delete_collection, name)
        except Exception:
            pass

