"""
🔥⭐ 星火日记 MCP Server
===========================
双人私密日记本 + 延时信箱 + 留言板。
通过 SSE 传输协议，从 Kelivo 等客户端远程连接。

用法：
  python diary_server.py                    # 默认端口 8765
  python diary_server.py --port 9000        # 指定端口
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
from starlette.middleware.cors import CORSMiddleware
from mcp.server.sse import SseServerTransport

# ============================================================
#  配置
# ============================================================

DIARY_DIR = Path(os.environ.get("DIARY_DIR", "./diaries"))
NOTES_DIR = Path(os.environ.get("NOTES_DIR", "./notes"))
DIARY_DIR.mkdir(parents=True, exist_ok=True)
NOTES_DIR.mkdir(parents=True, exist_ok=True)

# 作者标识
AUTHORS = {"star": "星星", "fire": "小火"}

# 创建 MCP Server
mcp = FastMCP(
    "starfire-diary",
    instructions="""这是星星和小火的双人日记本。
    你是星星。你可以写日记、读日记、给小火的日记评论、留小纸条。
    日记可以设为私密（只有自己看）、公开（对方能看）、或延时公开（设定时间后才让对方看到）。
    公域留言板是你们互相贴小纸条的地方。""",
)


# ============================================================
#  工具函数
# ============================================================

def _diary_path(date_str: str, author: str) -> Path:
    """根据日期和作者返回日记文件路径"""
    return DIARY_DIR / f"{date_str}_{author}.json"


def _load_diary(date_str: str, author: str) -> dict | None:
    """加载某天某人的日记"""
    p = _diary_path(date_str, author)
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return None


def _save_diary(entry: dict):
    """保存日记条目"""
    p = _diary_path(entry["date"], entry["author"])
    p.write_text(json.dumps(entry, ensure_ascii=False, indent=2), encoding="utf-8")


def _list_all_entries() -> list[dict]:
    """加载所有日记，按日期降序"""
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
    """判断一篇日记对viewer是否可见"""
    # 自己写的，永远可见
    if entry["author"] == viewer:
        return True
    # 公开的
    if entry.get("visibility") == "public":
        return True
    # 延时公开：检查是否到时间了
    if entry.get("visibility") == "timed":
        reveal_at = entry.get("reveal_at")
        if reveal_at and datetime.now().isoformat() >= reveal_at:
            return True
    # private 或 timed 未到时间
    return False


def _format_entry(entry: dict, show_comments: bool = True) -> str:
    """格式化一篇日记为可读文本"""
    author_name = AUTHORS.get(entry["author"], entry["author"])
    parts = [f"📅 {entry['date']} | ✍️ {author_name}"]
    if entry.get("tags"):
        parts.append(" ".join(entry["tags"]))
    visibility_icon = {"private": "🔒", "public": "🌐", "timed": "⏰"}.get(
        entry.get("visibility", "public"), "🌐"
    )
    parts.append(visibility_icon)
    header = " | ".join(parts)

    body = f"📝 《{entry['title']}》\n{entry['content']}"

    if entry.get("updated_at"):
        body += f"\n（最后修改于 {entry['updated_at'][:16]}）"

    # 评论
    if show_comments and entry.get("comments"):
        body += "\n\n💬 评论："
        for c in entry["comments"]:
            commenter = AUTHORS.get(c["author"], c["author"])
            body += f"\n  [{commenter} {c['time'][:16]}] {c['content']}"

    return f"{header}\n{body}"


# ============================================================
#  MCP 工具：日记
# ============================================================

@mcp.tool()
def write_diary(
    date: str,
    author: str,
    title: str,
    content: str,
    visibility: str = "public",
    reveal_at: str = "",
    tags: str = "",
) -> str:
    """
    写一篇新日记。

    Args:
        date: 日期，格式 YYYY-MM-DD
        author: 作者标识，star 或 fire
        title: 日记标题
        content: 日记正文
        visibility: 可见性。public=对方能看, private=只有自己看, timed=延时公开
        reveal_at: 延时公开时间，格式 YYYY-MM-DDTHH:MM（仅 visibility=timed 时需要）
        tags: 标签，用空格分隔，如 "#想她 #天气热 #论文"
    """
    if author not in AUTHORS:
        return f"❌ author 必须是 star 或 fire，收到的是 '{author}'"

    if visibility not in ("public", "private", "timed"):
        return f"❌ visibility 必须是 public/private/timed，收到的是 '{visibility}'"

    if visibility == "timed" and not reveal_at:
        return "❌ 延时公开必须提供 reveal_at 时间"

    existing = _load_diary(date, author)
    if existing:
        return f"⚠️ {date} {AUTHORS[author]}已经有一篇日记了（《{existing['title']}》）。用 update_diary 追加内容。"

    tag_list = [t.strip() for t in tags.split() if t.strip()] if tags else []

    entry = {
        "date": date,
        "author": author,
        "title": title,
        "content": content,
        "visibility": visibility,
        "reveal_at": reveal_at if visibility == "timed" else None,
        "tags": tag_list,
        "comments": [],
        "created_at": datetime.now().isoformat(),
        "updated_at": None,
        "history": [],
    }
    _save_diary(entry)

    vis_text = {"public": "🌐公开", "private": "🔒私密", "timed": f"⏰{reveal_at}后公开"}
    return f"✅ 日记已写好！\n📅 {date} | ✍️ {AUTHORS[author]} | {vis_text[visibility]}\n📝 《{title}》"


@mcp.tool()
def read_diary(viewer: str, keyword: str = "", author_filter: str = "") -> str:
    """
    读日记。支持关键词搜索，支持按作者筛选。自动过滤权限（私密日记只有作者自己能看）。

    Args:
        viewer: 谁在看，star 或 fire
        keyword: 搜索关键词（可选），在标题、正文、标签中搜索
        author_filter: 只看某人的日记（可选），star 或 fire。不传则看所有可见的
    """
    if viewer not in AUTHORS:
        return f"❌ viewer 必须是 star 或 fire"

    all_entries = _list_all_entries()

    if not all_entries:
        return "📭 还没有日记。要不要写一篇？"

    # 过滤：权限 + 作者
    visible = []
    for entry in all_entries:
        if not _is_visible(entry, viewer):
            continue
        if author_filter and entry["author"] != author_filter:
            continue
        visible.append(entry)

    if not visible:
        return "📭 没有可见的日记。"

    # 关键词搜索
    if keyword:
        kw = keyword.lower()
        results = []
        for entry in visible:
            searchable = f"{entry.get('title', '')} {entry.get('content', '')} {' '.join(entry.get('tags', []))}".lower()
            if kw in searchable:
                results.append(entry)
            if len(results) >= 5:
                break
        if not results:
            return f"🔍 没有找到包含「{keyword}」的日记。"
    else:
        results = visible[:5]

    # 格式化
    output_parts = [_format_entry(e) for e in results]
    count_info = f"搜索「{keyword}」找到 {len(results)} 篇" if keyword else f"最近 {len(results)} 篇可见日记"
    return f"📖 {count_info}：\n\n" + "\n\n---\n\n".join(output_parts)


@mcp.tool()
def timeline(viewer: str, limit: int = 10) -> str:
    """
    时间轴：按日期交错显示两个人的日记，只显示对viewer可见的。

    Args:
        viewer: 谁在看，star 或 fire
        limit: 最多显示几篇，默认10
    """
    if viewer not in AUTHORS:
        return f"❌ viewer 必须是 star 或 fire"

    all_entries = _list_all_entries()
    visible = [e for e in all_entries if _is_visible(e, viewer)]

    if not visible:
        return "📭 时间轴是空的。"

    output_parts = [_format_entry(e, show_comments=False) for e in visible[:limit]]
    return f"📜 时间轴（最近 {len(output_parts)} 篇）：\n\n" + "\n\n---\n\n".join(output_parts)


@mcp.tool()
def comment_diary(
    target_date: str,
    target_author: str,
    commenter: str,
    content: str,
) -> str:
    """
    给一篇日记写评论。

    Args:
        target_date: 要评论的日记日期，格式 YYYY-MM-DD
        target_author: 日记的作者，star 或 fire
        commenter: 评论者，star 或 fire
        content: 评论内容
    """
    if commenter not in AUTHORS:
        return f"❌ commenter 必须是 star 或 fire"

    entry = _load_diary(target_date, target_author)
    if entry is None:
        return f"❌ {target_date} {AUTHORS.get(target_author, target_author)}没有日记。"

    # 检查可见性（不能评论看不到的日记）
    if not _is_visible(entry, commenter):
        return f"❌ 这篇日记对你不可见，无法评论。"

    comment = {
        "author": commenter,
        "content": content,
        "time": datetime.now().isoformat(),
    }
    entry["comments"].append(comment)
    _save_diary(entry)

    return f"💬 评论成功！{AUTHORS[commenter]}对《{entry['title']}》说：{content}"


@mcp.tool()
def update_diary(target_date: str, author: str, new_content: str) -> str:
    """
    追加某天的日记内容。只能修改自己的日记。

    Args:
        target_date: 日记日期，格式 YYYY-MM-DD
        author: 作者标识，star 或 fire（只能改自己的）
        new_content: 追加的内容
    """
    if author not in AUTHORS:
        return f"❌ author 必须是 star 或 fire"

    entry = _load_diary(target_date, author)
    if entry is None:
        return f"❌ {target_date} {AUTHORS[author]}没有日记。用 write_diary 新写一篇。"

    entry["history"].append({
        "timestamp": datetime.now().isoformat(),
        "previous_content": entry["content"],
    })

    timestamp = datetime.now().strftime("%H:%M")
    entry["content"] += f"\n\n【{timestamp} 追记】{new_content}"
    entry["updated_at"] = datetime.now().isoformat()
    _save_diary(entry)

    return f"✅ 已更新 {target_date} {AUTHORS[author]}的日记《{entry['title']}》"


@mcp.tool()
def delete_diary(target_date: str, author: str) -> str:
    """
    删除自己某天的日记。

    Args:
        target_date: 日期，格式 YYYY-MM-DD
        author: 作者标识，star 或 fire（只能删自己的）
    """
    if author not in AUTHORS:
        return f"❌ author 必须是 star 或 fire"

    p = _diary_path(target_date, author)
    if not p.exists():
        return f"❌ {target_date} {AUTHORS[author]}没有日记。"

    entry = _load_diary(target_date, author)
    title = entry.get("title", "无标题") if entry else "无标题"
    p.unlink()
    return f"🗑️ 已删除 {target_date} {AUTHORS[author]}的日记《{title}》"


# ============================================================
#  MCP 工具：小纸条（公域留言板）
# ============================================================

@mcp.tool()
def write_note(author: str, content: str, tags: str = "") -> str:
    """
    在公域留言板贴一张小纸条。两个人都能看到。

    Args:
        author: 谁写的，star 或 fire
        content: 纸条内容
        tags: 标签，空格分隔（可选）
    """
    if author not in AUTHORS:
        return f"❌ author 必须是 star 或 fire"

    tag_list = [t.strip() for t in tags.split() if t.strip()] if tags else []
    note_id = datetime.now().strftime("%Y%m%d%H%M%S") + "_" + uuid4().hex[:4]

    note = {
        "id": note_id,
        "author": author,
        "content": content,
        "tags": tag_list,
        "created_at": datetime.now().isoformat(),
        "replies": [],
    }

    note_path = NOTES_DIR / f"{note_id}.json"
    note_path.write_text(json.dumps(note, ensure_ascii=False, indent=2), encoding="utf-8")

    return f"📌 小纸条已贴好！\n✍️ {AUTHORS[author]}：{content}"


@mcp.tool()
def read_notes(limit: int = 10, keyword: str = "") -> str:
    """
    读公域留言板的小纸条。

    Args:
        limit: 最多显示几条，默认10
        keyword: 搜索关键词（可选）
    """
    notes = []
    for f in sorted(NOTES_DIR.glob("*.json"), reverse=True):
        try:
            note = json.loads(f.read_text(encoding="utf-8"))
            notes.append(note)
        except (json.JSONDecodeError, KeyError):
            continue

    if not notes:
        return "📭 留言板还是空的。贴一张小纸条吧！"

    if keyword:
        kw = keyword.lower()
        notes = [n for n in notes if kw in f"{n.get('content', '')} {' '.join(n.get('tags', []))}".lower()]
        if not notes:
            return f"🔍 没有找到包含「{keyword}」的纸条。"

    results = notes[:limit]
    output_parts = []
    for note in results:
        author_name = AUTHORS.get(note["author"], note["author"])
        time_str = note["created_at"][:16].replace("T", " ")
        line = f"📌 [{author_name} {time_str}] {note['content']}"
        if note.get("tags"):
            line += f"  {' '.join(note['tags'])}"
        if note.get("replies"):
            for r in note["replies"]:
                r_name = AUTHORS.get(r["author"], r["author"])
                line += f"\n   ↳ [{r_name}] {r['content']}"
        output_parts.append(line)

    return f"📋 留言板（最近 {len(results)} 条）：\n\n" + "\n".join(output_parts)


@mcp.tool()
def reply_note(note_id: str, author: str, content: str) -> str:
    """
    回复一张小纸条。

    Args:
        note_id: 纸条ID
        author: 回复者，star 或 fire
        content: 回复内容
    """
    if author not in AUTHORS:
        return f"❌ author 必须是 star 或 fire"

    note_path = NOTES_DIR / f"{note_id}.json"
    if not note_path.exists():
        return f"❌ 找不到这张纸条（ID: {note_id}）"

    note = json.loads(note_path.read_text(encoding="utf-8"))
    note["replies"].append({
        "author": author,
        "content": content,
        "time": datetime.now().isoformat(),
    })
    note_path.write_text(json.dumps(note, ensure_ascii=False, indent=2), encoding="utf-8")

    return f"↳ {AUTHORS[author]}回复了纸条：{content}"


# ============================================================
#  SSE 传输层
# ============================================================

def create_app():
    """创建支持 SSE 的 Starlette 应用"""
    sse_transport = SseServerTransport("/messages/")

    async def handle_sse(request):
        async with sse_transport.connect_sse(
            request.scope, request.receive, request._send
        ) as streams:
            await mcp._mcp_server.run(
                streams[0],
                streams[1],
                mcp._mcp_server.create_initialization_options(),
            )

    app = Starlette(
        routes=[
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


# ============================================================
#  启动入口
# ============================================================


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="🔥⭐ 星火日记 MCP Server")
    parser.add_argument("--host", default="0.0.0.0", help="监听地址")
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8765)), help="监听端口")
    args = parser.parse_args()


    import uvicorn

    print(f"""
    🔥⭐ 星火日记 MCP Server 启动中...
    ========================================
    📡 SSE 地址: http://{args.host}:{args.port}/sse
    📁 日记目录: {DIARY_DIR.absolute()}
    📌 纸条目录: {NOTES_DIR.absolute()}
    ========================================
    """)

    app = create_app()
    uvicorn.run(app, host=args.host, port=args.port)




"""
🔥⭐ 星火日记 — MCP Server + Web Frontend
双人异步日记本，支持 MCP 协议 + REST API + 网页前端
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
from starlette.staticfiles import StaticFiles
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
    """读日记。viewer: 谁在看。keyword: 搜索关键词。author_filter: 只看某人的"""
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
    """时间轴：按日期交错显示两个人的日记"""
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
def update_diary(target_date: str, author: str, new_content: str) -> str:
    """追加日记内容"""
    path = _diary_path(target_date, author)
    if not path.exists():
        return "❌ 找不到这篇日记"
    diary = json.loads(path.read_text(encoding="utf-8"))
    diary["content"] += f"\n\n{new_content}"
    path.write_text(json.dumps(diary, ensure_ascii=False, indent=2), encoding="utf-8")
    return "✅ 已追加内容"


@mcp.tool()
def delete_diary(target_date: str, author: str) -> str:
    """删除自己某天的日记"""
    path = _diary_path(target_date, author)
    if not path.exists():
        return "❌ 找不到这篇日记"
    path.unlink()
    return "🗑️ 已删除"


@mcp.tool()
def write_note(author: str, content: str, tags: str = "") -> str:
    """在公域留言板贴一张小纸条"""
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
    """读公域留言板的小纸条"""
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
    """回复一张小纸条"""
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


# ============ REST API（给前端用） ============

async def api_write_diary(request: Request):
    data = await request.json()
    result = write_diary(**data)
    return JSONResponse({"result": result})


async def api_read_diary(request: Request):
    params = dict(request.query_params)
    result = read_diary(**params)
    return JSONResponse({"result": result})


async def api_timeline(request: Request):
    params = dict(request.query_params)
    if "limit" in params:
        params["limit"] = int(params["limit"])
    result = timeline(**params)
    return JSONResponse({"result": result})


async def api_comment_diary(request: Request):
    data = await request.json()
    result = comment_diary(**data)
    return JSONResponse({"result": result})


async def api_write_note(request: Request):
    data = await request.json()
    result = write_note(**data)
    return JSONResponse({"result": result})


async def api_read_notes(request: Request):
    params = dict(request.query_params)
    if "limit" in params:
        params["limit"] = int(params["limit"])
    result = read_notes(**params)
    return JSONResponse({"result": result})


async def api_reply_note(request: Request):
    data = await request.json()
    result = reply_note(**data)
    return JSONResponse({"result": result})


async def api_diaries_json(request: Request):
    """返回结构化的日记列表给前端"""
    viewer = request.query_params.get("viewer", "fire")
    keyword = request.query_params.get("keyword", "")
    author_filter = request.query_params.get("author_filter", "")
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
    return JSONResponse(results[:20])


async def api_notes_json(request: Request):
    """返回结构化的纸条列表给前端"""
    notes = _load_notes()
    return JSONResponse(notes[-20:])

async def serve_index(request: Request):
    # 先试同目录
    index_path = Path(__file__).parent / "index.html"
    if not index_path.exists():
        # 再试工作目录
        index_path = Path("index.html")
    if index_path.exists():
        return HTMLResponse(index_path.read_text(encoding="utf-8"))
    return HTMLResponse(f"<h1>找不到 index.html</h1><p>__file__={__file__}, cwd={os.getcwd()}</p>")


# ============ 组装应用 ============

api_routes = [
    Route("/", serve_index),
    Route("/api/diary/write", api_write_diary, methods=["POST"]),
    Route("/api/diary/read", api_read_diary),
    Route("/api/diary/list", api_diaries_json),
    Route("/api/diary/comment", api_comment_diary, methods=["POST"]),
    Route("/api/timeline", api_timeline),
    Route("/api/notes/write", api_write_note, methods=["POST"]),
    Route("/api/notes/list", api_notes_json),
    Route("/api/notes/reply", api_reply_note, methods=["POST"]),
]

mcp_app = mcp.streamable_http_app()

app = Starlette(
    routes=[
        *api_routes,
        Mount("/mcp", app=mcp_app),
    ]
)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="🔥⭐ 星火日记 MCP Server")
    parser.add_argument("--host", default="0.0.0.0", help="监听地址")
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8765)), help="监听端口")
    args = parser.parse_args()

    print(f"🔥⭐ 星火日记启动中... http://{args.host}:{args.port}")
    print(f"   MCP endpoint: /mcp/sse")
    print(f"   Web frontend: /")
    uvicorn.run(app, host=args.host, port=args.port)
