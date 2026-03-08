import os
import shutil
import pytest
import asyncio
from nanobot.knowledge.base import Document
from nanobot.knowledge.basic import BasicKnowledgeBase

@pytest.fixture
async def kb(tmp_path):
    # Setup
    persist_path = tmp_path / "knowledge_base"
    knowledge_base = BasicKnowledgeBase(persist_path=str(persist_path))
    yield knowledge_base
    
    # Teardown - handled by tmp_path fixture usually, but we can explicitly reset if needed
    # No explicit close for Chroma client available usually, relying on garbage collection
    pass

@pytest.mark.asyncio
async def test_create_and_get_collection(kb):
    collection_name = "test_collection"
    
    # Test creation
    collection = await kb.create_collection(collection_name)
    assert collection is not None
    assert collection.name == collection_name
    
    # Test listing
    collections = await kb.list_collections()
    assert collection_name in collections
    
    # Test getting existing collection
    retrieved_collection = await kb.get_collection(collection_name)
    assert retrieved_collection is not None
    assert retrieved_collection.name == collection_name

@pytest.mark.asyncio
async def test_add_and_search_documents(kb):
    collection = await kb.create_collection("search_test")
    
    docs = [
        Document(id="1", content="机器学习是人工智能的一个核心领域。", metadata={"category": "AI"}),
        Document(id="2", content="深度学习利用神经网络解决复杂问题。", metadata={"category": "AI"}),
        Document(id="3", content="苹果富含维生素C，是一种健康的水果。", metadata={"category": "Food"}),
        Document(id="4", content="自然语言处理(NLP)关注计算机与人类语言的交互。", metadata={"category": "AI"}),
    ]
    
    await collection.add_documents(docs)
    
    # Test 1: Vector-heavy query (semantic search)
    # "AI的技术" might not match keywords exactly but semantically close to ML/DL
    results = await collection.search("AI的技术", top_k=3)
    # Should retrieve AI related docs
    assert len(results) > 0
    categories = [r.document.metadata.get("category") for r in results]
    assert "AI" in categories

    # Test 2: Keyword-heavy query
    # "维生素C" is a specific keyword in document 3
    results_kw = await collection.search("维生素C", top_k=1)
    assert len(results_kw) > 0
    assert results_kw[0].document.id == "3"
    assert "Keyword" in results_kw[0].reasoning

    # Test 3: Mixed query
    results_mixed = await collection.search("神经网络", top_k=1)
    assert len(results_mixed) > 0
    assert results_mixed[0].document.id == "2"

@pytest.mark.asyncio
async def test_update_documents(kb):
    collection = await kb.create_collection("update_test")
    
    doc = Document(id="doc1", content="旧的内容", metadata={"version": 1})
    await collection.add_documents([doc])
    
    # Update content
    updated_doc = Document(id="doc1", content="新的内容，更新后的版本", metadata={"version": 2})
    await collection.update_documents([updated_doc])
    
    # Search to verify update
    results = await collection.search("更新", top_k=1)
    assert len(results) == 1
    assert results[0].document.content == "新的内容，更新后的版本"
    assert results[0].document.metadata["version"] == 2

@pytest.mark.asyncio
async def test_delete_documents(kb):
    collection = await kb.create_collection("delete_test")
    
    docs = [
        Document(id="1", content="文档1"),
        Document(id="2", content="文档2"),
    ]
    await collection.add_documents(docs)
    
    await collection.delete_documents(["1"])
    
    # Verify deletion
    results = await collection.search("文档1", top_k=5)
    # Should not find document 1 (or score very low if vector still lingers but usually delete removes it)
    # In exact match search, it should be gone. 
    # For vector search, delete should remove it from index.
    ids = [r.document.id for r in results]
    assert "1" not in ids
    assert "2" in ids

@pytest.mark.asyncio
async def test_delete_collection(kb):
    collection_name = "delete_col_test"
    await kb.create_collection(collection_name)
    
    assert collection_name in await kb.list_collections()
    
    await kb.delete_collection(collection_name)
    
    assert collection_name not in await kb.list_collections()
