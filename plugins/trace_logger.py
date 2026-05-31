"""数据流追踪日志插件（非侵入式）
通过 hook 注册 + monkey-patch 实现全链路数据流打印。
自动加载：agentmain.py 启动时 discover_and_load() 发现此文件即生效。

使用方法：在 agentmain.py L12 的 discover_and_load() 前设置环境变量可开关：
  TRACE_LOGGER=0  → 禁用
  默认开启

每个print统一加 [TRACE] 前缀，便于 grep 过滤。
"""
import os
import json
import sys
import time
import functools
import threading

if os.environ.get('TRACE_LOGGER', '1') == '0':
    # 环境变量禁用，跳过加载
    raise ImportError("TRACE_LOGGER=0, skip")

import plugins.hooks as hooks
import llmcore

# ── 格式化工具 ────────────────────────────────────────────────

_tls = threading.local()
_tls.turn_start_time = 0

def _ts():
    """时间戳：相对当前 turn 的秒数，或绝对时间"""
    start = getattr(_tls, 'abs_start', time.time())
    return f"+{time.time()-start:.1f}s"

def _preview(obj, maxlen=80):
    """截断预览"""
    s = json.dumps(obj, ensure_ascii=False) if not isinstance(obj, str) else obj
    return s[:maxlen] + ('...' if len(s) > maxlen else '')

def _msg_summary(messages):
    """消息列表简要摘要"""
    parts = []
    for m in messages[-5:]:  # 只看最近5条
        role = m['role']
        if m.get('tool_results'):
            parts.append(f"<{role}+{len(m['tool_results'])}tr>")
        else:
            c = m.get('content', '')
            if isinstance(c, str): parts.append(f"<{role}:str({len(c)})>")
            elif isinstance(c, list): parts.append(f"<{role}:{len(c)}blocks>")
    return ', '.join(parts) if parts else '(empty)'

def _content_blocks_detail(content):
    """content blocks 的详细类型描述"""
    if isinstance(content, str):
        return [f"text({len(content)}ch)"]
    types = {}
    for b in content:
        t = b.get('type', '?')
        if t == 'text':
            txt = b.get('text', '')
            types['text'] = types.get('text', 0) + 1
        elif t == 'tool_result':
            types['tool_result'] = types.get('tool_result', 0) + 1
        elif t == 'tool_use':
            types[f"tool_use:{b.get('name','?')}"] = types.get(f"tool_use:{b.get('name','?')}", 0) + 1
        elif t == 'tool_use_block':
            types[t] = types.get(t, 0) + 1
        else:
            types[t] = types.get(t, 0) + 1
    return [f"{k}×{v}" for k, v in types.items()]


# ═══════════════════════════════════════════════════════════════
# Phase 1: Hook 点（覆盖 agent_loop.py 内的流程）
# ═══════════════════════════════════════════════════════════════

@hooks.register('agent_before')
def _trace_agent_before(ctx):
    """【A】任务开始：用户输入到达系统"""
    _tls.abs_start = time.time()
    user_input = ctx.get('user_input', '')
    handler = ctx.get('handler')
    client = ctx.get('client')
    tools = ctx.get('tools_schema', [])
    print(f"\n{'='*60}")
    print(f"[TRACE ⚡A] 任务开始 ({_ts()})")
    print(f"[TRACE ⚡A]   来源句柄: {type(handler).__name__ if handler else 'N/A'}")
    print(f"[TRACE ⚡A]   LLM客户端: {type(client).__name__ if client else 'N/A'}")
    if client and hasattr(client, 'backend'):
        print(f"[TRACE ⚡A]   Backend:   {type(client.backend).__name__}")
    print(f"[TRACE ⚡A]   用户输入:   {_preview(user_input, 120)}")
    print(f"[TRACE ⚡A]   工具数量:   {len(tools)}")
    sp = ctx.get('system_prompt', '')
    print(f"[TRACE ⚡A]   系统提示词: {len(sp)} chars")
    print(f"{'='*60}")


@hooks.register('turn_before')
def _trace_turn_before(ctx):
    """【B】新一轮开始"""
    turn = ctx.get('turn', 0)
    _tls.turn_start_time = time.time()
    msgs = ctx.get('messages', [])
    print(f"\n─── [TRACE 🔄B] Turn {turn} 开始 ({_ts()}) ───")
    print(f"[TRACE 🔄B]   消息总数: {len(msgs)}")
    # 按角色统计
    role_counts = {}
    for m in msgs:
        role_counts[m['role']] = role_counts.get(m['role'], 0) + 1
    print(f"[TRACE 🔄B]   角色分布: {role_counts}")
    # 最后一条消息预览
    if msgs:
        last = msgs[-1]
        c = last.get('content', '')
        detail = _content_blocks_detail(c)
        print(f"[TRACE 🔄B]   末条消息: role={last['role']}, blocks={detail}")
        if last.get('tool_results'):
            print(f"[TRACE 🔄B]   末条含 tool_results: {len(last['tool_results'])} 个")


@hooks.register('llm_before')
def _trace_llm_before(ctx):
    """【C】即将调用 LLM"""
    msgs = ctx.get('messages', [])
    tools = ctx.get('tools_schema', [])
    turn = ctx.get('turn', 0)
    # 计算用户消息总字符数（粗略）
    total_chars = 0
    tool_results_count = 0
    for m in msgs:
        c = m.get('content', '')
        if isinstance(c, str):
            total_chars += len(c)
        elif isinstance(c, list):
            for b in c:
                if b.get('type') == 'text':
                    total_chars += len(b.get('text', ''))
        if m.get('tool_results'):
            tool_results_count += len(m['tool_results'])
    print(f"[TRACE 📤C] Turn {turn} → 调用 LLM ({_ts()})")
    print(f"[TRACE 📤C]   消息总文本: ~{total_chars} chars, tool_results={tool_results_count}")
    print(f"[TRACE 📤C]   工具传参:   {len(tools)} 个工具描述")
    print(f"[TRACE 📤C]   → 即将进入 NativeToolClient.chat()")


@hooks.register('llm_after')
def _trace_llm_after(ctx):
    """【F】LLM 响应已返回"""
    resp = ctx.get('response')
    turn = ctx.get('turn', 0)
    if resp is None:
        print(f"[TRACE 📥F] Turn {turn} ← LLM 响应: (None)")
        return
    thinking = getattr(resp, 'thinking', '') or ''
    content = getattr(resp, 'content', '') or ''
    tool_calls = getattr(resp, 'tool_calls', None) or []
    elapsed = time.time() - _tls.turn_start_time if _tls.turn_start_time else 0
    print(f"[TRACE 📥F] Turn {turn} ← LLM 响应返回 ({_ts()}, LLM耗时={elapsed:.1f}s)")
    print(f"[TRACE 📥F]   thinking:  {len(thinking)} chars{', (含)⚠️' if '⚠️' in thinking else ''}")
    print(f"[TRACE 📥F]   text:      {len(content)} chars")
    if tool_calls:
        for tc in tool_calls:
            name = tc.function.name if hasattr(tc, 'function') else tc.get('name','?')
            args = tc.function.arguments if hasattr(tc, 'function') else tc.get('input',{})
            print(f"[TRACE 📥F]   🛠 tool_call: {name}({_preview(args, 100)})")
    else:
        print(f"[TRACE 📥F]   🛠 tool_calls: (无，本轮为纯文本回复)")


@hooks.register('tool_before')
def _trace_tool_before(ctx):
    """【G】工具开始执行"""
    name = ctx.get('tool_name', '?')
    args = ctx.get('args', {})
    turn = 0
    # 尝试从调用栈获取 turn
    for f in sys._current_frames().values():
        for v in f.f_locals.values():
            if isinstance(v, int) and v < 100:
                pass
    print(f"[TRACE 🎯G] 工具执行 → {name}({_preview(args, 150)}) ({_ts()})")


@hooks.register('tool_after')
def _trace_tool_after(ctx):
    """【H】工具执行完成"""
    ret = ctx.get('ret')
    name = ctx.get('tool_name', '?')
    if ret is None:
        print(f"[TRACE ✅H] 工具完成 → {name}: (无返回值)")
        return
    data = getattr(ret, 'data', '')
    next_p = getattr(ret, 'next_prompt', '')
    should_exit = getattr(ret, 'should_exit', False)
    preview = _preview(data, 100)
    print(f"[TRACE ✅H] 工具完成 → {name} ({_ts()})")
    print(f"[TRACE ✅H]   返回数据:  {preview}")
    print(f"[TRACE ✅H]   下轮提示:  {'有' if next_p else '无'}, 应该退出={should_exit}")


@hooks.register('turn_after')
def _trace_turn_after(ctx):
    """【I】本轮结束，准备下一轮"""
    turn = ctx.get('turn', 0)
    next_prompt = ctx.get('next_prompt', '')
    exit_reason = ctx.get('exit_reason', {})
    tool_results = ctx.get('tool_results', [])
    elapsed = time.time() - _tls.turn_start_time if _tls.turn_start_time else 0
    print(f"[TRACE 🔚I] Turn {turn} 结束 ({_ts()}, 本轮耗时={elapsed:.1f}s)")
    print(f"[TRACE 🔚I]   tool_results: {len(tool_results)} 个")
    print(f"[TRACE 🔚I]   下轮next_prompt: {_preview(next_prompt, 120)}")
    print(f"[TRACE 🔚I]   exit_reason: {exit_reason}")
    if exit_reason.get('stop_reason'):
        print(f"[TRACE 🔚I]   ⛔ 停止原因: {exit_reason['stop_reason']}")
    if tool_results:
        print(f"[TRACE 🔚I]   → 结果将作为 tool_results 进入下一轮消息")
    print(f"{'─'*50}")


@hooks.register('agent_after')
def _trace_agent_after(ctx):
    """【J】整个任务结束"""
    msgs = ctx.get('messages', [])
    total_elapsed = time.time() - _tls.abs_start if hasattr(_tls, 'abs_start') else 0
    print(f"\n{'='*60}")
    print(f"[TRACE 🏁J] 任务结束 ({_ts()}, 总耗时={total_elapsed:.1f}s)")
    print(f"[TRACE 🏁J]   最终消息数: {len(msgs)}")
    role_counts = {}
    for m in msgs:
        role_counts[m['role']] = role_counts.get(m['role'], 0) + 1
    print(f"[TRACE 🏁J]   角色分布:   {role_counts}")
    print(f"{'='*60}\n")


# ═══════════════════════════════════════════════════════════════
# Phase 2: Monkey-patch llmcore 关键函数
# ═══════════════════════════════════════════════════════════════

def _patch_NativeToolClient_chat():
    """【D】NativeToolClient.chat() — 消息内容组装阶段
    此方法将 agent_loop 传来的 messages 拆解、合并 tool_results、
    处理 pending_tool_ids，最终组装成一个 merged 消息发给 session.ask()
    """
    orig = llmcore.NativeToolClient.chat
    if hasattr(orig, '__patched__'): return  # 防重复

    @functools.wraps(orig)
    def chat_wrapper(self, messages, tools=None):
        print(f"\n[TRACE 🔧D] NativeToolClient.chat() 进入 ({_ts()})")
        print(f"[TRACE 🔧D]   输入消息数: {len(messages)}")
        if tools:
            print(f"[TRACE 🔧D]   tools 已设: {len(tools)} 个")
        print(f"[TRACE 🔧D]   pending_tool_ids (from prev): {self._pending_tool_ids}")

        # 统计输入 messages 的内容
        user_count = 0; assistant_count = 0; sys_count = 0
        tr_total = 0
        for msg in messages:
            if msg['role'] == 'user': user_count += 1
            elif msg['role'] == 'assistant': assistant_count += 1
            elif msg['role'] == 'system': sys_count += 1
            if msg.get('tool_results'):
                tr_total += len(msg['tool_results'])
        print(f"[TRACE 🔧D]   user={user_count}, assistant={assistant_count}, system={sys_count}")
        print(f"[TRACE 🔧D]   tool_results 总数: {tr_total}")

        # 执行原方法——用 yield from 透传流式块
        gen = orig(self, messages, tools)
        try:
            while True:
                chunk = next(gen)
                yield chunk
        except StopIteration as e:
            resp = e.value

        # 原方法返回后，记录组装结果
        if hasattr(self, '_pending_tool_ids'):
            print(f"[TRACE 🔧D]   → pending_tool_ids (for next): {self._pending_tool_ids}")

        if resp:
            tc = getattr(resp, 'tool_calls', [])
            print(f"[TRACE 🔧D]   ← 返回: tool_calls={len(tc)}, content_len={len(getattr(resp,'content',''))}")
        else:
            print(f"[TRACE 🔧D]   ← 返回: (None)")

        return resp

    chat_wrapper.__patched__ = True
    llmcore.NativeToolClient.chat = chat_wrapper
    print("[TRACE ✅] NativeToolClient.chat 已 patch")


def _patch_NativeClaudeSession_raw_ask():
    """【E】NativeClaudeSession.raw_ask() — HTTP 请求构建
    在此构建 Claude API 的完整 payload（含 model, messages, tools, system, metadata）
    发出真正的 HTTP POST 请求到 messages API
    """
    orig = llmcore.NativeClaudeSession.raw_ask
    if hasattr(orig, '__patched__'): return

    import functools

    @functools.wraps(orig)
    def raw_ask_wrapper(self, messages):
        print(f"\n[TRACE 🌐E] NativeClaudeSession.raw_ask() 进入 ({_ts()})")
        print(f"[TRACE 🌐E]   model:     {self.model}")
        print(f"[TRACE 🌐E]   stream:    {self.stream}")
        print(f"[TRACE 🌐E]   max_tokens: {self.max_tokens}")
        print(f"[TRACE 🌐E]   输入 messages 数: {len(messages)}")

        # 检查 messages 中各角色的 content block 详情
        for i, m in enumerate(messages):
            role = m['role']
            c = m.get('content', '')
            if isinstance(c, list):
                details = _content_blocks_detail(c)
                print(f"[TRACE 🌐E]   msg[{i}] role={role}: {len(c)} blocks → {details}")
            elif isinstance(c, str):
                print(f"[TRACE 🌐E]   msg[{i}] role={role}: str({len(c)} chars)")

        # 执行原方法——yield from 透传
        gen = orig(self, messages)
        try:
            while True:
                chunk = next(gen)
                yield chunk
        except StopIteration as e:
            result = e.value

        # 记录 payload 关键信息（self.tools 已在 chat() 中设置）
        tools = getattr(self, 'tools', [])
        if tools:
            tool_names = []
            for t in tools:
                fn = t.get('function', {})
                tool_names.append(fn.get('name', t.get('name', '?')))
            print(f"[TRACE 🌐E]   self.tools:  {len(tools)} 个 → {tool_names[:6]}...")
        else:
            print(f"[TRACE 🌐E]   self.tools:  (无)")
        # system prompt 处理方式
        print(f"[TRACE 🌐E]   fake_cc_system_prompt: {getattr(self, 'fake_cc_system_prompt', False)}")
        sys_len = len(self.system) if hasattr(self, 'system') and self.system else 0
        print(f"[TRACE 🌐E]   system len:  {sys_len} chars")

        print(f"[TRACE 🌐E]   ← 响应已收到，返回 MockResponse")
        return result

    raw_ask_wrapper.__patched__ = True
    llmcore.NativeClaudeSession.raw_ask = raw_ask_wrapper
    print("[TRACE ✅] NativeClaudeSession.raw_ask 已 patch")


def _patch_parse_claude_sse():
    """【E2】_parse_claude_sse() — SSE 流实时解析
    解析 Claude API 返回的 SSE 事件流，识别 text delta、content_block_start/stop、
    tool_use、message_delta 等事件类型
    """
    orig = llmcore._parse_claude_sse
    if hasattr(orig, '__patched__'): return

    @functools.wraps(orig)
    def parse_wrapper(resp_lines, *a, **kw):
        print(f"[TRACE 📡E2] _parse_claude_sse() 开始解析 SSE 流 ({_ts()})")

        # 用 tee 方式同时录入日志和传递数据
        tee_lines = []
        total_chunks = 0
        tool_use_started = False
        tool_use_name = ""
        parse_start = time.time()

        def tee():
            nonlocal total_chunks, tool_use_started, tool_use_name
            for line in resp_lines:
                tee_lines.append(line)
                s = line.decode('utf-8', 'replace') if isinstance(line, (bytes, bytearray)) else line
                if not s: continue

                # 识别 SSE 事件类型（精简打印，避免刷屏）
                total_chunks += 1
                if 'content_block_start' in s:
                    try:
                        # 快速解析 event 中的 type
                        import re as _re
                        m = _re.search(r'"type"\s*:\s*"(\w+)"', s.split('\n', 1)[1] if '\n' in s else s)
                        if m:
                            block_type = m.group(1)
                            if block_type == 'tool_use':
                                nm = _re.search(r'"name"\s*:\s*"(\w+)"', s)
                                tool_use_name = nm.group(1) if nm else '?'
                                tool_use_started = True
                                print(f"[TRACE 📡E2]   ▶️ tool_use 开始: name={tool_use_name} ({_ts()})")
                            else:
                                print(f"[TRACE 📡E2]   ▶️ content_block_start: type={block_type}")
                    except Exception:
                        pass
                elif 'content_block_stop' in s:
                    if tool_use_started:
                        print(f"[TRACE 📡E2]   ⏹️ tool_use 结束: {tool_use_name} ({_ts()})")
                        tool_use_started = False
                        tool_use_name = ""
                    else:
                        print(f"[TRACE 📡E2]   ⏹️ content_block_stop")
                elif 'message_delta' in s:
                    import re as _re2
                    stop = _re2.search(r'"stop_reason"\s*:\s*"(\w+)"', s)
                    usage = _re2.search(r'"output_tokens"\s*:\s*(\d+)', s)
                    stop_str = f", stop_reason={stop.group(1)}" if stop else ""
                    tok_str = f", output_tokens={usage.group(1)}" if usage else ""
                    print(f"[TRACE 📡E2]   ℹ️ message_delta{stop_str}{tok_str} ({_ts()})")
                elif total_chunks % 200 == 0:
                    # 每200行打个心跳，避免长时间无输出
                    print(f"[TRACE 📡E2]   解析中... 已处理 {total_chunks} 行 ({_ts()})")

                yield line

        result = yield from orig(tee(), *a, **kw)
        elapsed = time.time() - parse_start
        print(f"[TRACE 📡E2]   解析完成: {total_chunks} 行, {elapsed:.1f}s ({_ts()})")
        print(f"[TRACE 📡E2]   ← content_blocks={len(result)}")
        return result

    parse_wrapper.__patched__ = True
    llmcore._parse_claude_sse = parse_wrapper
    print("[TRACE ✅] _parse_claude_sse 已 patch")


def _patch_ask_method():
    """【E1】NativeClaudeSession.ask() — 历史管理 + raw_ask 调用
    在调用 raw_ask 前将消息追加到 session.history 并裁剪
    """
    orig = llmcore.NativeClaudeSession.ask
    if hasattr(orig, '__patched__'): return

    @functools.wraps(orig)
    def ask_wrapper(self, msg):
        print(f"[TRACE 📋E1] NativeClaudeSession.ask() 进入 ({_ts()})")
        content_detail = _content_blocks_detail(msg.get('content', []))
        print(f"[TRACE 📋E1]   消息内容: blocks={content_detail}")
        print(f"[TRACE 📋E1]   当前 history 长度: {len(self.history)}")

        result = orig(self, msg)

        print(f"[TRACE 📋E1]   ← 返回, history 长度: {len(self.history)}")
        return result

    ask_wrapper.__patched__ = True
    llmcore.NativeClaudeSession.ask = ask_wrapper
    print("[TRACE ✅] NativeClaudeSession.ask 已 patch")


# ═══════════════════════════════════════════════════════════════
# 在模块导入时自动生效
# ═══════════════════════════════════════════════════════════════

print("[TRACE] 🔍 数据流追踪插件已加载，路径覆盖：A→B→C→D→E1→E→E2→F→G→H→I→J")
_patch_NativeToolClient_chat()
_patch_NativeClaudeSession_raw_ask()
_patch_parse_claude_sse()
_patch_ask_method()
