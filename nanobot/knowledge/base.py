from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Dict, Any, Optional

from nanobot.config.schema import KnowledgeBaseConfig


@dataclass
class Document:
    """
    文档对象，知识库的基本存储单元。
    
    Attributes:
        id (str): 文档的唯一标识符。
        content (str): 文档的内容（长字符串）。
        metadata (Dict[str, Any]): 文档的元数据字典。
    """
    content: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    id: Optional[str] = None

    def __post_init__(self):
        # 如果没有提供 ID，可以在实现层生成，或者要求必须提供
        # 这里暂时允许为空，由具体实现决定是否自动生成
        pass


@dataclass
class SearchResult:
    """
    搜索结果对象。
    
    Attributes:
        document (Document): 匹配的文档对象。
        score (float): 匹配分数（越高越好）。
        reasoning (Optional[str]): 匹配理由（可选，例如关键词匹配、向量相似度等说明）。
    """
    document: Document
    score: float
    reasoning: Optional[str] = None


class Collection(ABC):
    """
    集合抽象基类。
    
    集合是文档的逻辑分组，负责具体的文档增删改查及搜索操作。
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """获取集合名称"""
        pass

    @abstractmethod
    async def add_documents(self, documents: List[Document]) -> None:
        """
        向集合中添加文档。
        
        Args:
            documents (List[Document]): 要添加的文档列表。
        """
        pass

    @abstractmethod
    async def update_documents(self, documents: List[Document]) -> None:
        """
        更新集合中的文档。
        通常根据文档 ID 进行更新。
        
        Args:
            documents (List[Document]): 要更新的文档列表。
        """
        pass

    @abstractmethod
    async def delete_documents(self, document_ids: List[str]) -> None:
        """
        从集合中删除文档。
        
        Args:
            document_ids (List[str]): 要删除的文档 ID 列表。
        """
        pass

    @abstractmethod
    async def get_document(self, document_id: str) -> Optional[Document]:
        """
        获取单个文档详情。
        
        Args:
            document_id (str): 文档 ID。
            
        Returns:
            Optional[Document]: 文档对象，如果不存在则返回 None。
        """
        pass

    @abstractmethod
    async def search(self, query: str, top_k: int = 5, **kwargs) -> List[SearchResult]:
        """
        融合搜索接口。
        
        综合向量检索和关键词检索的结果，并进行重排。
        
        Args:
            query (str): 查询文本。
            top_k (int): 返回结果的数量。默认为 5。
            **kwargs: 其他可选参数，例如：
                - vector_weight (float): 向量检索权重。
                - keyword_weight (float): 关键词检索权重。
                - rerank (bool): 是否进行重排。
        
        Returns:
            List[SearchResult]: 排序后的搜索结果列表。
        """
        pass


class KnowledgeBase(ABC):
    """
    知识库抽象基类。
    
    负责管理集合的生命周期。
    """

    @abstractmethod
    async def create_collection(self, name: str, dimension: Optional[int] = None, **kwargs) -> Collection:
        """
        创建一个新的集合。
        
        Args:
            name (str): 集合名称。
            dimension (Optional[int]): 向量维度（如果适用）。
            **kwargs: 其他配置参数。
            
        Returns:
            Collection: 创建的集合对象。
        """
        pass

    @abstractmethod
    async def get_collection(self, name: str) -> Optional[Collection]:
        """
        获取已存在的集合。
        
        Args:
            name (str): 集合名称。
            
        Returns:
            Optional[Collection]: 集合对象，如果不存在则返回 None。
        """
        pass

    @abstractmethod
    async def list_collections(self) -> List[str]:
        """
        列出所有集合名称。
        
        Returns:
            List[str]: 集合名称列表。
        """
        pass

    @abstractmethod
    async def delete_collection(self, name: str) -> None:
        """
        删除指定的集合。
        
        Args:
            name (str): 要删除的集合名称。
        """
        pass


def get_knowledge_base(config: KnowledgeBaseConfig) -> KnowledgeBase:
    """
    Factory method to create a knowledge base instance based on type.
    
    Args:
        kb_type (str): The type of knowledge base (e.g., 'basic').
        persist_path (str): Path to persist data.
        **kwargs: Additional arguments for specific implementations.
        
    Returns:
        KnowledgeBase: An instance of the requested knowledge base.
        
    Raises:
        ValueError: If the kb_type is unknown.
    """
    if config.provider == "basic":
        from .basic import BasicKnowledgeBase
        persist_path = config.basic.persist_path if config.basic and config.basic.persist_path else "~/.nanobot/knowledge"
        return BasicKnowledgeBase(persist_path=persist_path)
    
    if config.provider == "seekdb":
        from .seekdb import SeekKnowledgeBase
        persist_path = config.seekdb.persist_path if config.seekdb and config.seekdb.persist_path else "~/.nanobot/seekdb.db"
        return SeekKnowledgeBase(persist_path=str(persist_path))
    
    if config.provider == "volcengine":
        from .volcengine import VolcengineKnowledgeBase
        vc = config.volcengine
        return VolcengineKnowledgeBase(
            access_key=vc.access_key,
            secret_key=vc.secret_key,
            region=vc.region,
            host=vc.host
        )

    return None
