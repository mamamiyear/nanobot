"""Knowledge base management tool."""

import json
from typing import Any

from loguru import logger

from nanobot.agent.tools.base import Tool
from nanobot.knowledge.base import Document, KnowledgeBase


class KnowledgeTool(Tool):
    """
    Built-in tool to manage the knowledge base (add, update, delete documents).
    """

    def __init__(self, knowledge_base: KnowledgeBase, collection_name: str = "default"):
        self.kb = knowledge_base
        self.collection_name = collection_name

    @property
    def name(self) -> str:
        return "knowledge"

    @property
    def description(self) -> str:
        return """Built-in tool to manage the knowledge base.
Operations:
- add: Add a new document to the knowledge base.
- update: Update an existing document (content and metadata). Note: This replaces the entire document.
- delete: Delete a document by ID.
- get: Get a document by ID.
- search: Search for documents to find their IDs.

Use this tool to persist important information, code snippets, or context that should be available for future sessions.
When adding documents, provide clear content and useful metadata.
When updating or deleting, you must provide the exact document ID (use 'search' first if unknown).
"""

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["add", "update", "delete", "get", "search"],
                    "description": "The operation to perform.",
                },
                "content": {
                    "type": "string",
                    "description": "Document content (required for 'add', optional for 'update').",
                },
                "metadata": {
                    "type": "string",
                    "description": "JSON string of metadata (optional). e.g. '{\"source\": \"chat\", \"topic\": \"python\"}'",
                },
                "id": {
                    "type": "string",
                    "description": "Document ID (required for 'update' and 'delete').",
                },
                "query": {
                    "type": "string",
                    "description": "Search query (required for 'search').",
                },
            },
            "required": ["action"],
        }

    async def execute(
        self,
        action: str,
        content: str | None = None,
        metadata: str | None = None,
        id: str | None = None,
        query: str | None = None,
        **kwargs: Any,
    ) -> str:
        if not self.kb:
            return "Error: Knowledge base not initialized."

        try:
            # Use configured collection name
            collection_name = self.collection_name
            collection = await self.kb.get_collection(collection_name)
            if not collection:
                collection = await self.kb.create_collection(collection_name)

            if action == "add":
                if not content:
                    return "Error: 'content' is required for 'add' action."
                
                meta_dict = {}
                if metadata:
                    try:
                        meta_dict = json.loads(metadata)
                    except json.JSONDecodeError:
                        return "Error: 'metadata' must be a valid JSON string."

                doc = Document(content=content, metadata=meta_dict)
                await collection.add_documents([doc])
                # The ID is generated in add_documents if not provided (by Basic implementation)
                # But Document is a dataclass, so it is mutable. 
                # BasicCollection updates the doc.id in place.
                return f"Document added successfully. ID: {doc.id}"

            elif action == "update":
                if not id:
                    return "Error: 'id' is required for 'update' action."
                
                # Full replacement requires content
                if not content:
                    return "Error: 'content' is required for 'update' action (full replacement)."
                
                meta_dict = {}
                if metadata:
                    try:
                        meta_dict = json.loads(metadata)
                    except json.JSONDecodeError:
                        return "Error: 'metadata' must be a valid JSON string."

                doc = Document(id=id, content=content, metadata=meta_dict)
                await collection.update_documents([doc])
                return f"Document {id} updated."

            elif action == "delete":
                if not id:
                    return "Error: 'id' is required for 'delete' action."
                await collection.delete_documents([id])
                return f"Document {id} deleted."

            elif action == "get":
                if not id:
                    return "Error: 'id' is required for 'get' action."
                doc = await collection.get_document(id)
                if not doc:
                    return f"Document {id} not found."
                return f"ID: {doc.id}\nContent: {doc.content}\nMetadata: {doc.metadata}"

            elif action == "search":
                if not query:
                    return "Error: 'query' is required for 'search' action."
                results = await collection.search(query)
                if not results:
                    return "No documents found."
                
                output = []
                for res in results:
                    doc = res.document
                    output.append(f"ID: {doc.id}\nScore: {res.score:.4f}\nContent: {doc.content[:200]}...\nMetadata: {doc.metadata}\n---")
                return "\n".join(output)

            else:
                return f"Error: Unknown action '{action}'"

        except Exception as e:
            logger.exception(f"Error executing knowledge action '{action}'")
            return f"Error executing knowledge action '{action}': {str(e)}"
