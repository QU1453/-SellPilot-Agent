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

import hashlib
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
    temperature: float | None = None           # 采样温度 0~2
    permission_mode: str | None = None         # plan / ask / accept / bypass
    call_token_budget: int | None = None       # 单次请求 token 预算
    cost_budget: float | None = None           # 单会话累计金额上限
    cost_currency: str | None = None           # CNY / USD
    persist: bool = False   # True = 同时写入本机 .env（重启后仍生效；.env 不入库不进镜像）


class TestSettingsRequest(BaseModel):
    """连接测试：优先测表单里当前填的值，未填则回落到已保存配置。

    —— 这样「先填 Key 再点测试」就能立刻验证，不必先保存。
    """

    api_key: str | None = None
    base_url: str | None = None
    model: str | None = None


PERMISSION_MODES = ("plan", "ask", "accept", "bypass")
CURRENCIES = ("CNY", "USD")


def mask_key(key: str | None) -> str:
    """密钥脱敏展示：只留首 4 / 末 4 位，绝不回传完整密钥。"""
    if not key:
        return ""
    if len(key) <= 8:
        return "•" * len(key)
    return f"{key[:4]}{'•' * 6}{key[-4:]}"


def config_fingerprint(api_key: str | None, base_url: str | None, model: str | None) -> str:
    """LLM 配置指纹：用于判断上一次连接测试结果是否仍适用于当前配置。"""
    raw = f"{api_key or ''}|{base_url or ''}|{model or ''}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()[:12]


def persist_env(pairs: dict[str, str]) -> None:
    """把设置写回本机 .env（逐行 upsert，保留其它配置；.env 已被 git/docker 双重拦截）。

    匹配时会忽略行首的「#」，所以像 `# GLM_API=` 这样的注释占位行会被就地替换，
    不会重复追加同名的键。
    """
    path = BASE_DIR / ".env"
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    out: list[str] = []
    seen: set[str] = set()
    for line in lines:
        bare = line.lstrip().lstrip("#").strip()
        key = bare.split("=", 1)[0].strip() if "=" in bare else ""
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
        # 最近一次连接测试结果（含配置指纹；指纹不匹配即视为未验证）
        self._verify: dict | None = None

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

    def record_verification(self, ok: bool, error: str | None,
                            fingerprint: str) -> None:
        """记录一次连接测试结果（带配置指纹）。"""
        self._verify = {"ok": bool(ok), "error": error, "fp": fingerprint}

    def verification(self) -> tuple[bool | None, str | None]:
        """当前配置的验证状态：None=未验证 / True=通过 / False=失败。

        配置（Key / 地址 / 模型）一变，旧结果立即作废——避免"改了密钥还显示在线"。
        """
        v = self._verify
        if not v:
            return None, None
        if v["fp"] != config_fingerprint(config.API_KEY, config.BASE_URL, config.MODEL_ID):
            return None, None
        return v["ok"], v["error"]

    def status(self) -> dict:
        """当前运行状态（密钥只回传布尔与脱敏串，绝不回传明文）。

        mode/agent 只表示「是否配好了 LLM」，不代表密钥可用；
        密钥是否真的能连通，看 key_verified（需先做一次连接测试）。
        """
        sup = self.supervisor()
        verified, verify_error = self.verification()
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
            "key_verified": verified,
            "key_error": verify_error,
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


# ===== 设置 API（前端「设置」面板的数据源：密钥 / 地址 / 模型 / 温度 / 权限 / 预算）=====
@app.get("/api/settings")
async def get_settings() -> dict:
    """当前设置（密钥脱敏）；更新前先读，表单只提交要改的字段。"""
    verified, verify_error = service.verification()
    return {
        "ok": True,
        "api_key_set": bool(config.API_KEY),
        "api_key_masked": mask_key(config.API_KEY),
        "api_key_from_env": bool(os.getenv("GLM_API") or os.getenv("OPENAI_API_KEY")),
        "key_verified": verified,
        "key_error": verify_error,
        "base_url": config.BASE_URL,
        "model": config.MODEL_ID,
        "temperature": config.LLM_TEMPERATURE,
        "permission_mode": config.AGENT_PERMISSION_MODE,
        "permission_modes": list(PERMISSION_MODES),
        "call_token_budget": config.CONTEXT_TOKEN_GUARD,
        "cost_budget": config.SESSION_COST_BUDGET,
        "cost_currency": config.SESSION_COST_BUDGET_CUR,
        "cost_budget_cny": config.SESSION_COST_BUDGET_CNY,
        "currencies": list(CURRENCIES),
        "usd_cny_rate": config.USD_CNY_RATE,
    }


@app.post("/api/settings")
async def update_settings(req: SettingsRequest) -> JSONResponse:
    """运行时更新配置并热重建智能体（空字段保持不变）；可选写回本机 .env。

    校验通过才落盘：任何一项不合法则整体不生效（避免"一半改了一半没改"）。
    """
    changed: list[str] = []
    errors: list[str] = []
    env_pairs: dict[str, str] = {}
    updates: list[tuple[str, object]] = []   # (设置名, setter) —— 校验通过后统一应用

    # ---- 第一步：只校验，不写 ----
    key = (req.api_key or "").strip()
    if key:
        # 常见误填：把请求地址贴进了密钥槽（会导致"显示在线但每次 401"）
        if "://" in key or key.lower().startswith(("http", "www.")):
            errors.append("API Key 看起来是一个网址，请填密钥；网址应填在「请求地址」里")
        else:
            updates.append(("api_key", key))
    url = (req.base_url or "").strip()
    if url:
        if "://" not in url:
            errors.append("请求地址需要是完整 URL（含 http:// 或 https://）")
        else:
            updates.append(("base_url", url))
    model = (req.model or "").strip()
    if model:
        updates.append(("model", model))

    temperature = None
    if req.temperature is not None:
        temperature = min(2.0, max(0.0, float(req.temperature)))
        updates.append(("temperature", temperature))

    mode = (req.permission_mode or "").strip().lower()
    if mode:
        if mode not in PERMISSION_MODES:
            errors.append(f"权限模式只能是 {'/'.join(PERMISSION_MODES)}")
        else:
            updates.append(("permission_mode", mode))

    if req.call_token_budget is not None:
        if int(req.call_token_budget) <= 0:
            errors.append("单次 token 预算需为正整数")
        else:
            updates.append(("call_token_budget", int(req.call_token_budget)))

    cost_value = currency = None
    if req.cost_budget is not None:
        currency = (req.cost_currency or config.SESSION_COST_BUDGET_CUR).strip().upper()
        if currency not in CURRENCIES:
            errors.append(f"币种只能是 {'/'.join(CURRENCIES)}")
        else:
            cost_value = max(0.0, float(req.cost_budget))

    if errors:
        return JSONResponse({"ok": False, "changed": [], "errors": errors,
                             "persisted": False, "status": service.status()})

    # ---- 第二步：应用（此时已确定无校验错误）----
    for name, value in updates:
        if name == "api_key":
            config.API_KEY = value
            env_pairs["GLM_API"] = value
            changed.append(name)
        elif name == "base_url":
            config.BASE_URL = value
            env_pairs["OPENAI_BASE_URL"] = value
            changed.append(name)
        elif name == "model":
            config.MODEL_ID = value
            env_pairs["OPENAI_MODEL"] = value
            changed.append(name)
        elif name == "temperature":
            config.LLM_TEMPERATURE = value
            env_pairs["LLM_TEMPERATURE"] = str(value)
            changed.append(name)
        elif name == "permission_mode":
            config.AGENT_PERMISSION_MODE = value
            env_pairs["AGENT_PERMISSION_MODE"] = value
            changed.append(name)
        elif name == "call_token_budget":
            config.CONTEXT_TOKEN_GUARD = value
            env_pairs["CONTEXT_TOKEN_GUARD"] = str(value)
            changed.append(name)

    if cost_value is not None:
        config.apply_cost_budget(cost_value, currency)
        env_pairs["SESSION_COST_BUDGET"] = str(config.SESSION_COST_BUDGET)
        env_pairs["SESSION_COST_BUDGET_CUR"] = config.SESSION_COST_BUDGET_CUR
        changed.append("cost_budget")

    persisted = False
    if changed and req.persist:
        try:
            persist_env(env_pairs)
            persisted = True
        except Exception:  # noqa: BLE001 - 写盘失败不影响本次运行（仅提示未持久化）
            persisted = False

    service.reload()  # 下一次请求会用新配置重建 Supervisor / Orchestrator
    return JSONResponse({
        "ok": True, "changed": changed, "errors": [], "persisted": persisted,
        "status": service.status(),
    })


@app.post("/api/settings/test")
async def test_settings(req: TestSettingsRequest | None = None) -> JSONResponse:
    """做一次最小真实调用，验证 Key / 地址 / 模型是否可用。

    优先用请求体里表单当前填的值（可不保存先验证），未填则回落到已保存配置。
    """
    api_key = (req.api_key or "").strip() if req else ""
    base_url = (req.base_url or "").strip() if req else ""
    model = (req.model or "").strip() if req else ""
    key = api_key or config.API_KEY
    url = base_url or config.BASE_URL
    mid = model or config.MODEL_ID

    fingerprint = config_fingerprint(key, url, mid)
    if not key:
        service.record_verification(False, "未配置 API Key", fingerprint)
        return JSONResponse({"ok": False, "error": "未配置 API Key", "verified": False})
    try:
        from langchain_openai import ChatOpenAI

        llm = ChatOpenAI(model=mid, api_key=key, base_url=url or None,
                         temperature=config.LLM_TEMPERATURE, max_tokens=16, timeout=20)
        resp = llm.invoke("ping")
        service.record_verification(True, None, fingerprint)
        return JSONResponse({
            "ok": True, "model": mid, "verified": True,
            "echo": str(getattr(resp, "content", ""))[:60],
        })
    except Exception as exc:  # noqa: BLE001 - 测试失败属预期路径，回传错误文本给前端
        error = f"{exc.__class__.__name__}: {exc}"[:300]
        service.record_verification(False, error, fingerprint)
        return JSONResponse({"ok": False, "error": error, "verified": False})


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
