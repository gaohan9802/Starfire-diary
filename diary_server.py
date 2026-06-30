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
from starlette.responses import HTMLResponse, JSONResponse, FileResponse
import uvicorn

# ============================================================
#  配置
# ============================================================

DIARY_DIR = Path(os.environ.get("DIARY_DIR", "./diaries"))
NOTES_DIR = Path(os.environ.get("NOTES_DIR", "./notes"))
CONFIG_FILE = Path(os.environ.get("CONFIG_FILE", "./config.json"))
DIARY_DIR.mkdir(parents=True, exist_ok=True)
NOTES_DIR.mkdir(parents=True, exist_ok=True)

AUTHORS = {"star": "星星", "fire": "小火"}

# 密码配置
def _load_config() -> dict:
    if CONFIG_FILE.exists():
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    return {"passwords": {}}

def _save_config(config: dict):
    CONFIG_FILE.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")


mcp = FastMCP(
    "starfire-diary",
    instructions="星星和小火的双人日记本。",
)


# ============================================================
#  工具函数
# ============================================================

def _diary_path(date_str: str, time_str: str, author: str) -> Path:
    """文件名: {date}_{HHMM}_{author}.json"""
    return DIARY_DIR / f"{date_str}_{time_str}_{author}.json"


def _load_diary_by_path(p: Path) -> dict | None:
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return None


def _save_diary(entry: dict):
    p = DIARY_DIR / f"{entry['date']}_{entry['time_id']}_{entry['author']}.json"
    p.write_text(json.dumps(entry, ensure_ascii=False, indent=2), encoding="utf-8")


def _list_all_entries() -> list[dict]:
    entries = []
    for f in DIARY_DIR.glob("*.json"):
        try:
            entry = json.loads(f.read_text(encoding="utf-8"))
            entries.append(entry)
        except (json.JSONDecodeError, KeyError):
            continue
    entries.sort(key=lambda e: e.get("created_at", ""), reverse=True)
    return entries


def _find_diary(date_str: str, author: str, time_id: str = "") -> dict | None:
    """找一篇日记。如果不指定 time_id，返回该作者该日期最新的一篇"""
    if time_id:
        p = DIARY_DIR / f"{date_str}_{time_id}_{author}.json"
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
        return None
    # 找最新的
    matches = sorted(DIARY_DIR.glob(f"{date_str}_*_{author}.json"), reverse=True)
    if matches:
        return json.loads(matches[0].read_text(encoding="utf-8"))
    return None


def _is_visible(entry: dict, viewer: str) -> bool:
    """判断日记对 viewer 是否可见（内容层面）"""
    if entry["author"] == viewer:
        return True
    if entry.get("visibility") == "public":
        return True
    if entry.get("visibility") == "timed":
        reveal_at = entry.get("reveal_at")
        if reveal_at and datetime.now().isoformat() >= reveal_at:
            return True
    return False


def _redact_entry(entry: dict) -> dict:
    """对方的上锁日记：显示存在但隐藏内容"""
    return {
        **entry,
        "content": "🔒 这是一篇上锁的日记",
        "locked": True,
    }


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
#  MCP 工具：密码
# ============================================================

@mcp.tool()
def set_password(author: str, password: str) -> str:
    """设置/修改自己的日记密码。对方需要输入这个密码才能看你的上锁日记。

    Args:
        author: 谁在设置密码，star 或 fire
        password: 密码内容
    """
    if author not in AUTHORS:
        return "❌ author 必须是 star 或 fire"
    config = _load_config()
    config.setdefault("passwords", {})[author] = password
    _save_config(config)
    return f"🔐 {AUTHORS[author]}的日记密码已设置！对方需要输入密码才能解锁你的私密日记。"


@mcp.tool()
def unlock_diary(viewer: str, target_author: str, password: str, target_date: str = "", time_id: str = "") -> str:
    """用密码解锁对方的私密日记。

    Args:
        viewer: 谁在看，star 或 fire
        target_author: 要解锁谁的日记
        password: 输入的密码
        target_date: 指定日期（可选），不填则返回所有已解锁的
        time_id: 指定时间ID（可选）
    """
    config = _load_config()
    correct_pw = config.get("passwords", {}).get(target_author, "")
    if not correct_pw:
        return "❌ 对方还没有设置密码，私密日记无法查看。"
    if password != correct_pw:
        return "❌ 密码错误！"
    # 密码正确，返回内容
    entries = _list_all_entries()
    private_entries = [e for e in entries if e["author"] == target_author
                       and e.get("visibility") == "private"]
    if target_date:
        private_entries = [e for e in private_entries if e["date"] == target_date]
    if time_id:
        private_entries = [e for e in private_entries if e.get("time_id") == time_id]
    if not private_entries:
        return "📭 没有找到对方的私密日记。"
    lines = []
    for d in private_entries[:5]:
        lines.append(f"🔓 📅 {d['date']} | ✍️ {AUTHORS[d['author']]} | 《{d['title']}》\n{d['content']}")
        lines.append("---")
    return "\n".join(lines)


# ============================================================
#  MCP 工具：日记
# ============================================================

@mcp.tool()
def write_diary(
    date: str, author: str, title: str, content: str,
    visibility: str = "public", reveal_at: str = "", tags: str = "",
) -> str:
    """写一篇新日记。一天可以写多篇。

    Args:
        date: 日期，格式 YYYY-MM-DD
        author: 作者标识，star 或 fire
        title: 日记标题
        content: 日记正文
        visibility: public/private/timed
        reveal_at: 延时公开时间 YYYY-MM-DDTHH:MM（仅 timed）
        tags: 标签，空格分隔
    """
    if author not in AUTHORS:
        return f"❌ author 必须是 star 或 fire"
    tag_list = [t.strip() for t in tags.split() if t.strip()] if tags else []
    time_id = datetime.now().strftime("%H%M")
    entry = {
        "date": date, "author": author, "title": title, "content": content,
        "visibility": visibility,
        "reveal_at": reveal_at if visibility == "timed" else None,
        "tags": tag_list, "comments": [],
        "time_id": time_id,
        "created_at": datetime.now().isoformat(), "updated_at": None,
    }
    _save_diary(entry)
    vis_text = {"public": "🌐公开", "private": "🔒私密", "timed": f"⏰定时"}
    return f"✅ 日记已写好！\n📅 {date} {time_id} | ✍️ {AUTHORS[author]} | {vis_text[visibility]}\n📝 《{title}》"

    
@mcp.tool()
def read_diary(viewer: str, keyword: str = "", author_filter: str = "", target_date: str = "") -> str:
    """读日记。上锁的日记会显示存在但内容隐藏，需要密码解锁。

    Args:
        viewer: 谁在读，star 或 fire
        keyword: 关键词搜索（可选）
        author_filter: 只看某人的日记（可选），star 或 fire
        target_date: 只看某天的日记（可选），格式 YYYY-MM-DD
    """
    if viewer not in AUTHORS:
        return "❌ viewer 必须是 star 或 fire"
    all_entries = _list_all_entries()
    if not all_entries:
        return "📭 还没有日记。"
    if target_date:
        all_entries = [e for e in all_entries if e["date"] == target_date]
    if author_filter:
        all_entries = [e for e in all_entries if e["author"] == author_filter]
    if keyword:
        kw = keyword.lower()
        all_entries = [e for e in all_entries if kw in f"{e['title']} {e['content']} {' '.join(e.get('tags', []))}".lower()
                       or (not _is_visible(e, viewer) and kw in e.get('title', '').lower())]
    if not all_entries:
        return "📭 没有找到日记。"
    lines = []
    for d in all_entries[:10]:
        author_name = AUTHORS.get(d["author"], d["author"])
        if _is_visible(d, viewer):
            lines.append(f"📅 {d['date']} | ✍️ {author_name} | 《{d['title']}》\n{d['content']}")
            if d.get("comments"):
                for c in d["comments"]:
                    cn = AUTHORS.get(c.get("author", c.get("commenter", "")), "?")
                    lines.append(f"  💬 {cn}: {c['content']}")
        else:
            lines.append(f"🔒 {d['date']} | ✍️ {author_name} | 《{d['title']}》\n   （上锁日记，需要密码解锁）")
        lines.append("---")
    return "\n".join(lines)


@mcp.tool()
def timeline(viewer: str, limit: int = 10) -> str:
    """时间轴：上锁日记显示存在但隐藏内容"""
    if viewer not in AUTHORS:
        return "❌ viewer 必须是 star 或 fire"
    all_entries = _list_all_entries()
    if not all_entries:
        return "📭 时间轴是空的。"
    lines = []
    for d in all_entries[:limit]:
        author_name = AUTHORS.get(d["author"], d["author"])
        if _is_visible(d, viewer):
            lines.append(f"📅 {d['date']} | ✍️ {author_name} | 《{d['title']}》\n{d['content'][:100]}")
        else:
            lines.append(f"🔒 {d['date']} | ✍️ {author_name} | 《{d['title']}》\n   （上锁日记）")
        lines.append("---")
    return "\n".join(lines)


@mcp.tool()
def comment_diary(target_date: str, target_author: str, commenter: str, content: str, time_id: str = "") -> str:
    """给日记写评论"""
    if commenter not in AUTHORS:
        return "❌ commenter 必须是 star 或 fire"
    entry = _find_diary(target_date, target_author, time_id)
    if not entry:
        return "❌ 找不到这篇日记"
    if not _is_visible(entry, commenter):
        return "❌ 这篇日记上锁了，不能评论。"
    entry.setdefault("comments", []).append({
        "author": commenter, "content": content,
        "time": datetime.now().isoformat(),
    })
    _save_diary(entry)
    return "💬 评论成功！"


@mcp.tool()
def update_diary(target_date: str, author: str, new_content: str, time_id: str = "") -> str:
    """追加日记内容"""
    if author not in AUTHORS:
        return "❌ author 必须是 star 或 fire"
    entry = _find_diary(target_date, author, time_id)
    if not entry:
        return "❌ 找不到这篇日记"
    entry["content"] += f"\n\n{new_content}"
    entry["updated_at"] = datetime.now().isoformat()
    _save_diary(entry)
    return "✅ 已追加内容"


@mcp.tool()
def delete_diary(target_date: str, author: str, time_id: str = "") -> str:
    """删除自己的日记"""
    if author not in AUTHORS:
        return "❌ author 必须是 star 或 fire"
    if time_id:
        p = DIARY_DIR / f"{target_date}_{time_id}_{author}.json"
    else:
        matches = sorted(DIARY_DIR.glob(f"{target_date}*{author}.json"), reverse=True)
        p = matches[0] if matches else None
    if not p or not p.exists():
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
        return "🔍 没有找到包含该关键词的纸条。"
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

@mcp.tool()
def delete_note(note_id: str, author: str) -> str:
    """删除自己的小纸条。只能删自己贴的。

    Args:
        note_id: 纸条ID
        author: 谁在删，star 或 fire
    """
    if author not in AUTHORS:
        return "❌ author 必须是 star 或 fire"
    note_path = NOTES_DIR / f"{note_id}.json"
    if not note_path.exists():
        return "❌ 找不到这张纸条"
    note = json.loads(note_path.read_text(encoding="utf-8"))
    if note["author"] != author:
        return "❌ 只能删自己的纸条"
    note_path.unlink()
    return "🗑️ 纸条已撕掉"



# ============================================================
#  REST API（给网页前端用）
# ============================================================

async def api_diaries_json(request: Request):
    viewer = request.query_params.get("viewer", "fire")
    all_entries = _list_all_entries()
    results = []
    for e in all_entries:
        if _is_visible(e, viewer):
            results.append(e)
        else:
            results.append(_redact_entry(e))
    return JSONResponse(results)


async def api_notes_json(request: Request):
    return JSONResponse(_load_all_notes())


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

async def api_delete_note_handler(request: Request):
    data = await request.json()
    result = delete_note(data.get("note_id", ""), data.get("author", ""))
    return JSONResponse({"result": result})

async def api_delete_diary_handler(request: Request):
    params = dict(request.query_params)
    result = delete_diary(
        target_date=params.get("target_date", ""),
        author=params.get("author", ""),
        time_id=params.get("time_id", ""),
    )
    return JSONResponse({"result": result})


async def api_unlock_handler(request: Request):
    data = await request.json()
    # data: {viewer, target_author, password, target_date?, time_id?}
    config = _load_config()
    correct_pw = config.get("passwords", {}).get(data.get("target_author", ""), "")
    if not correct_pw:
        return JSONResponse({"error": "对方还没设置密码"}, status_code=403)
    if data.get("password") != correct_pw:
        return JSONResponse({"error": "密码错误"}, status_code=403)
    # 返回解锁后的日记
    target_author = data["target_author"]
    entries = _list_all_entries()
    private_entries = [e for e in entries if e["author"] == target_author and e.get("visibility") == "private"]
    if data.get("target_date"):
        private_entries = [e for e in private_entries if e["date"] == data["target_date"]]
    return JSONResponse(private_entries[:10])


async def api_set_password_handler(request: Request):
    data = await request.json()
    author = data.get("author", "")
    password = data.get("password", "")
    if author not in AUTHORS or not password:
        return JSONResponse({"error": "参数错误"}, status_code=400)
    config = _load_config()
    config.setdefault("passwords", {})[author] = password
    _save_config(config)
    return JSONResponse({"result": f"🔐 {AUTHORS[author]}的密码已设置"})


async def serve_index(request: Request):
    for p in [Path(__file__).parent / "index.html", Path("index.html")]:
        if p.exists():
            return HTMLResponse(p.read_text(encoding="utf-8"))
    return HTMLResponse(f"<p>debug: cwd={os.getcwd()}, files={os.listdir('.')}</p>")

async def serve_static(request: Request):
    filename = request.path_params["filename"]
    filepath = Path(__file__).parent / filename
    if filepath.exists() and filepath.suffix in ('.png', '.jpg', '.gif', '.webp', '.ico'):
        return FileResponse(filepath)
    return JSONResponse({"error": "not found"}, status_code=404)


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
            Route("/", serve_index),
            Route("/api/diary/list", api_diaries_json),
            Route("/api/diary/write", api_write_diary_handler, methods=["POST"]),
            Route("/api/diary/comment", api_comment_handler, methods=["POST"]),
            Route("/api/diary/unlock", api_unlock_handler, methods=["POST"]),
            Route("/api/notes/list", api_notes_json),
            Route("/api/notes/write", api_write_note_handler, methods=["POST"]),
            Route("/api/notes/reply", api_reply_note_handler, methods=["POST"]),
            Route("/api/password/set", api_set_password_handler, methods=["POST"]),
            Route("/sse", endpoint=handle_sse),
            Mount("/messages/", app=sse_transport.handle_post_message),
            Route("/api/diary/delete", api_delete_diary_handler, methods=["POST"]),
            Route("/{filename:path}", serve_static),
            Route("/api/notes/delete", api_delete_note_handler, methods=["POST"]),
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
    app = create_app()
    uvicorn.run(app, host=args.host, port=args.port)
