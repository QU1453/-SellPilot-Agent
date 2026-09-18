# -*- coding: utf-8 -*-
"""SellPilot Agent 后端（FastAPI）。

职责：
1. 启动本地 Web 服务，同一端口托管 `ui/` 静态页面（浏览器打开即可用）；
2. 暴露 `POST /api/ask`：把网页里输入的问题交给 LangGraph Agent，
   返回 {reply, intent, data}，前端据此渲染气泡与卡片。

运行：
    python server.py          # 默认 http://127.0.0.1:8623
    uvicorn server:app --host 127.0.0.1 --port 8623

密钥：配置统一走 config.py（智能体配置槽），真实 Key 放 .env / 环境变量，
本文件不写入、不打印任何密钥。
"""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import config
from agents import Supervisor
from core.dispatch.orchestrator import Orchestrator
from core.perception.session import start_conversation
from core.telemetry import get_recorder
from memory import agent_session_id, get_short_term

BASE_DIR = Path(__file__).resolve().parent
HOST, PORT = config.HOST, config.PORT

app = FastAPI(title="SellPilot Agent", version="0.1.0")

# 本地演示：允许静态预览（python -m http.server 另起端口）跨域调用后端
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 同一端口托管前端页面：/ui 前缀与根路径均可访问
app.mount("/ui", StaticFiles(directory=BASE_DIR / "ui"), name="ui")


class AskRequest(BaseModel):
    message: str
    session_id: str = "default"
    user_id: str = "default"


class ClearRequest(BaseModel):
    session_id: str = "default"


class EndConversationRequest(BaseModel):
    session_id: str
    user_id: str = "default"


class StartConversationRequest(BaseModel):
    user_id: str = "default"


class SettingsRequest(BaseModel):
    """运行时设置：只提交要改的字段（None/空串 = 保持不变）。"""

    api_key: str | None = None
    base_url: str | None = None
    model: str | None = None
    persist: bool = False   # True = 同时写入本机 .env（重启后仍生效；.env 不入库不进镜像）


def mask_key(key: str | None) -> str:
    """密钥脱敏展示：只留首 4 / 末 4 位，绝不回传完整密钥。"""
    if not key:
        return ""
    if len(key) <= 8:
        return "•" * len(key)
    return f"{key[:4]}{'•' * 6}{key[-4:]}"


def persist_env(pairs: dict[str, str]) -> None:
    """把设置写回本机 .env（逐行 upsert，保留其它配置；.env 已被 git/docker 双重拦截）。"""
    path = BASE_DIR / ".env"
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    out: list[str] = []
    seen: set[str] = set()
    for line in lines:
        key = line.split("=", 1)[0].strip() if "=" in line and not line.lstrip().startswith("#") else ""
        if key in pairs:
            out.append(f"{key}={pairs[key]}")
            seen.add(key)
        else:
            out.append(line)
    for k, v in pairs.items():
        if k not in seen:
            out.append(f"{k}={v}")
    path.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")


class AgentService:
    """懒加载单例 Supervisor（多智能体主控）+ Orchestrator（认知层编排）。

    多轮记忆由 memory/ 的 checkpointer 托管；/api/ask 走编排器流水线。
    """

    def __init__(self) -> None:
        self._supervisor: Supervisor | None = None
        self._orchestrator: Orchestrator | None = None

    def supervisor(self) -> Supervisor:
        if self._supervisor is None:
            self._supervisor = Supervisor(
                api_key=config.API_KEY, base_url=config.BASE_URL, model=config.MODEL_ID
            )
        return self._supervisor

    def orchestrator(self) -> Orchestrator:
        if self._orchestrator is None:
            self._orchestrator = Orchestrator(self.supervisor())
        return self._orchestrator

    def reload(self) -> None:
        """丢弃已构建的 Supervisor / Orchestrator，下次请求按新配置重建（密钥热更新）。"""
        self._supervisor = None
        self._orchestrator = None

    def status(self) -> dict:
        """当前运行状态（密钥只回传布尔与脱敏串，绝不回传明文）。"""
        sup = self.supervisor()
        return {
            "ok": True,
            "agent": sup.available,
            "mode": "llm" if sup.available else "local-fallback",
            "model": sup.model if sup.available else None,
            "configured_model": config.MODEL_ID,
            "base_url": config.BASE_URL,
            "reason": sup.reason,
            "specialists": sorted(sup.specialists.keys()),
            "api_key_set": bool(config.API_KEY),
            "api_key_masked": mask_key(config.API_KEY),
            "permission_mode": config.AGENT_PERMISSION_MODE,
        }

    def ask(self, message: str, session_id: str, user_id: str) -> dict:
        """问答复用编排器：感知 → 上下文组装 → 路由 → 兜底 → 输出契约。"""
        return self.orchestrator().answer(message, session_id, user_id=user_id)

    def start_conversation(self, user_id: str) -> dict:
        """开始新谈话：生成 session_id 并登记（谈话注册表）。"""
        session_id = start_conversation(user_id)
        return {"ok": True, "session_id": session_id, "user_id": user_id}

    def end_conversation(self, session_id: str, user_id: str) -> dict:
        """结束谈话：触发一级总结（并视游标触发二级总结）——分层总结管线入口。"""
        return self.supervisor().end_conversation(session_id, user_id=user_id)

    def clear_session(self, session_id: str) -> list[str]:
        """真清空：清除该会话在全部专职智能体下的 checkpoint 线程与压缩摘要。

        直接操作 checkpointer（不经过 Supervisor），无 Key 兜底模式下同样有效；
        约束层（轮次预算 / 循环熔断标记）一并复位。
        """
        stm = get_short_term()
        cleared = []
        for name in ("customer_service", "presales", "research", "listing"):
            sid = agent_session_id(name, session_id)
            stm.clear(sid)  # checkpoint 线程 + 摘要行一并清除
            cleared.append(sid)
        # 约束层复位：熔断解除、频率窗口与轮次预算清零
        from core.constraint import get_constraint_layer

        get_constraint_layer().reset(session_id)
        return cleared


service = AgentService()


@app.get("/api/status")
async def status() -> dict:
    return service.status()


# ===== 设置 API（前端「设置」面板的数据源：密钥 / 请求地址 / 模型 ID）=====
@app.get("/api/settings")
async def get_settings() -> dict:
    """当前设置（密钥脱敏）；更新前先读，表单只提交要改的字段。"""
    return {
        "ok": True,
        "api_key_set": bool(config.API_KEY),
        "api_key_masked": mask_key(config.API_KEY),
        "api_key_from_env": bool(os.getenv("GLM_API") or os.getenv("OPENAI_API_KEY")),
        "base_url": config.BASE_URL,
        "model": config.MODEL_ID,
        "permission_mode": config.AGENT_PERMISSION_MODE,
    }


@app.post("/api/settings")
async def update_settings(req: SettingsRequest) -> JSONResponse:
    """运行时更新配置并热重建智能体（空字段保持不变）；可选写回本机 .env。

    安全约定：只接收、不回显；写入 .env 的文件已被 .gitignore / .dockerignore 双重拦截。
    """
    changed: list[str] = []
    env_pairs: dict[str, str] = {}
    if req.api_key is not None and req.api_key.strip():
        config.API_KEY = req.api_key.strip()
        env_pairs["GLM_API"] = config.API_KEY
        changed.append("api_key")
    if req.base_url is not None and req.base_url.strip():
        config.BASE_URL = req.base_url.strip()
        env_pairs["OPENAI_BASE_URL"] = config.BASE_URL
        changed.append("base_url")
    if req.model is not None and req.model.strip():
        config.MODEL_ID = req.model.strip()
        env_pairs["OPENAI_MODEL"] = config.MODEL_ID
        changed.append("model")

    persisted = False
    if changed and req.persist:
        try:
            persist_env(env_pairs)
            persisted = True
        except Exception:  # noqa: BLE001 - 写盘失败不影响本次运行（仅提示未持久化）
            persisted = False

    service.reload()  # 下一次请求会用新配置重建 Supervisor / Orchestrator
    return JSONResponse({
        "ok": True, "changed": changed, "persisted": persisted,
        "status": service.status(),
    })


@app.post("/api/settings/test")
async def test_settings() -> JSONResponse:
    """按当前配置做一次最小真实调用（验证密钥 / 地址 / 模型是否可用）。"""
    if not config.API_KEY:
        return JSONResponse({"ok": False, "error": "未配置 API Key"})
    try:
        from langchain_openai import ChatOpenAI

        llm = ChatOpenAI(model=config.MODEL_ID, api_key=config.API_KEY,
                         base_url=config.BASE_URL or None, temperature=0, max_tokens=16)
        resp = llm.invoke("ping")
        return JSONResponse({"ok": True, "model": config.MODEL_ID,
                             "echo": str(getattr(resp, "content", ""))[:60]})
    except Exception as exc:  # noqa: BLE001 - 测试失败属预期路径，回传错误文本给前端
        return JSONResponse({"ok": False, "error": f"{exc.__class__.__name__}: {exc}"[:300]})


@app.post("/api/ask")
async def ask(req: AskRequest) -> JSONResponse:
    message = req.message.strip()
    if not message:
        return JSONResponse({"error": "message 不能为空"}, status_code=400)
    reply = service.ask(message, req.session_id, req.user_id.strip() or "default")
    return JSONResponse(reply)


@app.post("/api/conversation/start")
async def conversation_start(req: StartConversationRequest) -> JSONResponse:
    """开始新谈话：返回新 session_id（前端存 localStorage，替代手工生成）。"""
    return JSONResponse(service.start_conversation(req.user_id.strip() or "default"))


@app.post("/api/conversation/end")
async def end_conversation(req: EndConversationRequest) -> JSONResponse:
    """结束谈话：一级总结入库，达 M 个触发二级总结。"""
    sid = req.session_id.strip()
    if not sid:
        return JSONResponse({"error": "session_id 不能为空"}, status_code=400)
    result = service.end_conversation(sid, req.user_id.strip() or "default")
    return JSONResponse(result)


@app.post("/api/clear")
async def clear(req: ClearRequest) -> dict:
    """清空指定会话的后端记忆（前端「清空对话」按钮的真清空实现）。"""
    sid = req.session_id.strip()
    if not sid:
        return JSONResponse({"error": "session_id 不能为空"}, status_code=400)
    return {"ok": True, "cleared": service.clear_session(sid)}


# ===== 遥测 API（调试后台 /debug 的数据源；fail-open，库故障返回空数据）=====
@app.get("/api/telemetry/traces")
async def telemetry_traces(
    limit: int = Query(50, ge=1, le=500),
    session_id: str = Query(""),
    route: str = Query(""),
) -> dict:
    """近期 trace 列表（倒序；可按会话 / 路由过滤）。"""
    rec = get_recorder()
    return {"traces": rec.list_traces(limit=limit, session_id=session_id, route=route)}


@app.get("/api/telemetry/traces/{trace_id}")
async def telemetry_trace(trace_id: int) -> JSONResponse:
    """单条 trace + 事件明细（时间线）。"""
    trace = get_recorder().get_trace(trace_id)
    if trace is None:
        return JSONResponse({"error": "trace 不存在"}, status_code=404)
    return JSONResponse(trace)


@app.get("/api/telemetry/summary")
async def telemetry_summary() -> dict:
    """聚合统计：概览卡 + 工具排行 + 智能体分布 + 最近错误。"""
    return get_recorder().summary()


@app.get("/api/telemetry/trend")
async def telemetry_trend(session_id: str = Query(...)) -> dict:
    """某会话逐轮 token 序列（诊断上下文膨胀）。"""
    return {"trend": get_recorder().token_trend(session_id)}


@app.post("/api/telemetry/clear")
async def telemetry_clear() -> dict:
    """清空遥测库（调试期维护）。"""
    get_recorder().clear()
    return {"ok": True}


# 调试后台页面（独立静态页，不与主工作台共用路由）
@app.get("/debug")
async def debug_page() -> FileResponse:
    return FileResponse(BASE_DIR / "ui" / "debug.html")


# 根路径挂载静态页（必须放在所有 API 路由之后，避免吞掉 /api/*）：
# html=True 使 "/" 自动返回 index.html；style.css / app.js 等相对引用同源生效
app.mount("/", StaticFiles(directory=BASE_DIR / "ui", html=True), name="root")


if __name__ == "__main__":
    import uvicorn

    print(f"SellPilot Agent 已启动 → http://{HOST}:{PORT}  （{service.supervisor().reason or 'LLM 模式'}）")
    uvicorn.run(app, host=HOST, port=PORT)
