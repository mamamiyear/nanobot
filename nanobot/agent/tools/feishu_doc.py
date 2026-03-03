"""Feishu/Lark document tool."""

import json
import re
from typing import Any

from loguru import logger

from nanobot.agent.tools.base import Tool

try:
    import lark_oapi as lark
    from lark_oapi.api.docx.v1 import RawContentDocumentRequest
    # Attempt to import wiki v2 if available
    try:
        from lark_oapi.api.wiki.v2 import GetNodeSpaceRequest
    except ImportError:
        GetNodeSpaceRequest = None

    # Attempt to import docs v1 if available (for old docs)
    try:
        from lark_oapi.api.docs.v1 import GetContentRequest
    except ImportError:
        GetContentRequest = None

    FEISHU_AVAILABLE = True
except ImportError:
    FEISHU_AVAILABLE = False
    lark = None
    RawContentDocumentRequest = None
    GetContentRequest = None
    GetNodeSpaceRequest = None


class FeishuDocTool(Tool):
    """Read content from Feishu/Lark documents (Docs and Docx)."""

    name = "feishu_doc"
    description = """Read content from Feishu/Lark documents. Supports Docs 1.0 (doc), Docs 2.0 (docx), and Wiki.
IF you receive a url like:
"https://example_org_id.feishu.cn/wiki/:wiki_token"
"https://example_org_id.feishu.cn/docx/:docx_token"
"https://example_org_id.feishu.cn/doc/:doc_token"
You can try use this tool to get feishu document content."""
    parameters = {
        "type": "object",
        "properties": {
            "document_id": {
                "type": "string",
                "description": "The document token or full URL (e.g., 'doxcn...', 'https://.../docx/doxcn...')"
            },
        },
        "required": ["document_id"]
    }

    def __init__(self, app_id: str | None = None, app_secret: str | None = None):
        self.app_id = app_id
        self.app_secret = app_secret
        self._client = None

    @property
    def client(self) -> Any:
        if not self._client and self.app_id and self.app_secret and FEISHU_AVAILABLE:
            self._client = lark.Client.builder() \
                .app_id(self.app_id) \
                .app_secret(self.app_secret) \
                .log_level(lark.LogLevel.INFO) \
                .build()
        return self._client

    def _extract_token(self, text: str) -> tuple[str, str]:
        """Extract token and type from URL or raw token."""
        # Handle full URL
        # e.g. https://domain.feishu.cn/docx/doxcn...
        # e.g. https://domain.feishu.cn/docs/doccn...
        # e.g. https://domain.feishu.cn/wiki/wikcn...
        
        url_match = re.search(r'/(docx|docs|wiki)/([a-zA-Z0-9]+)', text)
        if url_match:
            doc_type, token = url_match.groups()
            return token, doc_type

        # Handle raw token
        if text.startswith("dox"):
            return text, "docx"
        if text.startswith("doc"):
            return text, "docs"
        if text.startswith("wik"):
            return text, "wiki"
        
        # Default to docx if unknown but looks like token
        return text, "docx"

    async def execute(self, document_id: str, **kwargs: Any) -> str:
        if not FEISHU_AVAILABLE:
            return "Error: lark-oapi not installed. Run: pip install lark-oapi"

        if not self.app_id or not self.app_secret:
            return "Error: Feishu app_id and app_secret not configured in channels.feishu"

        token, doc_type = self._extract_token(document_id)
        
        try:
            if doc_type == "docx":
                return await self._read_docx(token)
            elif doc_type == "docs":
                return await self._read_docs(token)
            elif doc_type == "wiki":
                return await self._read_wiki(token)
            else:
                return f"Error: Unsupported document type: {doc_type}"
        except Exception as e:
            logger.exception(f"Failed to read Feishu doc {token}")
            return f"Error reading document: {str(e)}"

    async def _read_docx(self, token: str) -> str:
        """Read Docs 2.0 (docx) content."""
        # Use raw_content API to get plain text
        request = RawContentDocumentRequest.builder() \
            .document_id(token) \
            .build()
        
        response = await self.client.docx.v1.document.araw_content(request)
        
        if not response.success():
            return f"Error reading docx: {response.code} - {response.msg}"
        
        # The response data content is the text
        return response.data.content

    async def _read_docs(self, token: str) -> str:
        """Read Docs 1.0 (doc) content."""
        if not GetContentRequest:
            return "Error: Docs 1.0 API not available in this SDK version"

        request = GetContentRequest.builder() \
            .doc_token(token) \
            .build()
        
        response = await self.client.docs.v1.content.aget(request)
        
        if not response.success():
            return f"Error reading doc: {response.code} - {response.msg}"
            
        # Docs 1.0 returns a JSON structure of content
        # We need to extract text from it
        return self._parse_docs_content(response.data.content)

    async def _read_wiki(self, token: str) -> str:
        """Read Wiki content by resolving its real object token."""
        if not GetNodeSpaceRequest:
            return "Error: Wiki API not available in this SDK version"

        # 1. Get node info to find the real object token
        request = GetNodeSpaceRequest.builder() \
            .token(token) \
            .build()
        
        response = await self.client.wiki.v2.space.aget_node(request)
        
        if not response.success():
            return f"Error reading wiki node info: {response.code} - {response.msg}"
            
        node = response.data.node
        obj_token = node.obj_token
        obj_type = node.obj_type
        
        # 2. Read content based on object type
        if obj_type == "docx":
            return await self._read_docx(obj_token)
        elif obj_type == "doc":
            return await self._read_docs(obj_token)
        else:
            return f"Error: Unsupported wiki object type: {obj_type}"

    def _parse_docs_content(self, content_str: str) -> str:
        """Parse Docs 1.0 content JSON to text."""
        try:
            content = json.loads(content_str)
            text_parts = []
            
            # Simple traversal of the content structure
            # This depends on the specific structure of Docs 1.0 JSON
            # Usually it has body -> block -> paragraph -> elements -> textRun
            
            if "body" in content and "blocks" in content["body"]:
                for block in content["body"]["blocks"]:
                    if block["type"] == "paragraph":
                        para = block.get("paragraph", {})
                        for element in para.get("elements", []):
                            if element["type"] == "textRun":
                                text_parts.append(element["textRun"]["text"])
                        text_parts.append("\n")
            
            return "".join(text_parts)
        except Exception as e:
            return f"Error parsing docs content: {str(e)}\nRaw content: {content_str[:500]}..."
