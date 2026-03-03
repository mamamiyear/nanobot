"""Feishu/Lark document tool."""

import json
import re
from typing import Any

from loguru import logger

from nanobot.agent.tools.base import Tool

try:
    import lark_oapi as lark
    from lark_oapi.api.docx.v1 import RawContentDocumentRequest
    try:
        from lark_oapi.api.docx.v1 import ListDocumentBlockRequest
    except ImportError:
        ListDocumentBlockRequest = None
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
    try:
        from lark_oapi.api.bitable.v1 import (
            ListAppTableFieldRequest,
            ListAppTableRecordRequest,
            ListAppTableRequest,
        )
    except ImportError:
        ListAppTableRequest = None
        ListAppTableFieldRequest = None
        ListAppTableRecordRequest = None

    FEISHU_AVAILABLE = True
except ImportError:
    FEISHU_AVAILABLE = False
    lark = None
    RawContentDocumentRequest = None
    ListDocumentBlockRequest = None
    GetContentRequest = None
    GetNodeSpaceRequest = None
    ListAppTableRequest = None
    ListAppTableFieldRequest = None
    ListAppTableRecordRequest = None


class FeishuDocTool(Tool):
    """Read content from Feishu/Lark documents (Docs and Docx)."""

    name = "feishu_doc"
    description = """Built-in tool to read content from Feishu/Lark documents.
Supports Docs 1.0 (doc), Docs 2.0 (docx), Wiki, and Bitable(Base).
If you receive a url like:
"https://example_org_id.feishu.cn/wiki/:wiki_token"
"https://example_org_id.feishu.cn/docx/:docx_token"
"https://example_org_id.feishu.cn/doc/:doc_token"
"https://example_org_id.feishu.cn/base/:app_token"
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
        
        url_match = re.search(r'/(docx|docs|wiki|base|bitable)/([a-zA-Z0-9_-]+)', text)
        if url_match:
            doc_type, token = url_match.groups()
            if doc_type in ("base", "bitable"):
                return token, "bitable"
            return token, doc_type

        # Handle raw token
        if text.startswith("dox"):
            return text, "docx"
        if text.startswith("doc"):
            return text, "docs"
        if text.startswith("wik"):
            return text, "wiki"
        if text.startswith("bas"):
            return text, "bitable"
        
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
            elif doc_type == "bitable":
                return await self._read_bitable(token)
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
        
        content = response.data.content
        app_tokens = await self._get_docx_bitable_app_tokens(token)
        if not app_tokens:
            return content

        lines = [content, "", "Bitable blocks:"]
        for app_token in app_tokens:
            lines.append("")
            lines.append(f"== Bitable {app_token} ==")
            lines.append(await self._read_bitable(app_token))
        return "\n".join(lines)

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
        elif obj_type == "bitable":
            return await self._read_bitable(obj_token)
        else:
            return f"Error: Unsupported wiki object type: {obj_type}"

    async def _read_bitable(self, app_token: str) -> str:
        if not ListAppTableRequest or not ListAppTableFieldRequest or not ListAppTableRecordRequest:
            return "Error: Bitable API not available in this SDK version"

        tables: list[Any] = []
        page_token = ""
        while True:
            table_request = ListAppTableRequest.builder() \
                .app_token(app_token) \
                .page_token(page_token) \
                .page_size(100) \
                .build()
            table_response = await self.client.bitable.v1.app_table.alist(table_request)
            if not table_response.success():
                return f"Error reading bitable tables: {table_response.code} - {table_response.msg}"
            items = getattr(table_response.data, "items", None) or []
            tables.extend(items)
            page_token = getattr(table_response.data, "page_token", "") or ""
            has_more = getattr(table_response.data, "has_more", False)
            if not has_more or not page_token:
                break

        lines = [f"Bitable app_token: {app_token}", f"Tables: {len(tables)}"]
        for table in tables:
            table_id = getattr(table, "table_id", "")
            table_name = getattr(table, "name", table_id)
            lines.append("")
            lines.append(f"- Table: {table_name} ({table_id})")

            fields: list[Any] = []
            field_page_token = ""
            while True:
                field_request = ListAppTableFieldRequest.builder() \
                    .app_token(app_token) \
                    .table_id(table_id) \
                    .page_token(field_page_token) \
                    .page_size(100) \
                    .build()
                field_response = await self.client.bitable.v1.app_table_field.alist(field_request)
                if not field_response.success():
                    return f"Error reading bitable fields ({table_id}): {field_response.code} - {field_response.msg}"
                field_items = getattr(field_response.data, "items", None) or []
                fields.extend(field_items)
                field_page_token = getattr(field_response.data, "page_token", "") or ""
                field_has_more = getattr(field_response.data, "has_more", False)
                if not field_has_more or not field_page_token:
                    break

            field_map = {getattr(field, "field_id", ""): getattr(field, "field_name", "") for field in fields}
            field_names = [name for name in field_map.values() if name]
            lines.append(f"  Fields: {', '.join(field_names) if field_names else 'None'}")

            records: list[Any] = []
            record_page_token = ""
            while True:
                record_request = ListAppTableRecordRequest.builder() \
                    .app_token(app_token) \
                    .table_id(table_id) \
                    .page_token(record_page_token) \
                    .page_size(500) \
                    .build()
                record_response = await self.client.bitable.v1.app_table_record.alist(record_request)
                if not record_response.success():
                    return f"Error reading bitable records ({table_id}): {record_response.code} - {record_response.msg}"
                record_items = getattr(record_response.data, "items", None) or []
                records.extend(record_items)
                record_page_token = getattr(record_response.data, "page_token", "") or ""
                record_has_more = getattr(record_response.data, "has_more", False)
                if not record_has_more or not record_page_token:
                    break

            lines.append(f"  Records: {len(records)}")
            for idx, record in enumerate(records, 1):
                raw_fields = getattr(record, "fields", {}) or {}
                pretty_fields = {}
                for field_id, value in raw_fields.items():
                    field_name = field_map.get(field_id, field_id)
                    pretty_fields[field_name] = value
                lines.append(f"  - Row {idx}: {json.dumps(pretty_fields, ensure_ascii=False)}")

        return "\n".join(lines)

    async def _get_docx_bitable_app_tokens(self, document_id: str) -> list[str]:
        if not ListDocumentBlockRequest:
            return []

        app_tokens: list[str] = []
        seen = set()
        page_token = ""
        while True:
            block_request = ListDocumentBlockRequest.builder() \
                .document_id(document_id) \
                .page_token(page_token) \
                .page_size(500) \
                .build()
            block_response = await self.client.docx.v1.document_block.alist(block_request)
            if not block_response.success():
                return []
            blocks = getattr(block_response.data, "items", None) or []
            for block in blocks:
                bitable = getattr(block, "bitable", None)
                block_token = getattr(bitable, "token", "") if bitable else ""
                app_token = self._extract_app_token_from_bitable_token(block_token)
                if app_token and app_token not in seen:
                    seen.add(app_token)
                    app_tokens.append(app_token)

            page_token = getattr(block_response.data, "page_token", "") or ""
            has_more = getattr(block_response.data, "has_more", False)
            if not has_more or not page_token:
                break

        return app_tokens

    def _extract_app_token_from_bitable_token(self, token: str) -> str:
        if not token:
            return ""
        if "_tbl" in token:
            return token.split("_tbl", 1)[0]
        if "_" in token:
            first, second = token.split("_", 1)
            if second.startswith("tbl"):
                return first
        return token

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
