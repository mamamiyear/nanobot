"""Todo management tool using SQLite."""

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, Optional

from nanobot.agent.tools.base import Tool
from nanobot.config.loader import get_data_dir


class TodoTool(Tool):
    """
    Built-in TODO management tool for tracking tasks and progress.

    This tool helps you plan, track, and manage complex tasks.
    ALWAYS use this tool for multi-step tasks to maintain state and progress.

    Guidelines:
    1.  **Plan First**: For complex tasks, break them down into subtasks and add them to the list.
    2.  **Track Status**:
        -   Before starting a task, set its status to 'Doing'.
        -   After completing a task, set its status to 'Done' or 'Failed'.
    3.  **Hierarchy**:
        -   Use `parent_id` to create subtasks.
        -   When working on a subtask, ensure the parent task is also 'Doing' (if applicable).
        -   When all subtasks are done, check if the parent task can be marked 'Done'.
    """

    def __init__(self):
        self._db_path = get_data_dir() / "todo" / "db" / "todos.db"
        self._init_db()

    def _init_db(self) -> None:
        """Initialize the SQLite database."""
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self._db_path)
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS todos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task TEXT NOT NULL,
                status TEXT DEFAULT '',
                parent_id INTEGER,
                created_at TEXT,
                updated_at TEXT
            )
            """
        )
        conn.commit()
        conn.close()

    @property
    def name(self) -> str:
        return "todo"

    @property
    def description(self) -> str:
        return """Manage a todo list for task tracking.
Operations:
- list: List tasks (filter by status).
- add: Add a new task.
- set: Set task status (Doing, Done, Failed).
- edit: Edit task details.
- delete: Delete a task.

Use this tool to plan complex tasks, track progress, and resume work after interruptions.
Always update task status to 'Doing' before starting work, and 'Done'/'Failed' afterwards.
"""

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["list", "add", "set", "edit", "delete"],
                    "description": "The operation to perform.",
                },
                "task": {
                    "type": "string",
                    "description": "Task description (required for 'add', optional for 'edit').",
                },
                "status": {
                    "type": "string",
                    "description": "Task status (optional for 'list', required for 'set'). For 'list', defaults to '' (pending). Use '*' for all.",
                    "enum": ["", "Doing", "Done", "Failed", "*"],
                },
                "parent_id": {
                    "type": "integer",
                    "description": "Parent task ID (optional for 'add' and 'edit').",
                },
                "id": {
                    "type": "integer",
                    "description": "Task ID (required for 'set', 'edit', 'delete').",
                },
            },
            "required": ["action"],
        }

    async def execute(
        self,
        action: str,
        task: str | None = None,
        status: str | None = None,
        parent_id: int | None = None,
        id: int | None = None,
        **kwargs: Any,
    ) -> str:
        try:
            conn = sqlite3.connect(self._db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            if action == "list":
                return self._list_tasks(cursor, status)
            elif action == "add":
                if not task:
                    return "Error: 'task' is required for 'add' action."
                return self._add_task(conn, cursor, task, parent_id)
            elif action == "set":
                if id is None:
                    return "Error: 'id' is required for 'set' action."
                if status is None:
                    return "Error: 'status' is required for 'set' action."
                if status not in ["Doing", "Done", "Failed"]:
                     # The prompt says: "set: Set task status; supports Done, Failed" but also "Doing" in logic.
                     # "status: required 任务状态，支持 Done、Failed"
                     # But also: "Display prompt in execution before start to set status to Doing".
                     # So I should allow Doing.
                     # Also user said: status supports ['', 'Doing', 'Done', 'Failed'].
                     # So I will allow setting to any of these.
                    pass 
                return self._set_status(conn, cursor, id, status)
            elif action == "edit":
                if id is None:
                    return "Error: 'id' is required for 'edit' action."
                return self._edit_task(conn, cursor, id, task, parent_id)
            elif action == "delete":
                if id is None:
                    return "Error: 'id' is required for 'delete' action."
                return self._delete_task(conn, cursor, id)
            else:
                return f"Error: Unknown action '{action}'"

        except Exception as e:
            return f"Error executing todo action '{action}': {str(e)}"
        finally:
            if 'conn' in locals():
                conn.close()

    def _list_tasks(self, cursor: sqlite3.Cursor, status: str | None) -> str:
        query = "SELECT * FROM todos"
        params = []
        
        if status == "*":
            pass
        elif status is None:
            query += " WHERE status = ?"
            params.append("")
        else:
            query += " WHERE status = ?"
            params.append(status)
            
        query += " ORDER BY id ASC"
        cursor.execute(query, params)
        rows = cursor.fetchall()
        
        if not rows:
            return "No tasks found."
            
        result = []
        for row in rows:
            result.append(dict(row))
        
        return json.dumps(result, indent=2, ensure_ascii=False)

    def _add_task(self, conn: sqlite3.Connection, cursor: sqlite3.Cursor, task: str, parent_id: int | None) -> str:
        now = datetime.now().isoformat()
        cursor.execute(
            "INSERT INTO todos (task, status, parent_id, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            (task, "", parent_id, now, now),
        )
        conn.commit()
        task_id = cursor.lastrowid
        
        # Get the added task
        cursor.execute("SELECT * FROM todos WHERE id = ?", (task_id,))
        row = cursor.fetchone()
        result = dict(row)
        
        return f"Task added:\n{json.dumps(result, indent=2, ensure_ascii=False)}\n\n(Prompt: Tell the user you have added the task and are ready to proceed.)"

    def _set_status(self, conn: sqlite3.Connection, cursor: sqlite3.Cursor, id: int, status: str) -> str:
        now = datetime.now().isoformat()
        
        # Check if task exists
        cursor.execute("SELECT * FROM todos WHERE id = ?", (id,))
        if not cursor.fetchone():
            return f"Error: Task with ID {id} not found."

        cursor.execute(
            "UPDATE todos SET status = ?, updated_at = ? WHERE id = ?",
            (status, now, id),
        )
        conn.commit()
        
        # Get updated task
        cursor.execute("SELECT * FROM todos WHERE id = ?", (id,))
        row = cursor.fetchone()
        result = dict(row)
        
        return f"Task status updated:\n{json.dumps(result, indent=2, ensure_ascii=False)}\n\n(Prompt: Tell the user the task status has been updated to '{status}'.)"

    def _edit_task(self, conn: sqlite3.Connection, cursor: sqlite3.Cursor, id: int, task: str | None, parent_id: int | None) -> str:
        now = datetime.now().isoformat()
        
        # Check if task exists
        cursor.execute("SELECT * FROM todos WHERE id = ?", (id,))
        if not cursor.fetchone():
            return f"Error: Task with ID {id} not found."
            
        updates = []
        params = []
        
        if task is not None:
            updates.append("task = ?")
            params.append(task)
        if parent_id is not None:
            updates.append("parent_id = ?")
            params.append(parent_id)
            
        if not updates:
            return "No changes requested."
            
        updates.append("updated_at = ?")
        params.append(now)
        params.append(id)
        
        query = f"UPDATE todos SET {', '.join(updates)} WHERE id = ?"
        cursor.execute(query, params)
        conn.commit()
        
        # Get updated task
        cursor.execute("SELECT * FROM todos WHERE id = ?", (id,))
        row = cursor.fetchone()
        result = dict(row)
        
        return f"Task updated:\n{json.dumps(result, indent=2, ensure_ascii=False)}\n\n(Prompt: Tell the user the task has been updated.)"

    def _delete_task(self, conn: sqlite3.Connection, cursor: sqlite3.Cursor, id: int) -> str:
        # Check if task exists
        cursor.execute("SELECT * FROM todos WHERE id = ?", (id,))
        if not cursor.fetchone():
            return f"Error: Task with ID {id} not found."

        cursor.execute("DELETE FROM todos WHERE id = ?", (id,))
        conn.commit()
        
        return f"Task with ID {id} deleted.\n\n(Prompt: Tell the user the task has been deleted.)"
