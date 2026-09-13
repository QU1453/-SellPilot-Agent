# -*- coding: utf-8 -*-
"""工具层（core/toolkit/）单元测试：MCP 协议 / 参数校验 / 动态暴露 / 重试超时 / 异常兜底。

覆盖用户规范的全部要点：
- 注册分发机制（BaseTool 继承 + ToolRegistry.register）；
- 参数校验（类型 / 必填 / 范围）失败 → 错误提示返回模型；
- MCP 三方法时序 initialize → tools/list → tools/call（content 数组 + 状态码 + 元信息）；
- MCP client 协议封装 / 连接管理 / 重试最多 5 次 / 超时；
- 分阶段动态加载（阶段一轮次 → 阶段二角色）+ 配置黑名单 + read_only 权限元数据；
- try/except 包裹全流程：工具内部任何异常都丢给大模型。
"""
from __future__ import annotations

import pytest

import config
from core.toolkit import (
    AgentConfig,
    BaseTool,
    FunctionTool,
    InProcessTransport,
    MCPClient,
    MCPServer,
    PlanningTool,
    ReadFileTool,
    Status,
    StdioTransport,
    ToolRegistry,
    TransportError,
    build_default_registry,
    estimate_planning_rounds,
    schema_from_signature,
    to_langchain_tools,
    validate_arguments,
)
from core.toolkit.client import Transport


# ============================================================
# 1) 基类与签名 → schema
# ============================================================
class TestBaseToolAndSchema:
    def test_base_tool_is_abstract(self):
        with pytest.raises(TypeError):
            BaseTool()

    def test_mcp_and_openai_entries(self):
        tool = ReadFileTool()
        mcp = tool.mcp_entry()
        assert set(mcp) == {"name", "description", "inputSchema", "annotations"}
        assert mcp["annotations"]["readOnlyHint"] is True
        fn = tool.openai_entry()
        assert fn["type"] == "function"
        assert fn["function"]["name"] == "read_file"
        assert fn["function"]["parameters"]["required"] == ["path"]

    def test_schema_from_signature_types_and_required(self):
        def demo(path: str, limit: int = 10, tags: list[str] | None = None,
                 ratio: float = 1.0, flag: bool = False):
            """demo"""

        schema = schema_from_signature(demo, {"path": "文件路径"})
        props = schema["properties"]
        assert props["path"] == {"type": "string", "description": "文件路径"}
        assert props["limit"]["type"] == "integer"
        assert props["tags"]["type"] == "array"
        assert props["tags"]["items"] == {"type": "string"}
        assert props["ratio"]["type"] == "number"
        assert props["flag"]["type"] == "boolean"
        assert schema["required"] == ["path"]

    def test_function_tool_wraps_exception(self):
        def boom(x: str) -> str:
            raise ValueError("炸了")

        tool = FunctionTool(boom, name="boom", description="d")
        ok, text = tool.execute({"x": "1"}, AgentConfig())
        assert ok is False and "ValueError" in text and "炸了" in text


# ============================================================
# 2) 参数校验
# ============================================================
class TestValidation:
    SCHEMA = {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 100},
            "mode": {"type": "string", "enum": ["a", "b"]},
            "items": {"type": "array", "items": {"type": "integer"}, "minItems": 1},
        },
        "required": ["path"],
    }

    def test_required_missing(self):
        ok, msg = validate_arguments(self.SCHEMA, {})
        assert not ok and "缺少必填参数 'path'" in msg

    def test_type_mismatch(self):
        ok, msg = validate_arguments(self.SCHEMA, {"path": "x", "limit": "10"})
        assert not ok and "limit" in msg and "整数" in msg

    def test_bool_is_not_integer(self):
        ok, _ = validate_arguments(self.SCHEMA, {"path": "x", "limit": True})
        assert not ok

    def test_range_min_max(self):
        ok, msg = validate_arguments(self.SCHEMA, {"path": "x", "limit": 0})
        assert not ok and "最小值" in msg
        ok, msg = validate_arguments(self.SCHEMA, {"path": "x", "limit": 101})
        assert not ok and "最大值" in msg

    def test_enum_and_items(self):
        ok, msg = validate_arguments(self.SCHEMA, {"path": "x", "mode": "c"})
        assert not ok and "取值必须" in msg
        ok, msg = validate_arguments(self.SCHEMA, {"path": "x", "items": [1, "2"]})
        assert not ok and "items[1]" in msg

    def test_ok(self):
        ok, msg = validate_arguments(self.SCHEMA, {"path": "x", "limit": 10, "mode": "a",
                                                   "items": [1, 2]})
        assert ok and msg == ""


# ============================================================
# 3) 注册 / 查询 / 动态暴露（三原则）
# ============================================================
class TestRegistryExposure:
    def build(self):
        reg = ToolRegistry()
        reg.register(PlanningTool())
        reg.register(ReadFileTool())
        reg.register(FunctionTool(lambda order_no: "ok", name="query_order_info",
                                  description="查订单", roles={"customer_service"}))
        reg.register(FunctionTool(lambda order_no, reason="": "ok", name="handle_return",
                                  description="退货", roles={"customer_service"},
                                  read_only=False))
        reg.register(FunctionTool(lambda product_name: "ok", name="draft_listing",
                                  description="写listing", roles={"listing"}))
        return reg

    def test_register_get_unregister(self):
        reg = self.build()
        assert reg.get("read_file").name == "read_file"
        assert "read_file" in reg.names()
        reg.unregister("read_file")
        assert reg.get("read_file") is None

    def test_register_requires_name(self):
        class _NoName(BaseTool):
            name = ""

            def get_schema(self):
                return {}

            def execute(self, args, config):
                return True, ""

        with pytest.raises(ValueError):
            ToolRegistry().register(_NoName())

    def test_planning_phase_only_planning_tools(self):
        reg = self.build()
        cfg = AgentConfig(round_index=0, planning_rounds=3)
        assert [t.name for t in reg.exposed(cfg)] == ["planning_tool"]

    def test_execution_phase_role_filter_and_planning_retired(self):
        reg = self.build()
        cfg = AgentConfig(role="listing", round_index=5, planning_rounds=3)
        names = {t.name for t in reg.exposed(cfg)}
        assert names == {"read_file", "draft_listing"}
        # 客服角色可见订单/退货工具（关掉只读模式，否则写工具按权限元数据隐藏）
        cfg = AgentConfig(role="customer_service", round_index=5, planning_rounds=3,
                          read_only_mode=False)
        names = {t.name for t in reg.exposed(cfg)}
        assert names == {"read_file", "query_order_info", "handle_return"}

    def test_read_only_mode_hides_write_tools(self):
        reg = self.build()
        cfg = AgentConfig(role="customer_service", round_index=5, planning_rounds=0,
                          read_only_mode=True)
        assert "handle_return" not in {t.name for t in reg.exposed(cfg)}
        cfg.read_only_mode = False
        assert "handle_return" in {t.name for t in reg.exposed(cfg)}

    def test_blacklist_disables_tool(self):
        reg = self.build()
        cfg = AgentConfig(role="listing", round_index=5, planning_rounds=0,
                          disabled_tools={"draft_listing"})
        assert "draft_listing" not in {t.name for t in reg.exposed(cfg)}

    def test_planning_rounds_positive_with_complexity(self):
        assert estimate_planning_rounds(0) >= config.TOOL_PLANNING_ROUNDS_BASE
        assert estimate_planning_rounds(3) > estimate_planning_rounds(1)
        assert estimate_planning_rounds(999) == config.TOOL_PLANNING_ROUNDS_BASE + 8

    def test_openai_schemas_match_exposed(self):
        reg = self.build()
        cfg = AgentConfig(role="listing", round_index=5, planning_rounds=0)
        schemas = reg.to_openai_schemas(cfg)
        assert {s["function"]["name"] for s in schemas} == {"read_file", "draft_listing"}

    def test_adapted_business_tool_schema_types(self):
        """既有业务工具（future annotations 字符串注解）类型推导正确：整数/数字/数组。"""
        reg = build_default_registry()
        assert reg.get("recommend_fulfillment").get_schema()["properties"]["stock"]["type"] == "integer"
        assert reg.get("calc_profit").get_schema()["properties"]["sell_price"]["type"] == "number"
        # recommend_products(keywords: list[str]) → array + items: string
        kw = reg.get("recommend_products").get_schema()["properties"]["keywords"]
        assert kw["type"] == "array" and kw["items"] == {"type": "string"}
        # draft_listing 源码注解是裸 list | None，故只推导出 array（无 items）
        assert reg.get("draft_listing").get_schema()["properties"]["keywords"]["type"] == "array"
        assert reg.get("draft_listing").get_schema()["required"] == ["product_name"]
        # read_only 权限元数据：写工具标记为非只读
        assert reg.get("handle_return").read_only is False
        assert reg.get("query_order_info").read_only is True

    def test_default_registry_excludes_internal_helpers(self):
        reg = build_default_registry()
        assert reg.get("lookup_order") is None      # 内部辅助函数不进工具箱
        assert reg.get("register_return") is None
        assert reg.get("check_redline") is None     # 约束层自查工具不进业务工具箱


# ============================================================
# 4) MCP 协议：initialize / tools/list / tools/call
# ============================================================
class TestMCPProtocol:
    @pytest.fixture()
    def server(self):
        return MCPServer(build_default_registry(), name="test-server")

    def test_initialize_handshake(self, server):
        resp = server.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        result = resp["result"]
        assert result["serverInfo"]["name"] == "test-server"
        assert "tools" in result["capabilities"]
        assert result["protocolVersion"] == config.MCP_PROTOCOL_VERSION

    def test_tools_list_entries(self, server):
        resp = server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        tools = resp["result"]["tools"]
        assert tools and all(set(t) >= {"name", "description", "inputSchema"} for t in tools)
        names = {t["name"] for t in tools}
        assert {"planning_tool", "read_file"} <= names

    def test_tools_call_content_status_meta(self, server):
        resp = server.handle({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                              "params": {"name": "read_file",
                                         "arguments": {"path": "config.py", "limit": 2}}})
        result = resp["result"]
        assert result["isError"] is False
        assert result["content"][0]["type"] == "text"
        assert result["_meta"]["status"] == Status.OK
        assert result["_meta"]["tool"] == "read_file"

    def test_tools_call_invalid_args_is_error_to_model(self, server):
        resp = server.handle({"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                              "params": {"name": "read_file", "arguments": {}}})
        result = resp["result"]
        assert result["isError"] is True
        assert result["_meta"]["status"] == Status.INVALID_ARGS
        assert "path" in result["content"][0]["text"]

    def test_unknown_tool_and_method(self, server):
        resp = server.handle({"jsonrpc": "2.0", "id": 5, "method": "tools/call",
                              "params": {"name": "nope", "arguments": {}}})
        assert resp["result"]["isError"] is True
        resp = server.handle({"jsonrpc": "2.0", "id": 6, "method": "no/such", "params": {}})
        assert resp["error"]["code"] == -32601

    def test_bad_jsonrpc_version(self, server):
        resp = server.handle({"id": 7, "method": "ping", "params": {}})
        assert resp["error"]["code"] == -32600

    def test_initialized_notification_returns_none(self, server):
        assert server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None


# ============================================================
# 5) MCP client：重试 / 超时 / 连接管理
# ============================================================
class _FlakyTransport(Transport):
    """可编程故障传输：tools/call 前 N 次抛错，之后成功。"""

    def __init__(self, fail_times: int = 0, exc: Exception | None = None):
        self.fail_times = fail_times
        self.exc = exc or TransportError("连接断开")
        self.call_attempts = 0

    def request(self, method, params, timeout_s, req_id):
        if method == "initialize":
            return {"jsonrpc": "2.0", "id": req_id,
                    "result": {"protocolVersion": "2024-11-05", "capabilities": {},
                               "serverInfo": {"name": "flaky", "version": "0"}}}
        if method == "tools/call":
            self.call_attempts += 1
            if self.fail_times > 0:
                self.fail_times -= 1
                raise self.exc
        return {"jsonrpc": "2.0", "id": req_id,
                "result": {"content": [{"type": "text", "text": "pong"}],
                           "isError": False, "_meta": {"status": "ok"}}}


class TestClientRetryAndTimeout:
    def test_retry_until_success_within_limit(self):
        t = _FlakyTransport(fail_times=4)
        cli = MCPClient(t, max_retries=5)
        res = cli.call_tool("ping", {}, AgentConfig(timeout_s=1))
        assert res.ok and res.text == "pong" and t.call_attempts == 5

    def test_gives_up_after_max_retries(self):
        t = _FlakyTransport(fail_times=99)
        cli = MCPClient(t, max_retries=5)
        res = cli.call_tool("ping", {}, AgentConfig(timeout_s=1))
        assert not res.ok and res.status == Status.TRANSPORT_ERROR
        assert "已重试至上限 5 次退出" in res.text
        assert t.call_attempts == 5  # 含首次共 5 次即退出

    def test_timeout_reported_as_timeout_status(self):
        t = _FlakyTransport(fail_times=99, exc=TimeoutError("超时"))
        cli = MCPClient(t, max_retries=3)
        res = cli.call_tool("ping", {}, AgentConfig(timeout_s=0.01))
        assert not res.ok and res.status == Status.TIMEOUT
        assert t.call_attempts == 3

    def test_protocol_error_not_retried(self):
        class _ErrTransport(Transport):
            def __init__(self):
                self.calls = 0

            def request(self, method, params, timeout_s, req_id):
                if method == "initialize":
                    return {"jsonrpc": "2.0", "id": req_id, "result": {}}
                self.calls += 1
                return {"jsonrpc": "2.0", "id": req_id,
                        "error": {"code": -32602, "message": "bad params"}}

        t = _ErrTransport()
        cli = MCPClient(t, max_retries=5)
        res = cli.call_tool("ping", {}, AgentConfig(timeout_s=1))
        assert not res.ok and res.status == Status.PROTOCOL_ERROR
        assert t.calls == 1  # 业务/协议错误不重试

    def test_initialize_and_list_tools_inprocess(self):
        reg = build_default_registry()
        cli = MCPClient(InProcessTransport(MCPServer(reg)))
        assert cli.initialize()["serverInfo"]["name"]
        tools = cli.list_tools()
        assert any(t["name"] == "read_file" for t in tools)
        assert cli.server_info  # 连接管理：握手信息留痕


# ============================================================
# 6) 全流程异常兜底 + 约束层联动
# ============================================================
class TestCallFlowAndGuard:
    def build(self):
        reg = ToolRegistry()
        reg.register(ReadFileTool())
        reg.register(FunctionTool(lambda order_no: "ok", name="handle_return",
                                  description="退货", read_only=False))
        reg.register(FunctionTool(lambda x: (_ for _ in ()).throw(RuntimeError("内部炸了")),
                                  name="boom_tool", description="必炸", read_only=True))
        return reg

    def test_unregistered_tool_returns_message(self):
        reg = self.build()
        res = reg.call("nope", {}, AgentConfig())
        assert not res.ok and res.status == Status.INVALID_ARGS and "未注册" in res.text

    def test_not_exposed_tool_blocked(self):
        reg = self.build()
        cfg = AgentConfig(round_index=0, planning_rounds=2)  # 阶段一：只开放规划工具
        res = reg.call("read_file", {"path": "config.py"}, cfg)
        assert not res.ok and res.status == Status.NOT_EXPOSED

    def test_param_error_returned_to_model(self):
        reg = self.build()
        cfg = AgentConfig(round_index=5, planning_rounds=0)
        res = reg.call("read_file", {"offset": 1}, cfg)
        assert not res.ok and res.status == Status.INVALID_ARGS and "path" in res.text

    def test_tool_exception_returned_to_model(self):
        reg = self.build()
        cfg = AgentConfig(round_index=5, planning_rounds=0)
        res = reg.call("boom_tool", {"x": "1"}, cfg)
        assert not res.ok and res.status == Status.INTERNAL_ERROR and "内部炸了" in res.text

    def test_non_dict_args_does_not_raise(self):
        reg = self.build()
        res = reg.call("read_file", None, AgentConfig(round_index=5, planning_rounds=0))
        assert isinstance(res.text, str)  # 全流程 try/except：绝不外抛

    def test_constraint_layer_blocks_write_in_plan_mode(self, monkeypatch):
        """约束层联动：plan（只读）模式下写工具被验证层拦截，错误提示返回模型。"""
        monkeypatch.setattr(config, "AGENT_PERMISSION_MODE", "plan")
        reg = self.build()
        cfg = AgentConfig(round_index=5, planning_rounds=0, read_only_mode=False,
                          session_id="toolkit-test")
        res = reg.call("handle_return", {"order_no": "2026081200012"}, cfg)
        assert not res.ok and res.status == Status.BLOCKED and "plan" in res.text

    def test_constraint_layer_allows_read_only(self, monkeypatch):
        monkeypatch.setattr(config, "AGENT_PERMISSION_MODE", "plan")
        reg = self.build()
        cfg = AgentConfig(round_index=5, planning_rounds=0, session_id="toolkit-read")
        res = reg.call("read_file", {"path": "config.py", "limit": 1}, cfg)
        assert res.ok and res.status == Status.OK


# ============================================================
# 7) 内置工具行为 + stdio 独立进程 + LangChain 桥
# ============================================================
class TestBuiltinsAndTransport:
    def test_read_file_paging(self):
        tool = ReadFileTool()
        ok, text = tool.execute({"path": "config.py", "offset": 0, "limit": 3}, AgentConfig())
        assert ok and '"returned": 3' in text and '"total_lines"' in text

    def test_read_file_rejects_outside_root(self):
        tool = ReadFileTool()
        ok, text = tool.execute({"path": "/etc/hosts"}, AgentConfig())
        assert ok is False and "越出允许的根目录" in text

    def test_planning_tool_output(self):
        tool = PlanningTool()
        ok, text = tool.execute({"task": "给耳机写 listing", "steps": ["查竞品", "写五点"]},
                                AgentConfig())
        assert ok and "suggested_planning_rounds" in text

    def test_stdio_independent_server_process(self):
        reg = build_default_registry()
        cli = MCPClient(StdioTransport(), max_retries=2)
        try:
            info = cli.initialize(timeout_s=60)
            assert info["serverInfo"]["name"] == config.MCP_SERVER_NAME
            names = {t["name"] for t in cli.list_tools(timeout_s=60)}
            assert "read_file" in names
            res = cli.call_tool("read_file", {"path": "config.py", "limit": 2},
                                AgentConfig(round_index=5, planning_rounds=0, timeout_s=60))
            assert res.ok and res.status == Status.OK
        finally:
            cli.close()

    def test_langchain_bridge(self):
        reg = build_default_registry()
        cfg = AgentConfig(role="listing", round_index=5, planning_rounds=0)
        tools = to_langchain_tools(reg, cfg)
        assert tools, "bridge 应产出可挂载工具"
        names = {t.name for t in tools}
        assert "draft_listing" in names and "planning_tool" not in names
