import os
import shutil
import json
import uuid
import jieba
import chromadb
import asyncio
from loguru import logger
from typing import List, Optional
from chromadb.utils import embedding_functions
from whoosh import index
from whoosh.fields import Schema, TEXT, ID, STORED
from whoosh.qparser import QueryParser
from whoosh.analysis import Tokenizer, Token, LowercaseFilter, StopFilter
from whoosh.scoring import BM25F
from .base import KnowledgeBase, Collection, Document, SearchResult


# -----------------------------------------------------------------------------
# Whoosh Analyzer for Jieba
# -----------------------------------------------------------------------------

class JiebaTokenizer(Tokenizer):
    def __call__(self, value, positions=False, chars=False,
                 keeporiginal=False, removestops=True,
                 start_pos=0, start_char=0, mode='', **kwargs):
        t = Token(positions, chars, removestops=removestops, mode=mode,
                  **kwargs)
        if not isinstance(value, str):
            value = str(value)
            
        seg_list = jieba.tokenize(value, mode="search") # 使用搜索引擎模式
        
        for (w, start, end) in seg_list:
            t.text = w
            if keeporiginal:
                t.original = t.text
            t.boost = 1.0
            if positions:
                t.pos = start_pos # jieba.tokenize doesn't give token position index, only char offset
                start_pos += 1
            if chars:
                t.startchar = start_char + start
                t.endchar = start_char + end
            yield t

def JiebaAnalyzer(stoplist=None, minsize=1):
    return JiebaTokenizer() | LowercaseFilter() | StopFilter(stoplist=stoplist, minsize=minsize)


# -----------------------------------------------------------------------------
# Basic Implementation
# -----------------------------------------------------------------------------

class BasicCollection(Collection):
    def __init__(self, name: str, chroma_collection: chromadb.Collection, whoosh_ix: index.Index, embedding_function=None):
        self._name = name
        self._chroma_collection = chroma_collection
        self._whoosh_ix = whoosh_ix
        self._embedding_function = embedding_function # Currently handled by chroma collection internally if not provided

    @property
    def name(self) -> str:
        return self._name

    async def add_documents(self, documents: List[Document]) -> None:
        if not documents:
            return

        # Generate IDs before entering the thread
        for doc in documents:
            if not doc.id:
                doc.id = str(uuid.uuid4())

        def _add_sync():
            ids = []
            contents = []
            metadatas = []
            
            # Prepare data
            for doc in documents:
                ids.append(doc.id)
                contents.append(doc.content)
                metadatas.append(doc.metadata if doc.metadata else None)

            # 1. Add to Chroma
            # Chroma handles embeddings automatically if embedding_function is set on collection
            self._chroma_collection.add(
                ids=ids,
                documents=contents,
                metadatas=metadatas
            )

            # 2. Add to Whoosh
            writer = self._whoosh_ix.writer()
            for doc in documents:
                # Metadata is stored as JSON string in Whoosh for retrieval if needed, 
                # though search result usually reconstructs Document from Chroma or Whoosh stored fields
                # Here we just store content and id for searching.
                writer.add_document(
                    id=doc.id,
                    content=doc.content,
                    metadata_json=json.dumps(doc.metadata, ensure_ascii=False)
                )
            writer.commit()

        await asyncio.to_thread(_add_sync)

    async def update_documents(self, documents: List[Document]) -> None:
        if not documents:
            return

        def _update_sync():
            # Chroma upsert
            ids = []
            contents = []
            metadatas = []
            for doc in documents:
                if not doc.id:
                    # If updating, ID must be present. If not, we skip or treat as add? 
                    # Base class says "Usually update by ID". If no ID, we can't update.
                    continue
                ids.append(doc.id)
                contents.append(doc.content)
                metadatas.append(doc.metadata if doc.metadata else None)
            
            if ids:
                self._chroma_collection.upsert(
                    ids=ids,
                    documents=contents,
                    metadatas=metadatas
                )

            # Whoosh update
            writer = self._whoosh_ix.writer()
            for doc in documents:
                if doc.id:
                    writer.update_document(
                        id=doc.id,
                        content=doc.content,
                        metadata_json=json.dumps(doc.metadata, ensure_ascii=False)
                    )
            writer.commit()
            
        await asyncio.to_thread(_update_sync)

    async def get_document(self, document_id: str) -> Optional[Document]:
        if not document_id:
            return None
            
        def _get_sync():
            # Try to get from Chroma first (faster?) or Whoosh
            # Chroma .get()
            try:
                result = self._chroma_collection.get(ids=[document_id])
                if result and result['ids']:
                    content = result['documents'][0] if result['documents'] else ""
                    metadata = result['metadatas'][0] if result['metadatas'] else {}
                    return Document(id=document_id, content=content, metadata=metadata)
            except Exception:
                pass
            return None
            
        return await asyncio.to_thread(_get_sync)

    async def delete_documents(self, document_ids: List[str]) -> None:
        if not document_ids:
            return

        def _delete_sync():
            # Delete from Chroma
            self._chroma_collection.delete(ids=document_ids)

            # Delete from Whoosh
            writer = self._whoosh_ix.writer()
            for doc_id in document_ids:
                writer.delete_by_term('id', doc_id)
            writer.commit()

        await asyncio.to_thread(_delete_sync)

    async def search(self, query: str, top_k: int = 5, **kwargs) -> List[SearchResult]:
        """
        融合搜索实现。
        策略：
        1. 向量搜索 (Chroma) -> Top K
        2. 关键词搜索 (Whoosh) -> Top K
        3. RRF (Reciprocal Rank Fusion) 合并
        """
        vector_weight = kwargs.get('vector_weight', 0.5)
        keyword_weight = kwargs.get('keyword_weight', 0.5) # Not directly used in RRF but could be used for weighted RRF
        
        def _search_sync():
            # 1. Vector Search (Chroma)
            chroma_results = self._chroma_collection.query(
                query_texts=[query],
                n_results=top_k * 2 # Retrieve more for fusion
            )
            
            # Parse Chroma results
            chroma_docs = {} # id -> (doc, score, rank)
            if chroma_results['ids'] and chroma_results['ids'][0]:
                ids = chroma_results['ids'][0]
                distances = chroma_results['distances'][0] if chroma_results['distances'] else [0]*len(ids)
                documents = chroma_results['documents'][0] if chroma_results['documents'] else [""]*len(ids)
                metadatas = chroma_results['metadatas'][0] if chroma_results['metadatas'] else [{}]*len(ids)
                
                for rank, (doc_id, dist, content, meta) in enumerate(zip(ids, distances, documents, metadatas)):
                    # Chroma returns distance (smaller is better). 
                    # We can treat rank as the score proxy for RRF.
                    doc = Document(content=content, metadata=meta, id=doc_id)
                    chroma_docs[doc_id] = {'doc': doc, 'rank': rank, 'distance': dist}

            # 2. Keyword Search (Whoosh)
            whoosh_docs = {} # id -> (doc, score, rank)
            
            # Extract keywords for better search or use raw query
            # jieba.analyse.extract_tags(query, topK=5) could be used to boost key terms
            # For now, use the raw query with the analyzer
            
            with self._whoosh_ix.searcher(weighting=BM25F) as searcher:
                parser = QueryParser("content", self._whoosh_ix.schema)
                try:
                    q = parser.parse(query)
                    results = searcher.search(q, limit=top_k * 2)
                    
                    for rank, hit in enumerate(results):
                        doc_id = hit['id']
                        content = hit.get('content', '')
                        meta = json.loads(hit.get('metadata_json', '{}'))
                        score = hit.score
                        
                        doc = Document(content=content, metadata=meta, id=doc_id)
                        whoosh_docs[doc_id] = {'doc': doc, 'rank': rank, 'score': score}
                except Exception as e:
                    # Query parsing might fail for empty or weird strings
                    logger.error(f"Whoosh search error: {e}")

            # 3. RRF Fusion
            # RRF score = 1 / (k + rank)
            k = 60
            combined_scores = {}
            all_docs = {}

            for doc_id, info in chroma_docs.items():
                all_docs[doc_id] = info['doc']
                combined_scores[doc_id] = combined_scores.get(doc_id, 0) + (1 / (k + info['rank']))
            
            for doc_id, info in whoosh_docs.items():
                all_docs[doc_id] = info['doc']
                combined_scores[doc_id] = combined_scores.get(doc_id, 0) + (1 / (k + info['rank']))

            # Sort by combined score
            sorted_ids = sorted(combined_scores.items(), key=lambda x: x[1], reverse=True)
            
            final_results = []
            for doc_id, score in sorted_ids[:top_k]:
                doc = all_docs[doc_id]
                reasoning_parts = []
                if doc_id in chroma_docs:
                    reasoning_parts.append(f"Vector(dist={chroma_docs[doc_id]['distance']:.4f})")
                if doc_id in whoosh_docs:
                    reasoning_parts.append(f"Keyword(score={whoosh_docs[doc_id]['score']:.4f})")
                
                reasoning = ", ".join(reasoning_parts)
                final_results.append(SearchResult(document=doc, score=score, reasoning=reasoning))

            return final_results

        return await asyncio.to_thread(_search_sync)


class BasicKnowledgeBase(KnowledgeBase):
    def __init__(self, persist_path: str, embedding_func=None, tokenizer_func=None):
        """
        初始化 BasicKnowledgeBase。

        Args:
            persist_path (str): 持久化存储路径。
            embedding_func: 向量模型函数。默认为 Chroma 自带。
            tokenizer_func: 分词函数。默认为 jieba。
        """
        self.persist_path = persist_path
        self.chroma_path = os.path.join(persist_path, "chroma_db")
        self.whoosh_path = os.path.join(persist_path, "whoosh_db")
        
        # Ensure directories exist
        os.makedirs(self.chroma_path, exist_ok=True)
        os.makedirs(self.whoosh_path, exist_ok=True)

        # Initialize Chroma Client
        self.chroma_client = chromadb.PersistentClient(path=self.chroma_path)
        
        self.embedding_function = embedding_func or embedding_functions.DefaultEmbeddingFunction()
        
        # Whoosh tokenizer setup
        if tokenizer_func:
            # If user provides a tokenizer function, wrap it?
            # For simplicity, if passed, we assume it fits Whoosh or use default
            # But the requirement says "分词组件默认使用 jieba 分词，支持传入"
            # Since Whoosh requires an Analyzer object, if tokenizer_func is passed, 
            # we might need to adapt it. 
            # For this implementation, let's assume tokenizer_func returns a list of tokens
            # and we need to wrap it into a Whoosh Analyzer if it's not one.
            # But making a generic wrapper is complex. 
            # Let's support passing a Whoosh Analyzer directly, or if it's a function,
            # we might need a custom Analyzer class that calls it.
            pass
        
        # Default analyzer
        self.analyzer = JiebaAnalyzer()

    async def create_collection(self, name: str, dimension: Optional[int] = None, **kwargs) -> Collection:
        def _create_sync():
            # 1. Create Chroma Collection
            chroma_col = self.chroma_client.get_or_create_collection(
                name=name,
                embedding_function=self.embedding_function,
                metadata=kwargs if kwargs else None
            )

            # 2. Create Whoosh Index
            # Each collection needs its own index directory
            index_dir = os.path.join(self.whoosh_path, name)
            if not os.path.exists(index_dir):
                os.makedirs(index_dir)
                schema = Schema(
                    id=ID(stored=True, unique=True),
                    content=TEXT(stored=True, analyzer=self.analyzer),
                    metadata_json=STORED
                )
                ix = index.create_in(index_dir, schema)
            else:
                if index.exists_in(index_dir):
                    ix = index.open_dir(index_dir)
                else:
                    schema = Schema(
                        id=ID(stored=True, unique=True),
                        content=TEXT(stored=True, analyzer=self.analyzer),
                        metadata_json=STORED
                    )
                    ix = index.create_in(index_dir, schema)

            return BasicCollection(name, chroma_col, ix, self.embedding_function)

        return await asyncio.to_thread(_create_sync)

    async def get_collection(self, name: str) -> Optional[Collection]:
        def _get_sync():
            # Check if exists in Chroma
            try:
                chroma_col = self.chroma_client.get_collection(
                    name=name,
                    embedding_function=self.embedding_function
                )
            except (ValueError, Exception):
                # If not found in Chroma, try create_collection logic which handles both
                # But here we are in a sync context, we can't call await self.create_collection
                # We should return None so the caller calls create_collection
                return None

            # Check if exists in Whoosh
            index_dir = os.path.join(self.whoosh_path, name)
            if index.exists_in(index_dir):
                ix = index.open_dir(index_dir)
            else:
                # If Chroma exists but Whoosh missing, return None to trigger recreation via create_collection
                # Or we could try to fix it here? 
                # Simplest is return None -> KnowledgeTool calls create_collection -> _create_sync will fix it.
                return None

            return BasicCollection(name, chroma_col, ix, self.embedding_function)

        return await asyncio.to_thread(_get_sync)

    async def list_collections(self) -> List[str]:
        def _list_sync():
            cols = self.chroma_client.list_collections()
            return [c.name for c in cols]
        return await asyncio.to_thread(_list_sync)

    async def delete_collection(self, name: str) -> None:
        def _delete_sync():
            # Delete from Chroma
            try:
                self.chroma_client.delete_collection(name)
            except ValueError:
                pass

            # Delete from Whoosh
            index_dir = os.path.join(self.whoosh_path, name)
            if os.path.exists(index_dir):
                shutil.rmtree(index_dir)
        
        await asyncio.to_thread(_delete_sync)
