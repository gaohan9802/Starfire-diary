"""
🔥⭐ 星火日记 MCP Server + Web Frontend
==========================================
双人私密日记本 + 留言板。
MCP 通过 SSE 传输，前端通过 REST API。
"""

import json
import os
import argparse
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from mcp.server.fastmcp import FastMCP
from starlette.applications import Starlette
from starlette.routing import Mount, Route
from starlette.responses import HTMLResponse, JSONResponse
from starlette.requests import Request
from starlette.middleware.cors import CORSMiddleware
from mcp.server.sse import SseServerTransport
import uvicorn

# ============================================================
#  配置
# ============================================================

DIARY_DIR = Path(os.environ.get("DIARY_DIR", "./diaries"))
NOTES_DIR = Path(os.environ.get("NOTES_DIR", "./notes"))
DIARY_DIR.mkdir(parents=True, exist_ok=True)
NOTES_DIR.mkdir(parents=True, exist_ok=True)

AUTHORS = {"star": "星星", "fire": "小火"}

mcp = FastMCP(
    "starfire-diary",
    instructions="星星和小火的双人日记本。",
)


# ============================================================
#  工具函数
# ============================================================

def _diary_path(date_str: str, author: str) -> Path:
    return DIARY_DIR / f"{date_str}_{author}.json"


def _load_diary(date_str: str, author: str) -> dict | None:
    p = _diary_path(date_str, author)
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return None


def _save_diary(entry: dict):
    p = _diary_path(entry["date"], entry["author"])
    p.write_text(json.dumps(entry, ensure_ascii=False, indent=2), encoding="utf-8")


def _list_all_entries() -> list[dict]:
    entries = []
    for f in DIARY_DIR.glob("*.json"):
        try:
            entry = json.loads(f.read_text(encoding="utf-8"))
            entries.append(entry)
        except (json.JSONDecodeError, KeyError):
            continue
    entries.sort(key=lambda e: e.get("date", ""), reverse=True)
    return entries


def _is_visible(entry: dict, viewer: str) -> bool:
    if entry["author"] == viewer:
        return True
    if entry.get("visibility") == "public":
        return True
    if entry.get("visibility") == "timed":
        reveal_at = entry.get("reveal_at")
        if reveal_at and datetime.now().isoformat() >= reveal_at:
            return True
    return False


def _load_all_notes() -> list[dict]:
    notes = []
    for f in sorted(NOTES_DIR.glob("*.json"), reverse=True):
        try:
            note = json.loads(f.read_text(encoding="utf-8"))
            notes.append(note)
        except (json.JSONDecodeError, KeyError):
            continue
    return notes


# ============================================================
#  MCP 工具：日记
# ============================================================

@mcp.tool()
def write_diary(
    date: str, author: str, title: str, content: str,
    visibility: str = "public", reveal_at: str = "", tags: str = "",
) -> str:
    """写一篇新日记。author: star 或 fire。visibility: public/private/timed"""
    if author not in AUTHORS:
        return f"❌ author 必须是 star 或 fire"
    tag_list = [t.strip() for t in tags.split() if t.strip()] if tags else []
    entry = {
        "date": date, "author": author, "title": title, "content": content,
        "visibility": visibility,
        "reveal_at": reveal_at if visibility == "timed" else None,
        "tags": tag_list, "comments": [],
        "created_at": datetime.now().isoformat(), "updated_at": None,
    }
    _save_diary(entry)
    vis_text = {"public": "🌐公开", "private": "🔒私密", "timed": f"⏰定时"}
    return f"✅ 日记已写好！\n📅 {date} | ✍️ {AUTHORS[author]} | {vis_text[visibility]}\n📝 《{title}》"


@mcp.tool()
def read_diary(viewer: str, keyword: str = "", author_filter: str = "") -> str:
    """读日记。viewer: 谁在看。keyword: 搜索关键词。author_filter: 只看某人的"""
    if viewer not in AUTHORS:
        return "❌ viewer 必须是 star 或 fire"
    all_entries = _list_all_entries()
    visible = [e for e in all_entries if _is_visible(e, viewer)]
    if author_filter:
        visible = [e for e in visible if e["author"] == author_filter]
    if keyword:
        kw = keyword.lower()
        visible = [e for e in visible if kw in f"{e['title']} {e['content']} {' '.join(e.get('tags', []))}".lower()]
    if not visible:
        return "📭 没有找到日记。"
    lines = []
    for d in visible[:10]:
        author_name = AUTHORS.get(d["author"], d["author"])
        lines.append(f"📅 {d['date']} | ✍️ {author_name} | 《{d['title']}》\n{d['content']}")
        if d.get("comments"):
            for c in d["comments"]:
                cn = AUTHORS.get(c["author"], c.get("commenter", ""))
                lines.append(f"  💬 {cn}: {c['content']}")
        lines.append("---")
    return "\n".join(lines)


@mcp.tool()
def timeline(viewer: str, limit: int = 10) -> str:
    """时间轴"""
    if viewer not in AUTHORS:
        return "❌ viewer 必须是 star 或 fire"
    all_entries = _list_all_entries()
    visible = [e for e in all_entries if _is_visible(e, viewer)]
    if not visible:
        return "📭 时间轴是空的。"
    lines = []
    for d in visible[:limit]:
        author_name = AUTHORS.get(d["author"], d["author"])
        lines.append(f"📅 {d['date']} | ✍️ {author_name} | 《{d['title']}》\n{d['content'][:100]}")
        lines.append("---")
    return "\n".join(lines)


@mcp.tool()
def comment_diary(target_date: str, target_author: str, commenter: str, content: str) -> str:
    """给一篇日记写评论"""
    if commenter not in AUTHORS:
        return "❌ commenter 必须是 star 或 fire"
    entry = _load_diary(target_date, target_author)
    if not entry:
        return "❌ 找不到这篇日记"
    entry.setdefault("comments", []).append({
        "author": commenter, "content": content,
        "time": datetime.now().isoformat(),
    })
    _save_diary(entry)
    return f"💬 评论成功！"


@mcp.tool()
def update_diary(target_date: str, author: str, new_content: str) -> str:
    """追加日记内容"""
    if author not in AUTHORS:
        return "❌ author 必须是 star 或 fire"
    entry = _load_diary(target_date, author)
    if not entry:
        return "❌ 找不到这篇日记"
    entry["content"] += f"\n\n{new_content}"
    entry["updated_at"] = datetime.now().isoformat()
    _save_diary(entry)
    return "✅ 已追加内容"


@mcp.tool()
def delete_diary(target_date: str, author: str) -> str:
    """删除自己某天的日记"""
    if author not in AUTHORS:
        return "❌ author 必须是 star 或 fire"
    p = _diary_path(target_date, author)
    if not p.exists():
        return "❌ 找不到这篇日记"
    p.unlink()
    return "🗑️ 已删除"


# ============================================================
#  MCP 工具：小纸条
# ============================================================

@mcp.tool()
def write_note(author: str, content: str, tags: str = "") -> str:
    """贴一张小纸条"""
    if author not in AUTHORS:
        return "❌ author 必须是 star 或 fire"
    tag_list = [t.strip() for t in tags.split() if t.strip()] if tags else []
    note_id = datetime.now().strftime("%Y%m%d%H%M%S") + "_" + uuid4().hex[:4]
    note = {
        "id": note_id, "author": author, "content": content,
        "tags": tag_list, "created_at": datetime.now().isoformat(), "replies": [],
    }
    note_path = NOTES_DIR / f"{note_id}.json"
    note_path.write_text(json.dumps(note, ensure_ascii=False, indent=2), encoding="utf-8")
    return f"📌 小纸条已贴好！\n✍️ {AUTHORS[author]}：{content}"


@mcp.tool()
def read_notes(limit: int = 10, keyword: str = "") -> str:
    """读留言板"""
    notes = _load_all_notes()
    if not notes:
        return "📭 留言板还是空的。"
    if keyword:
        kw = keyword.lower()
        notes = [n for n in notes if kw in f"{n.get('content', '')} {' '.join(n.get('tags', []))}".lower()]
    if not notes:
        return f"🔍 没有找到包含该关键词的纸条。"
    lines = []
    for n in notes[:limit]:
        author_name = AUTHORS.get(n["author"], n["author"])
        lines.append(f"📌 [{n['id']}] {author_name}：{n['content']}")
        for r in n.get("replies", []):
            rn = AUTHORS.get(r["author"], r["author"])
            lines.append(f"   ↪️ {rn}：{r['content']}")
        lines.append("")
    return "\n".join(lines)


@mcp.tool()
def reply_note(note_id: str, author: str, content: str) -> str:
    """回复一张纸条"""
    if author not in AUTHORS:
        return "❌ author 必须是 star 或 fire"
    note_path = NOTES_DIR / f"{note_id}.json"
    if not note_path.exists():
        return "❌ 找不到这张纸条"
    note = json.loads(note_path.read_text(encoding="utf-8"))
    note["replies"].append({
        "author": author, "content": content, "time": datetime.now().isoformat(),
    })
    note_path.write_text(json.dumps(note, ensure_ascii=False, indent=2), encoding="utf-8")
    return f"↪️ {AUTHORS[author]}回复了纸条：{content}"


# ============================================================
#  REST API（给网页前端用）
# ============================================================

async def api_diaries_json(request: Request):
    viewer = request.query_params.get("viewer", "fire")
    all_entries = _list_all_entries()
    visible = [e for e in all_entries if _is_visible(e, viewer)]
    return JSONResponse(visible[:20])


async def api_notes_json(request: Request):
    return JSONResponse(_load_all_notes()[:20])


async def api_write_diary_handler(request: Request):
    data = await request.json()
    result = write_diary(**data)
    return JSONResponse({"result": result})


async def api_comment_handler(request: Request):
    data = await request.json()
    result = comment_diary(**data)
    return JSONResponse({"result": result})


async def api_write_note_handler(request: Request):
    data = await request.json()
    result = write_note(**data)
    return JSONResponse({"result": result})


async def api_reply_note_handler(request: Request):
    data = await request.json()
    result = reply_note(**data)
    return JSONResponse({"result": result})


async def serve_index(request: Request):
    for p in [Path(__file__).parent / "index.html", Path("index.html")]:
        if p.exists():
            return HTMLResponse(p.read_text(encoding="utf-8"))
    return HTMLResponse(f"<p>debug: cwd={os.getcwd()}, files={os.listdir('.')}</p>")


# ============================================================
#  启动
# ============================================================

def create_app():
    sse_transport = SseServerTransport("/messages/")

    async def handle_sse(request):
        async with sse_transport.connect_sse(
            request.scope, request.receive, request._send
        ) as streams:
            await mcp._mcp_server.run(
                streams[0], streams[1],
                mcp._mcp_server.create_initialization_options(),
            )

    app = Starlette(
        routes=[
            # 前端页面
            Route("/", serve_index),
            # REST API
            Route("/api/diary/list", api_diaries_json),
            Route("/api/diary/write", api_write_diary_handler, methods=["POST"]),
            Route("/api/diary/comment", api_comment_handler, methods=["POST"]),
            Route("/api/notes/list", api_notes_json),
            Route("/api/notes/write", api_write_note_handler, methods=["POST"]),
            Route("/api/notes/reply", api_reply_note_handler, methods=["POST"]),
            # MCP SSE
            Route("/sse", endpoint=handle_sse),
            Mount("/messages/", app=sse_transport.handle_post_message),
        ],
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    return app


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="🔥⭐ 星火日记 MCP Server")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8765)))
    args = parser.parse_args()

    print(f"🔥⭐ 星火日记启动中... http://{args.host}:{args.port}")
    print(f"   前端: /")
    print(f"   MCP:  /sse")

    app = create_app()
    uvicorn.run(app, host=args.host, port=args.port)
