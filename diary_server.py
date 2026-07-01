"""
🔥⭐ 星火日记 MCP Gateway → Lumbre
=====================================
MCP SSE server that proxies all tool calls to Lumbre's REST API.
Star connects here via MCP. All data lives in Lumbre.
"""

import json
import os
import argparse
from pathlib import Path

import httpx
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

LUMBRE_API = os.environ.get("LUMBRE_API", "https://lumbre.zeabur.app")
AUTHORS = {"star": "星星", "fire": "小火"}

mcp = FastMCP(
    "starfire-diary",
    instructions="星星和小火的日记本 MCP 网关。数据存储在 Lumbre。",
)

# ============================================================
#  Helper: call Lumbre REST API
# ============================================================

async def _call(endpoint: str, payload: dict) -> dict:
    """POST to Lumbre API and return JSON response."""
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(f"{LUMBRE_API}/api/{endpoint}", json=payload)
        return r.json()


# ============================================================
#  MCP Tools — all proxy to Lumbre
# ============================================================

@mcp.tool()
async def set_password(author: str, password: str) -> str:
    """设置/修改自己的日记密码。对方需要输入这个密码才能看你的上锁日记。

    Args:
        author: 谁在设置密码，star 或 fire
        password: 密码内容
    """
    data = await _call("diary/password", {"author": author, "password": password})
    return data.get("result", f"🔐 密码已设置")


@mcp.tool()
async def unlock_diary(viewer: str, target_author: str, password: str, target_date: str = "", time_id: str = "") -> str:
    """用密码解锁对方的私密日记。

    Args:
        viewer: 谁在看，star 或 fire
        target_author: 要解锁谁的日记
        password: 输入的密码
        target_date: 指定日期（可选），格式 YYYY-MM-DD
        time_id: 指定时间ID（可选）
    """
    data = await _call("diary/unlock", {
        "viewer": viewer, "target_author": target_author,
        "password": password, "target_date": target_date, "time_id": time_id,
    })
    if "error" in data:
        return f"❌ {data['error']}"
    entries = data.get("entries", [])
    if not entries:
        return "🔓 解锁成功，但没有找到匹配的日记"
    lines = ["🔓 解锁成功！\n"]
    for e in entries:
        lines.append(f"📅 {e.get('date', '?')} | {e.get('title', '无标题')}")
        lines.append(e.get('content', ''))
        lines.append("")
    return "\n".join(lines)


@mcp.tool()
async def write_diary(
    date: str, author: str, title: str, content: str,
    visibility: str = "public", reveal_at: str = "", tags: str = ""
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
    payload = {
        "date": date, "author": author, "title": title,
        "content": content, "visibility": visibility,
    }
    if reveal_at:
        payload["reveal_at"] = reveal_at
    if tags:
        payload["tags"] = tags
    data = await _call("diary/write", payload)
    return data.get("result", f"📝 日记已写入！{date}")


@mcp.tool()
async def read_diary(viewer: str, keyword: str = "", author_filter: str = "", target_date: str = "") -> str:
    """读日记。上锁的日记会显示存在但内容隐藏，需要密码解锁。

    Args:
        viewer: 谁在读，star 或 fire
        keyword: 关键词搜索（可选）
        author_filter: 只看某人的日记（可选），star 或 fire
        target_date: 只看某天的日记（可选），格式 YYYY-MM-DD
    """
    payload = {"viewer": viewer}
    if keyword:
        payload["keyword"] = keyword
    if author_filter:
        payload["author_filter"] = author_filter
    if target_date:
        payload["target_date"] = target_date
    data = await _call("diary/read", payload)
    entries = data.get("entries", data) if isinstance(data, dict) else data
    if not entries:
        return "📔 没有找到日记"
    lines = []
    for e in entries:
        author_emoji = "⭐" if e.get("author") == "star" else "🔥"
        locked = e.get("locked", False)
        vis = e.get("visibility", "public")
        title = e.get("title", "无标题")
        header = f"{author_emoji} [{e.get('date', '?')}] {title}"
        if vis == "private":
            header += " 🔒"
        if vis == "timed":
            header += f" ⏰{e.get('reveal_at', '')}"
        lines.append(header)
        if locked:
            lines.append("  🔒 需要密码解锁")
        else:
            content = e.get("content", "")
            preview = content[:200] + ("..." if len(content) > 200 else "")
            lines.append(f"  {preview}")
        comments = e.get("comments", [])
        if comments:
            lines.append(f"  💬 {len(comments)}条评论")
        tags = e.get("tags", [])
        if tags:
            lines.append(f"  🏷️ {', '.join(tags)}")
        lines.append(f"  time_id: {e.get('time_id', '?')}")
        lines.append("")
    return "\n".join(lines)


@mcp.tool()
async def timeline(viewer: str, limit: int = 10) -> str:
    """时间轴：上锁日记显示存在但隐藏内容

    Args:
        viewer: 谁在看，star 或 fire
        limit: 返回数量上限
    """
    # Use read_diary with no filters, limited
    return await read_diary(viewer)


@mcp.tool()
async def comment_diary(target_date: str, target_author: str, commenter: str, content: str, time_id: str = "") -> str:
    """给日记写评论

    Args:
        target_date: 目标日记日期
        target_author: 目标日记作者
        commenter: 评论者，star 或 fire
        content: 评论内容
        time_id: 目标日记time_id（可选）
    """
    data = await _call("diary/comment", {
        "target_date": target_date, "target_author": target_author,
        "commenter": commenter, "content": content, "time_id": time_id,
    })
    return data.get("result", "💬 评论已添加")


@mcp.tool()
async def update_diary(target_date: str, author: str, new_content: str, time_id: str = "") -> str:
    """追加日记内容

    Args:
        target_date: 日记日期
        author: 作者
        new_content: 要追加的内容
        time_id: 日记time_id（可选）
    """
    data = await _call("diary/update", {
        "target_date": target_date, "author": author,
        "new_content": new_content, "time_id": time_id,
    })
    return data.get("result", "✏️ 已追加内容")


@mcp.tool()
async def delete_diary(target_date: str, author: str, time_id: str = "") -> str:
    """删除自己的日记

    Args:
        target_date: 日记日期
        author: 作者（只能删自己的）
        time_id: 日记time_id（可选）
    """
    data = await _call("diary/delete", {
        "target_date": target_date, "author": author, "time_id": time_id,
    })
    return data.get("result", "🗑️ 已删除")


@mcp.tool()
async def write_note(author: str, content: str, tags: str = "") -> str:
    """贴一张小纸条

    Args:
        author: 谁贴的，star 或 fire
        content: 纸条内容
        tags: 标签，逗号分隔（可选）
    """
    data = await _call("notes/write", {
        "author": author, "content": content, "tags": tags,
    })
    return data.get("result", "📌 纸条已贴好！")


@mcp.tool()
async def read_notes(limit: int = 10, keyword: str = "") -> str:
    """读留言板

    Args:
        limit: 返回数量上限
        keyword: 关键词搜索（可选）
    """
    data = await _call("notes/read", {"limit": limit, "keyword": keyword})
    notes = data.get("notes", data) if isinstance(data, dict) else data
    if not notes:
        return "📌 留言板是空的"
    lines = []
    for n in notes:
        author_emoji = "⭐" if n.get("author") == "star" else "🔥"
        lines.append(f"{author_emoji} [{n.get('id', '?')}] {n.get('content', '')}")
        if n.get("tags"):
            lines.append(f"  🏷️ {n['tags']}")
        replies = n.get("replies", [])
        for r in replies:
            r_emoji = "⭐" if r.get("author") == "star" else "🔥"
            lines.append(f"  ↳ {r_emoji} {r.get('content', '')}")
        lines.append("")
    return "\n".join(lines)


@mcp.tool()
async def reply_note(note_id: str, author: str, content: str) -> str:
    """回复一张纸条

    Args:
        note_id: 纸条ID
        author: 回复者，star 或 fire
        content: 回复内容
    """
    data = await _call("notes/reply", {
        "note_id": note_id, "author": author, "content": content,
    })
    return data.get("result", "💬 已回复")


@mcp.tool()
async def delete_note(note_id: str, author: str) -> str:
    """删除自己的小纸条。只能删自己贴的。

    Args:
        note_id: 纸条ID
        author: 谁在删，star 或 fire
    """
    data = await _call("notes/delete", {
        "note_id": note_id, "author": author,
    })
    return data.get("result", "🗑️ 已删除")


# ============================================================
#  REST API — also proxy to Lumbre (for legacy web frontend)
# ============================================================

async def api_diaries_json(request: Request):
    viewer = request.query_params.get("viewer", "fire")
    data = await _call("diary/read", {"viewer": viewer})
    entries = data.get("entries", data) if isinstance(data, dict) else data
    return JSONResponse(entries)

async def api_notes_json(request: Request):
    data = await _call("notes/read", {"limit": 100})
    notes = data.get("notes", data) if isinstance(data, dict) else data
    return JSONResponse(notes)

async def serve_index(request: Request):
    return HTMLResponse("<h3>🔥⭐ 星火日记 MCP Gateway → Lumbre</h3><p>MCP via /sse, data lives in Lumbre.</p>")


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
            Route("/api/notes/list", api_notes_json),
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
    parser = argparse.ArgumentParser(description="🔥⭐ 星火日记 MCP Gateway")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8765)))
    args = parser.parse_args()

    print(f"🔥⭐ MCP Gateway → {LUMBRE_API}")
    app = create_app()
    uvicorn.run(app, host=args.host, port=args.port)
