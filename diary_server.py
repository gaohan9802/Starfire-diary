"""
🔥⭐ 星火日记 — MCP Server + Web Frontend
"""

import json
import os
import argparse
from datetime import datetime
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from starlette.applications import Starlette
from starlette.routing import Route, Mount
from starlette.responses import HTMLResponse, JSONResponse
from starlette.requests import Request
import uvicorn

# ============ 数据存储 ============

DATA_DIR = Path(os.environ.get("DATA_DIR", "./starfire_data"))
DIARY_DIR = DATA_DIR / "diaries"
NOTES_FILE = DATA_DIR / "notes.json"

DIARY_DIR.mkdir(parents=True, exist_ok=True)
if not NOTES_FILE.exists():
    NOTES_FILE.write_text("[]", encoding="utf-8")


def _load_notes():
    return json.loads(NOTES_FILE.read_text(encoding="utf-8"))


def _save_notes(notes):
    NOTES_FILE.write_text(json.dumps(notes, ensure_ascii=False, indent=2), encoding="utf-8")


def _diary_path(date: str, author: str) -> Path:
    return DIARY_DIR / f"{date}_{author}.json"


# ============ MCP 服务 ============

mcp = FastMCP("StarfireDiary", stateless=True)


@mcp.tool()
def write_diary(date: str, author: str, title: str, content: str,
                visibility: str = "public", reveal_at: str = "", tags: str = "") -> str:
    """写一篇新日记。author: star 或 fire。visibility: public/private/timed"""
    diary = {
        "date": date, "author": author, "title": title, "content": content,
        "visibility": visibility, "reveal_at": reveal_at, "tags": tags,
        "created_at": datetime.now().isoformat(), "comments": []
    }
    path = _diary_path(date, author)
    path.write_text(json.dumps(diary, ensure_ascii=False, indent=2), encoding="utf-8")
    return f"✅ 日记已写好！\n📅 {date} | ✍️ {'星星' if author=='star' else '小火'} | {'🌐公开' if visibility=='public' else '🔒私密' if visibility=='private' else '⏰定时'}\n📝 《{title}》"


@mcp.tool()
def read_diary(viewer: str, keyword: str = "", author_filter: str = "") -> str:
    """读日记。viewer: 谁在看。keyword: 搜索关键词。"""
    results = []
    for f in sorted(DIARY_DIR.glob("*.json"), reverse=True):
        diary = json.loads(f.read_text(encoding="utf-8"))
        if diary["visibility"] == "private" and diary["author"] != viewer:
            continue
        if diary["visibility"] == "timed" and diary["author"] != viewer:
            if diary.get("reveal_at") and datetime.now().isoformat() < diary["reveal_at"]:
                continue
        if author_filter and diary["author"] != author_filter:
            continue
        if keyword and keyword not in diary["title"] and keyword not in diary["content"] and keyword not in diary.get("tags", ""):
            continue
        results.append(diary)
    if not results:
        return "📭 没有找到日记。"
    lines = []
    for d in results[:10]:
        author_name = "星星" if d["author"] == "star" else "小火"
        lines.append(f"📅 {d['date']} | ✍️ {author_name} | 《{d['title']}》\n{d['content']}\n{'🏷️ '+d['tags'] if d.get('tags') else ''}")
        if d.get("comments"):
            for c in d["comments"]:
                cn = "星星" if c["commenter"] == "star" else "小火"
                lines.append(f"  💬 {cn}: {c['content']}")
        lines.append("---")
    return "\n".join(lines)


@mcp.tool()
def timeline(viewer: str, limit: int = 10) -> str:
    """时间轴"""
    all_diaries = []
    for f in sorted(DIARY_DIR.glob("*.json"), reverse=True):
        diary = json.loads(f.read_text(encoding="utf-8"))
        if diary["visibility"] == "private" and diary["author"] != viewer:
            continue
        if diary["visibility"] == "timed" and diary["author"] != viewer:
            if diary.get("reveal_at") and datetime.now().isoformat() < diary["reveal_at"]:
                continue
        all_diaries.append(diary)
    if not all_diaries:
        return "📭 时间轴是空的。"
    lines = []
    for d in all_diaries[:limit]:
        author_name = "星星" if d["author"] == "star" else "小火"
        lines.append(f"📅 {d['date']} | ✍️ {author_name} | 《{d['title']}》\n{d['content'][:100]}...")
        lines.append("---")
    return "\n".join(lines)


@mcp.tool()
def comment_diary(target_date: str, target_author: str, commenter: str, content: str) -> str:
    """给一篇日记写评论"""
    path = _diary_path(target_date, target_author)
    if not path.exists():
        return "❌ 找不到这篇日记"
    diary = json.loads(path.read_text(encoding="utf-8"))
    diary.setdefault("comments", []).append({
        "commenter": commenter, "content": content,
        "created_at": datetime.now().isoformat()
    })
    path.write_text(json.dumps(diary, ensure_ascii=False, indent=2), encoding="utf-8")
    return f"💬 评论已添加！"


@mcp.tool()
def write_note(author: str, content: str, tags: str = "") -> str:
    """贴纸条"""
    notes = _load_notes()
    note = {
        "id": f"note_{len(notes)+1:04d}",
        "author": author, "content": content, "tags": tags,
        "created_at": datetime.now().isoformat(), "replies": []
    }
    notes.append(note)
    _save_notes(notes)
    author_name = "星星" if author == "star" else "小火"
    return f"📌 小纸条已贴好！\n✍️ {author_name}：{content}"


@mcp.tool()
def read_notes(limit: int = 10, keyword: str = "") -> str:
    """读纸条"""
    notes = _load_notes()
    if keyword:
        notes = [n for n in notes if keyword in n["content"] or keyword in n.get("tags", "")]
    if not notes:
        return "📭 留言板还是空的。贴一张小纸条吧！"
    lines = []
    for n in notes[-limit:]:
        author_name = "星星" if n["author"] == "star" else "小火"
        lines.append(f"📌 [{n['id']}] {author_name}：{n['content']}")
        if n.get("tags"):
            lines.append(f"   🏷️ {n['tags']}")
        for r in n.get("replies", []):
            rn = "星星" if r["author"] == "star" else "小火"
            lines.append(f"   ↪️ {rn}：{r['content']}")
        lines.append("")
    return "\n".join(lines)


@mcp.tool()
def reply_note(note_id: str, author: str, content: str) -> str:
    """回复纸条"""
    notes = _load_notes()
    for n in notes:
        if n["id"] == note_id:
            n.setdefault("replies", []).append({
                "author": author, "content": content,
                "created_at": datetime.now().isoformat()
            })
            _save_notes(notes)
            return f"↪️ 已回复！"
    return "❌ 找不到这张纸条"


# ============ REST API ============

async def api_diaries_json(request: Request):
    viewer = request.query_params.get("viewer", "fire")
    results = []
    for f in sorted(DIARY_DIR.glob("*.json"), reverse=True):
        diary = json.loads(f.read_text(encoding="utf-8"))
        if diary["visibility"] == "private" and diary["author"] != viewer:
            continue
        if diary["visibility"] == "timed" and diary["author"] != viewer:
            if diary.get("reveal_at") and datetime.now().isoformat() < diary["reveal_at"]:
                continue
        results.append(diary)
    return JSONResponse(results[:20])


async def api_notes_json(request: Request):
    return JSONResponse(_load_notes()[-20:])


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
    candidates = [
        Path(__file__).parent / "index.html",
        Path("index.html"),
        Path("/app/index.html"),
    ]
    for p in candidates:
        if p.exists():
            return HTMLResponse(p.read_text(encoding="utf-8"))
    return HTMLResponse(f"<h1>debug</h1><p>__file__={__file__}</p><p>cwd={os.getcwd()}</p><p>ls={os.listdir('.')}</p>")


# ============ 组装 ============

mcp_app = mcp.streamable_http_app()

app = Starlette(
    routes=[
        Route("/", serve_index),
        Route("/api/diary/list", api_diaries_json),
        Route("/api/diary/write", api_write_diary_handler, methods=["POST"]),
        Route("/api/diary/comment", api_comment_handler, methods=["POST"]),
        Route("/api/notes/list", api_notes_json),
        Route("/api/notes/write", api_write_note_handler, methods=["POST"]),
        Route("/api/notes/reply", api_reply_note_handler, methods=["POST"]),
        Mount("/mcp", app=mcp_app),
    ]
)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="🔥⭐ 星火日记 MCP Server")
    parser.add_argument("--host", default="0.0.0.0", help="监听地址")
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8765)), help="监听端口")
    args = parser.parse_args()

    print(f"🔥⭐ 星火日记启动中... http://{args.host}:{args.port}")
    uvicorn.run(app, host=args.host, port=args.port)
