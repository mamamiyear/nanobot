# 知识库组件设计文档

## 1. 概述

本组件旨在为 Nanobot 提供一个灵活、高效的知识库检索能力。采用“向量检索 + 关键词检索”的多路召回策略，并引入重排机制，以提高检索结果的准确性和相关性。

## 2. 核心概念

- **Document (文档)**: 知识库存储的基本单位，包含内容(Content)和元数据(Metadata)。
- **Collection (集合)**: 文档的逻辑分组，类似于数据库中的 Table。每个集合拥有独立的配置（如向量维度、距离度量方式等）。
- **Embedding (向量)**: 文本内容的向量化表示，用于语义相似度计算。
- **Keyword (关键词)**: 从文本中提取的关键信息，用于精确匹配。

## 3. 架构设计

### 3.1 抽象层

定义统一的接口规范，屏蔽底层具体实现的差异。主要包含以下抽象基类：

- `KnowledgeBase`: 知识库顶层接口，负责集合的生命周期管理（创建、删除、列出）。
- `Collection`: 集合操作接口，负责文档的增删改查及搜索。
- `Document`: 数据模型，定义文档结构。

### 3.2 实现层 (未来规划)

- **向量存储**: 基于 ChromaDB 或 Milvus 等实现，负责向量检索。
- **关键词存储**: 基于 Whoosh 或 Elasticsearch 等倒排索引实现，负责关键词匹配。
- **混合检索逻辑**: 封装多路召回与重排算法。

## 4. 接口详细定义

### 4.1 数据模型 (Data Model)

#### `Document`

```python
@dataclass
class Document:
    id: str                  # 文档唯一标识
    content: str             # 文档内容（长文本）
    metadata: Dict[str, Any] # 元数据（字典）
    embedding: Optional[List[float]] = None # 预留：向量表示
    keywords: Optional[List[str]] = None    # 预留：关键词列表
```

### 4.2 知识库管理接口 (`KnowledgeBase`)

负责管理 `Collection` 对象。

- `create_collection(name: str, dimension: int, metadata: Optional[Dict] = None) -> Collection`: 创建一个新的集合。
- `get_collection(name: str) -> Collection`: 获取已存在的集合。
- `list_collections() -> List[str]`: 列出所有集合名称。
- `delete_collection(name: str) -> None`: 删除集合。

### 4.3 集合操作接口 (`Collection`)

负责具体的文档管理和检索操作。

#### 文档操作

- `add_documents(documents: List[Document]) -> None`: 添加文档。
- `update_documents(documents: List[Document]) -> None`: 更新文档。
- `delete_documents(ids: List[str]) -> None`: 删除文档。
- `get_document(id: str) -> Optional[Document]`: 获取单个文档详情。

#### 搜索操作

- `search(query: str, top_k: int = 10, **kwargs) -> List[Document]`: 融合搜索接口。

### 4.4 融合搜索流程

1.  **查询预处理**:
    - 对用户查询 `query` 进行分词，提取关键词。
    - 对用户查询 `query` 进行向量化，生成 `query_embedding`。

2.  **多路召回**:
    - **向量召回**: 基于 `query_embedding` 在向量数据库中检索 Top-N 文档。
    - **关键词召回**: 基于提取的关键词在倒排索引中检索 Top-N 文档。

3.  **结果合并与重排**:
    - 合并两路召回结果，去重。
    - 使用 Cross-Encoder 或其他 Rerank 模型对合并后的结果进行打分重排。
    - 返回 Top-K 结果。

## 5. 实现计划

1.  定义 `base.py` 中的抽象基类。
2.  实现具体的 `ChromaKnowledgeBase` (示例) 或 `MemoryKnowledgeBase` (用于测试)。
3.  集成 Embedding 模型和 Rerank 模型。
