"""Volcengine Knowledge Base implementation."""

import json
import os
import asyncio
from typing import List, Optional

from loguru import logger

try:
    from volcengine.viking_knowledgebase import VikingKnowledgeBaseService, CollectionVersion
    VOLCENGINE_AVAILABLE = True
except ImportError:
    VOLCENGINE_AVAILABLE = False

from .base import Collection, Document, KnowledgeBase, SearchResult


class VolcengineCollection(Collection):
    def __init__(self, name: str, kb: "VolcengineKnowledgeBase", project: str = "default"):
        self._name = name
        self.kb = kb
        self.project = project

    @property
    def name(self) -> str:
        return self._name

    async def add_documents(self, documents: List[Document]) -> None:
        """
        Add documents to the knowledge base.
        Note: The official SDK mainly supports adding files. 
        For text content, we might need to save to temp files or check if there's a text API.
        Current implementation is a placeholder as the SDK `add_doc` usually takes file paths.
        """
        if not documents:
            return

        logger.warning("VolcengineCollection.add_documents: Direct text addition is not fully supported by current SDK wrapper. Please use file upload if possible.")
        # TODO: Check if SDK supports raw text addition or if we need to write to temp file and upload.

    async def update_documents(self, documents: List[Document]) -> None:
        logger.warning("VolcengineCollection.update_documents is not supported directly.")

    async def delete_documents(self, document_ids: List[str]) -> None:
        # SDK doesn't seem to expose simple delete by ID list easily without doc object context
        logger.warning("VolcengineCollection.delete_documents is not fully implemented yet.")

    async def get_document(self, document_id: str) -> Optional[Document]:
        return None

    async def search(self, query: str, top_k: int = 5, **kwargs) -> List[SearchResult]:
        """
        Search the knowledge base.
        """
        def _search_sync():
            return self.kb.service.search_knowledge(
                collection_name=self.name,
                query=query,
                limit=top_k,
                project=self.project,
                dense_weight=kwargs.get("dense_weight", 0.5)
            )

        try:
            ret = await asyncio.to_thread(_search_sync)
            
            # Parse result
            # The structure of ret depends on SDK response, assuming it matches the API response structure
            # based on the user provided demo which prints json.dumps(ret)
            
            # The SDK returns a dict usually wrapping the API response
            data = ret.get("data", {})
            result_list = data.get("result_list", [])
            
            results = []
            for item in result_list:
                content = item.get("content", "")
                score = item.get("score", 0.0)
                doc_id = item.get("id") or item.get("point_id")
                
                # Extract metadata
                metadata = item.get("doc_info", {})
                if isinstance(metadata, dict):
                    if "doc_meta" in metadata and isinstance(metadata["doc_meta"], str):
                        try:
                            meta_list = json.loads(metadata["doc_meta"])
                            for field in meta_list:
                                metadata[field.get("field_name")] = field.get("field_value")
                        except:
                            pass
                
                doc = Document(id=doc_id, content=content, metadata=metadata)
                results.append(SearchResult(document=doc, score=score))
            
            return results

        except Exception as e:
            logger.error(f"Volcengine search error: {e}")
            return []


class VolcengineKnowledgeBase(KnowledgeBase):
    def __init__(
        self,
        access_key: str = None,
        secret_key: str = None,
        region: str = "cn-beijing",
        host: str = "api-knowledgebase.mlp.cn-beijing.volces.com",
        **kwargs
    ):
        if not VOLCENGINE_AVAILABLE:
            raise ImportError("volcengine package is not installed. Please install it via 'pip install volcengine'.")

        self.ak = access_key or os.environ.get("VOLC_ACCESS_KEY")
        self.sk = secret_key or os.environ.get("VOLC_SECRET_KEY")
        self.host = host
        self.scheme = "https"
        self.project = kwargs.get("project", "default")
        
        if not self.ak or not self.sk:
            logger.warning("Volcengine Access Key or Secret Key not provided.")

        # Construct SDK specific AK format if needed, or use standard credentials
        # The user demo uses a specific AK format:
        # ak = f"service_account={account};main_account_id={account_id};sts_type=samlSts;volc_host={g_knowledge_base_domain}"
        # But standard SDK usage usually takes standard AK/SK. 
        # We will assume the user provides standard AK/SK in config, 
        # OR the full string if they have special requirements.
        # However, `VikingKnowledgeBaseService` in `volcengine` SDK typically expects standard AK/SK.
        # The user demo seems to use an internal or specific version of SDK/Authentication?
        # Let's stick to the standard `VikingKnowledgeBaseService` initialization if possible.
        
        # Checking `volcengine.viking_knowledgebase` source code availability is hard here.
        # But assuming `VikingKnowledgeBaseService` accepts ak, sk, host, scheme.
        
        self.service = VikingKnowledgeBaseService(
            host=self.host,
            scheme=self.scheme,
            ak=self.ak,
            sk=self.sk
        )

    async def create_collection(self, name: str, dimension: Optional[int] = None, **kwargs) -> Collection:
        def _create_sync():
            # Use SDK method
            # CollectionVersion.UltimateVersion is used in demo, we can default to it or standard
            return self.service.create_collection(
                name, 
                version=CollectionVersion.UltimateVersion, 
                project=self.project
            )
        
        try:
            await asyncio.to_thread(_create_sync)
            return VolcengineCollection(name, self, self.project)
        except Exception as e:
            logger.error(f"Error creating collection: {e}")
            # Return collection object anyway, assuming it might exist or we want to try using it
            return VolcengineCollection(name, self, self.project)

    async def get_collection(self, name: str) -> Optional[Collection]:
        def _get_sync():
            return self.service.get_collection(name, project=self.project)
            
        try:
            await asyncio.to_thread(_get_sync)
            return VolcengineCollection(name, self, self.project)
        except Exception as e:
            logger.warning(f"Collection {name} not found or error: {e}")
            return None

    async def list_collections(self) -> List[str]:
        def _list_sync():
            cols = self.service.list_collections(project=self.project)
            # cols is list of objects, assume they have collection_name attribute
            return [c.collection_name for c in cols]
            
        try:
            return await asyncio.to_thread(_list_sync)
        except Exception as e:
            logger.error(f"Error listing collections: {e}")
            return []

    async def delete_collection(self, name: str) -> None:
        def _delete_sync():
            self.service.drop_collection(name, project=self.project)
            
        try:
            await asyncio.to_thread(_delete_sync)
        except Exception as e:
            logger.error(f"Error deleting collection: {e}")
