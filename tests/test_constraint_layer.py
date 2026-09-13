# -*- coding: utf-8 -*-
"""约束层（core/constraint/）单元测试：验证层四道检查 + hook / 循环守卫 / 预算熔断 / 门面。

覆盖用户规范要点：
- 权限四档（plan 只读 / ask 待确认 / accept 低风险放行 / bypass 全放开），默认 plan；
- 主路径：权限 → 路径（防越权文件操作）→ 网络策略 → 危险内容/模式（rm -rf、curl 等）；
- hook 规则：允许 pytest、禁止 pip install（deny 优先，首条命中生效）；
- 循环守卫：总调用量 / 连续失败 / 完全相同调用（MD5 前 12 位 + 结果前 20 字符）/ [A,B]×3 交替；
- 预算熔断：五段分配（15/10/5/20/50）+ token/金额记账熔断 + 上下文封顶截断；
- 门面：L9 跳过、会话线程变量回落、软干预以 system-reminder 返回。
"""
from __future__ import annotations

import pytest

import config
from core.constraint import (
    BudgetGuard,
    ConstraintLayer,
    ToolLoopGuard,
    ToolValidator,
    get_constraint_layer,
    set_current_session,
)
from memory.access import MemoryCaller


def _caller(session_id: str = "", level: str = "L1") -> MemoryCaller:
    return MemoryCaller("tester", level, session_id=session_id)


# ============================================================
# 1) 验证层·权限四档
# ============================================================
class TestValidatorPermission:
    def test_plan_blocks_write_tool(self, monkeypatch):
        monkeypatch.setattr(config, "AGENT_PERMISSION_MODE", "plan")
        v = ToolValidator().check("write_file", {"path": "out.txt"})
        assert not v.allowed and v.kind == "permission" and "plan" in v.message

    def test_plan_allows_read_tool(self, monkeypatch):
        monkeypatch.setattr(config, "AGENT_PERMISSION_MODE", "plan")
        v = ToolValidator().check("read_file", {"path": "config.py"})
        assert v.allowed

    def test_ask_blocks_write_with_confirm_hint(self, monkeypatch):
        monkeypatch.setattr(config, "AGENT_PERMISSION_MODE", "ask")
        v = ToolValidator().check("write_file", {})
        assert not v.allowed and v.kind == "permission" and "ask" in v.message

    def test_accept_lets_low_risk_write_through(self, monkeypatch):
        monkeypatch.setattr(config, "AGENT_PERMISSION_MODE", "accept")
        v = ToolValidator().check("write_file", {"path": "out.txt"})
        assert v.allowed

    def test_bypass_skips_every_check(self, monkeypatch):
        monkeypatch.setattr(config, "AGENT_PERMISSION_MODE", "bypass")
        v = ToolValidator().check("write_file", {"cmd": "rm -rf /"})
        assert v.allowed

    def test_explicit_write_tool_list_is_respected(self, monkeypatch):
        monkeypatch.setattr(config, "AGENT_PERMISSION_MODE", "plan")
        assert "handle_return" in config.TOOL_WRITE_TOOLS
        v = ToolValidator().check("handle_return", {"order_no": "1"})
        assert not v.allowed and v.kind == "permission"

    def test_write_name_pattern_fallback(self, monkeypatch):
        monkeypatch.setattr(config, "AGENT_PERMISSION_MODE", "plan")
        for name in ("edit_file", "delete_all", "run_bash", "install_pkg"):
            assert not ToolValidator().check(name, {}).allowed


# ============================================================
# 2) 验证层·hook 规则
# ============================================================
class TestValidatorHooks:
    def test_pip_install_denied(self):
        v = ToolValidator().check("run_shell", {"cmd": "pip install numpy"})
        assert not v.allowed and v.kind == "hook" and "pip install" in v.message

    def test_pytest_allowed_and_short_circuits_permission(self, monkeypatch):
        # run_shell 命中写类命名，但 allow hook 先生效 → 放行并跳过后续检查
        monkeypatch.setattr(config, "AGENT_PERMISSION_MODE", "plan")
        v = ToolValidator().check("run_shell", {"cmd": "python3 -m pytest tests/"})
        assert v.allowed and v.kind == "ok"

    def test_deny_hook_wins_over_allow_hook(self):
        # "pip install pytest" 同时含两条规则，deny 排在前面 → 拒绝
        v = ToolValidator().check("run_shell", {"cmd": "pip install pytest"})
        assert not v.allowed and v.kind == "hook"

    def test_constraint_self_check_tool_not_false_positive(self):
        # 约束层自查工具的参数是被检文本，可能含危险串，必须放行
        v = ToolValidator().check("check_redline", {"text": "rm -rf /"})
        assert v.allowed


# ============================================================
# 3) 验证层·文件路径检查
# ============================================================
class TestValidatorPaths:
    def test_traversal_denied(self):
        v = ToolValidator().check("read_file", {"path": "../../etc/passwd"})
        assert not v.allowed and v.kind == "path" and "穿越" in v.message

    def test_absolute_outside_root_denied(self):
        v = ToolValidator().check("read_file", {"path": "/etc/hosts"})
        assert not v.allowed and v.kind == "path" and "越出" in v.message

    def test_home_dir_denied(self):
        v = ToolValidator().check("read_file", {"path": "~/secret.txt"})
        assert not v.allowed and v.kind == "path"

    def test_sensitive_bare_filename_denied(self):
        # 裸文件名（无分隔符）也必须命中敏感文件检查
        v = ToolValidator().check("read_file", {"path": ".env"})
        assert not v.allowed and v.kind == "path" and "敏感" in v.message

    def test_sensitive_git_dir_denied(self):
        v = ToolValidator().check("read_file", {"path": ".git/config"})
        assert not v.allowed and v.kind == "path"

    def test_relative_inside_root_allowed(self):
        assert ToolValidator().check("read_file", {"path": "config.py"}).allowed

    def test_absolute_inside_root_allowed(self):
        assert ToolValidator().check("read_file", {"path": str(config.BASE_DIR / "config.py")}).allowed

    def test_path_key_without_separator_not_flagged(self):
        assert ToolValidator().check("read_file", {"path": "notes.txt"}).allowed


# ============================================================
# 4) 验证层·网络访问策略
# ============================================================
class TestValidatorNetwork:
    def test_metadata_endpoint_always_denied(self):
        v = ToolValidator().check("http_get", {"url": "http://169.254.169.254/latest/meta-data"})
        assert not v.allowed and v.kind == "network" and "元数据" in v.message

    def test_policy_deny_blocks_all(self, monkeypatch):
        monkeypatch.setattr(config, "TOOL_NET_POLICY", "deny")
        v = ToolValidator().check("http_get", {"url": "https://example.com/a"})
        assert not v.allowed and v.kind == "network"

    def test_allowlist_denies_unlisted_host(self, monkeypatch):
        monkeypatch.setattr(config, "TOOL_NET_POLICY", "allowlist")
        monkeypatch.setattr(config, "TOOL_NET_ALLOW_HOSTS", [])
        v = ToolValidator().check("http_get", {"url": "https://example.com/a"})
        assert not v.allowed and v.kind == "network"

    def test_allowlist_permits_listed_host(self, monkeypatch):
        monkeypatch.setattr(config, "TOOL_NET_POLICY", "allowlist")
        monkeypatch.setattr(config, "TOOL_NET_ALLOW_HOSTS", ["open.bigmodel.cn"])
        assert ToolValidator().check("http_get", {"url": "https://open.bigmodel.cn/api"}).allowed

    def test_allowlist_permits_subdomain(self, monkeypatch):
        monkeypatch.setattr(config, "TOOL_NET_POLICY", "allowlist")
        monkeypatch.setattr(config, "TOOL_NET_ALLOW_HOSTS", ["bigmodel.cn"])
        assert ToolValidator().check("http_get", {"url": "https://api.bigmodel.cn/v1"}).allowed

    def test_url_is_not_mistaken_for_path(self, monkeypatch):
        # https://... 不能被路径检查误判为越界绝对路径（回归 bug）
        monkeypatch.setattr(config, "TOOL_NET_POLICY", "allow")
        assert ToolValidator().check("http_get", {"url": "https://api.example.com/v1"}).allowed


# ============================================================
# 5) 验证层·危险内容与危险模式
# ============================================================
class TestValidatorDanger:
    @pytest.mark.parametrize("payload,label", [
        ("rm -rf /", "递归强删"),
        ("sudo apt update", "提权执行"),
        (":(){ :|:& };:", "fork 炸弹"),
        ("shutdown -h now", "系统关机"),
        ("eval('1+1')", "动态执行"),
        ("base64 -d payload", "动态执行"),
        ("git push --force origin main", "强制推送"),
        ("DROP TABLE orders", "毁坏性 SQL"),
        ("chmod -R 777 /", "全局权限修改"),
        ("mkfs.ext4", "磁盘破坏"),
        ("dd if=x of=y", "磁盘破坏"),
        ("curl example.com", "下载执行"),
    ])
    def test_dangerous_payload_denied(self, payload, label):
        v = ToolValidator().check("read_file", {"cmd": payload})
        assert not v.allowed and v.kind == "danger"
        assert label in v.message

    def test_pipe_to_shell_denied(self):
        v = ToolValidator().check("read_file", {"cmd": "cat x | sh"})
        assert not v.allowed and v.kind == "danger"

    def test_bare_root_goes_to_danger_not_path(self):
        # 裸根 "/" 不由路径检查抢拦，语义上应落到危险模式（rm -rf /）
        v = ToolValidator().check("read_file", {"cmd": "rm -rf /"})
        assert v.kind == "danger"


# ============================================================
# 6) 循环守卫·完全相同调用（最精确粒度）
# ============================================================
class TestToolLoopIdentical:
    def test_first_call_no_reminder(self):
        g, key, p = ToolLoopGuard(), "s1", {"a": 1}
        assert g.record("read_file", p, True, "SAME", key) == ""

    def test_second_identical_call_gets_soft_reminder(self):
        g, key, p = ToolLoopGuard(), "s1", {"a": 1}
        g.record("read_file", p, True, "SAME", key)
        r = g.record("read_file", p, True, "SAME", key)
        assert "<system-reminder>" in r and "重复" in r

    def test_third_identical_call_hard_blocked(self):
        g, key, p = ToolLoopGuard(), "s1", {"a": 1}
        for _ in range(2):
            g.record("read_file", p, True, "SAME", key)
        blocked, msg = g.check("read_file", p, key)
        assert blocked and "第 3 次" in msg

    def test_same_params_different_result_no_soft_but_hard_block(self):
        g, key, p = ToolLoopGuard(), "s1", {"a": 1}
        g.record("read_file", p, True, "AAA", key)
        r = g.record("read_file", p, True, "BBB", key)
        assert r == ""                                   # 结果不同 → 不软提醒
        blocked, _ = g.check("read_file", p, key)
        assert blocked                                   # 同参数第 3 次仍硬拦

    def test_signature_uses_md5_prefix_and_result_prefix(self):
        g, key = ToolLoopGuard(), "s1"
        g.record("t", {"x": 1}, True, "R" * 50, key)
        st = g.session_status(key)
        assert st["window_size"] == 1


# ============================================================
# 7) 循环守卫·[A,B]×3 交替检测
# ============================================================
class TestToolLoopAlternating:
    def test_alternating_pair_triggers_once(self):
        g, key = ToolLoopGuard(), "alt"
        reminders = 0
        for i, name in enumerate(["read_file", "edit_file"] * 3):
            r = g.record(name, {"i": i}, True, "r", key)
            reminders += 1 if "<system-reminder>" in r else 0
        assert reminders == 1

    def test_alternating_reminder_is_single_shot(self):
        g, key = ToolLoopGuard(), "alt"
        for i, name in enumerate(["read_file", "edit_file"] * 3):
            g.record(name, {"i": i}, True, "r", key)
        r = g.record("read_file", {"i": 99}, True, "r", key)   # 仍在交替
        assert "<system-reminder>" not in r                    # 已提醒过，不重复

    def test_five_calls_not_enough(self):
        g, key = ToolLoopGuard(), "alt"
        reminders = 0
        for i, name in enumerate(["read_file", "edit_file"] * 3):
            if i >= 5:
                break
            r = g.record(name, {"i": i}, True, "r", key)
            reminders += 1 if "<system-reminder>" in r else 0
        assert reminders == 0


# ============================================================
# 8) 循环守卫·熔断（总量 / 连败 / 会话隔离 / 复位）
# ============================================================
class TestToolLoopFuse:
    def test_total_calls_fuse(self, monkeypatch):
        monkeypatch.setattr(config, "TOOL_LOOP_MAX_CALLS", 3)
        g, key = ToolLoopGuard(), "fuse"
        for i in range(3):
            g.record("t", {"i": i}, True, "r", key)
        blocked, msg = g.check("t", {"i": 9}, key)
        assert blocked and "上限" in msg

    def test_consecutive_failures_fuse_message(self, monkeypatch):
        monkeypatch.setattr(config, "TOOL_LOOP_MAX_CONSEC_FAILS", 3)
        g, key = ToolLoopGuard(), "fuse"
        for i in range(3):
            g.record("t", {"i": i}, False, "err", key)
        blocked, msg = g.check("t", {"i": 9}, key)
        assert blocked and "连续失败" in msg      # 熔断原因话术不能串台

    def test_success_resets_failure_counter(self):
        g, key = ToolLoopGuard(), "fuse"
        g.record("t", {"i": 1}, False, "err", key)
        g.record("t", {"i": 2}, True, "ok", key)
        assert g.session_status(key)["consecutive_failures"] == 0

    def test_session_isolation(self):
        g = ToolLoopGuard()
        g.record("t", {"a": 1}, True, "r", "s1")
        assert g.session_status("s1")["tool_calls"] == 1
        assert g.session_status("s2")["tool_calls"] == 0

    def test_reset_clears_state(self):
        g, key = ToolLoopGuard(), "fuse"
        g.record("t", {"a": 1}, True, "r", key)
        g.reset(key)
        assert g.session_status(key)["tool_calls"] == 0


# ============================================================
# 9) 预算熔断
# ============================================================
class TestBudgetAllocation:
    def test_five_segments_sum_to_100(self):
        pct = [config.BUDGET_PCT_OUTPUT, config.BUDGET_PCT_SYSTEM, config.BUDGET_PCT_LONG_TERM,
               config.BUDGET_PCT_TASK, config.BUDGET_PCT_HISTORY]
        assert sum(pct) == 100
        assert pct == [15, 10, 5, 20, 50]

    def test_allocation_values(self, monkeypatch):
        monkeypatch.setattr(config, "CONTEXT_TOKEN_GUARD", 1000)
        a = BudgetGuard.allocation()
        assert a == {"output": 150, "system": 100, "long_term": 50, "task": 200, "history": 500}

    def test_allocation_accepts_explicit_total(self):
        a = BudgetGuard.allocation(2000)
        assert sum(a.values()) == 2000


class TestBudgetFuse:
    def test_token_budget_fuse(self, monkeypatch):
        monkeypatch.setattr(config, "SESSION_TOKEN_BUDGET", 100)
        b = BudgetGuard()
        b.record("s", 80, 30)
        assert b.is_over("s") and "110" in b.over_reply("s")

    def test_cost_budget_fuse(self, monkeypatch):
        monkeypatch.setattr(config, "SESSION_TOKEN_BUDGET", 10 ** 9)
        monkeypatch.setattr(config, "SESSION_COST_BUDGET_CNY", 1.0)
        monkeypatch.setattr(config, "PRICE_INPUT_CNY_PER_M", 1_000_000.0)
        b = BudgetGuard()
        b.record("s", 2, 0)
        assert b.status("s")["cost"] == 2.0 and b.is_over("s")

    def test_cost_fuse_disabled_by_default(self, monkeypatch):
        monkeypatch.setattr(config, "SESSION_TOKEN_BUDGET", 10 ** 9)
        monkeypatch.setattr(config, "SESSION_COST_BUDGET_CNY", 0)
        monkeypatch.setattr(config, "PRICE_INPUT_CNY_PER_M", 1_000_000.0)
        b = BudgetGuard()
        b.record("s", 2, 0)
        assert b.status("s")["cost"] > 0 and not b.is_over("s")

    def test_status_and_reset(self, monkeypatch):
        monkeypatch.setattr(config, "SESSION_TOKEN_BUDGET", 10 ** 9)
        b = BudgetGuard()
        b.record("s", 10, 5)
        st = b.status("s")
        assert st["tokens"] == 15 and st["llm_calls"] == 1
        b.reset("s")
        assert b.status("s")["tokens"] == 0


class TestBudgetTrim:
    def test_over_limit_block_trimmed_with_marker(self, monkeypatch):
        monkeypatch.setattr(config, "CONTEXT_TOKEN_GUARD", 1000)   # system 100 / facts 30
        blocks = BudgetGuard().trim_context_blocks({"rules": "短", "facts": "长" * 200})
        assert blocks["rules"] == "短"                              # 未超限不动
        assert "预算封顶截断" in blocks["facts"] and len(blocks["facts"]) < 200

    def test_under_limit_untouched(self, monkeypatch):
        monkeypatch.setattr(config, "CONTEXT_TOKEN_GUARD", 1000)
        blocks = BudgetGuard().trim_context_blocks({"hot_skills": "短技能", "kb_index": "短索引"})
        assert blocks["hot_skills"] == "短技能" and blocks["kb_index"] == "短索引"

    def test_long_term_split_between_facts_and_hot_skills(self, monkeypatch):
        monkeypatch.setattr(config, "CONTEXT_TOKEN_GUARD", 1000)   # long_term 50 → facts 30 / hot 20
        blocks = BudgetGuard().trim_context_blocks({"facts": "长" * 100, "hot_skills": "技" * 100})
        assert "预算封顶截断" in blocks["facts"] and "预算封顶截断" in blocks["hot_skills"]

    def test_single_line_over_cap_is_hard_cut(self, monkeypatch):
        monkeypatch.setattr(config, "CONTEXT_TOKEN_GUARD", 100)
        blocks = BudgetGuard().trim_context_blocks({"facts": "长" * 100})   # facts cap = 3
        assert "预算封顶截断" in blocks["facts"] and len(blocks["facts"]) < 20


# ============================================================
# 10) 门面（ConstraintLayer）整合
# ============================================================
class TestConstraintLayerFacade:
    def test_plan_mode_blocks_write_via_facade(self, monkeypatch):
        monkeypatch.setattr(config, "AGENT_PERMISSION_MODE", "plan")
        v = ConstraintLayer().check_tool_call("handle_return", {"order_no": "1"}, _caller("f1"))
        assert not v.allowed and v.kind == "permission"

    def test_l9_system_caller_skips_check_and_accounting(self):
        layer = ConstraintLayer()
        L9 = MemoryCaller("system", "L9", session_id="l9")
        assert layer.check_tool_call("handle_return", {}, L9).allowed
        assert layer.record_tool_result("handle_return", {}, True, "ok", L9) == ""
        assert layer.tool_loop.session_status("l9")["tool_calls"] == 0

    def test_soft_reminder_returned_by_record(self):
        layer, key = ConstraintLayer(), "facade-dup"
        c = _caller(key)
        p = {"a": 1}
        layer.record_tool_result("read_file", p, True, "SAME", c)
        r = layer.record_tool_result("read_file", p, True, "SAME", c)
        assert "<system-reminder>" in r

    def test_loop_key_falls_back_to_thread_session(self):
        layer = ConstraintLayer()
        set_current_session("th-1")
        try:
            layer.record_tool_result("ping", {"a": 1}, True, "ok", _caller(""))
            assert layer.tool_loop.session_status("th-1")["tool_calls"] == 1
            layer.record_tool_result("ping", {"a": 2}, True, "ok", _caller("scoped"))
            assert layer.tool_loop.session_status("scoped")["tool_calls"] == 1
            assert layer.tool_loop.session_status("th-1")["tool_calls"] == 1
        finally:
            set_current_session("")

    def test_llm_blocked_tracks_budget(self, monkeypatch):
        monkeypatch.setattr(config, "SESSION_TOKEN_BUDGET", 50)
        layer = ConstraintLayer()
        assert layer.llm_blocked("s") is False
        layer.record_llm_usage("s", 40, 30)
        assert layer.llm_blocked("s") is True
        assert layer.blocked_reply("s")

    def test_session_snapshot_keys(self):
        snap = ConstraintLayer().session_snapshot("s")
        assert set(snap) == {"framework", "loop", "tool_loop", "budget", "permission_mode"}

    def test_reset_clears_guards(self):
        layer = ConstraintLayer()
        layer.record_tool_result("t", {"a": 1}, True, "r", _caller("rst"))
        layer.record_llm_usage("rst", 10, 10)
        layer.reset("rst")
        assert layer.tool_loop.session_status("rst")["tool_calls"] == 0
        assert layer.budget.status("rst")["tokens"] == 0

    def test_singleton_identity(self):
        assert get_constraint_layer() is get_constraint_layer()

    def test_旁路容错_never_raises(self, monkeypatch):
        # 约束层内部故障时必须放行，而不是阻断主链路
        layer = ConstraintLayer()

        class _Boom:
            def check(self, *a, **k):
                raise RuntimeError("boom")

        monkeypatch.setattr(layer, "validator", _Boom())
        assert layer.check_tool_call("read_file", {"path": "x"}, _caller("e")).allowed
