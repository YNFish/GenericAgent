"""
Compound Engineering Plugin for GenericAgent
=============================================
Integrates https://github.com/EveryInc/compound-engineering-plugin skills
into AG via the hooks system.

Auto-loaded by plugins.hooks.discover_and_load() at agent startup.

Key features:
  - 39+ compound engineering skills as discoverable references
  - Intent→skill matching: suggest_skills(query) returns relevant skills
  - Skill index injected into agent context at startup
  - Dynamic skill loading via file read
"""

import os
import sys
import re
import threading

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SKILLS_DIR = os.path.join(_PROJECT_ROOT, 'plugins', 'compound-engineering',
                           'plugins', 'compound-engineering', 'skills')

_skills_cache = None
_cache_lock = threading.Lock()

# ── Intent-to-Skill Keyword Map ──────────────────────────
# Each skill has trigger keywords for fuzzy matching
_INTENT_MAP = {
    'ce-strategy': [
        'strategy', 'strategic', 'product strategy', 'roadmap', 'vision',
        '方向', '战略', '路线图', '产品规划', '产品策略', '产品战略',
    ],
    'ce-ideate': [
        'ideate', 'ideation', 'brainstorm ideas', 'generate ideas',
        '创意', '头脑风暴', '想法', '构思',
    ],
    'ce-brainstorm': [
        'brainstorm', 'requirements', 'prd', 'feature request', 'scope',
        '需求', '讨论', '功能需求', '需求文档', 'prd', '产品需求',
        '头脑风暴', '需求分析',
    ],
    'ce-plan': [
        'plan', 'implementation plan', 'technical design', 'architecture',
        '计划', '实现计划', '技术设计', '架构设计', '技术方案',
        '设计方案', '设计文档', '详细设计',
        '设计', '数据库设计', '系统设计',
    ],
    'ce-work': [
        'implement', 'build', 'develop', 'code', 'write code', 'execute',
        '实现', '开发', '编码', '写代码', '执行',
        '做一个', '写一个', '创建一个', '开发一个', '建一个', '搞一个',
        '编程', '写程序', '编写', '构建', '搭建',
        '实现一个', '实现功能',
        '写个', '做个', '搞个', '建个', '搭个', '开发个', '创建个',
    ],
    'ce-code-review': [
        'code review', 'review code', 'pull request review', 'pr review',
        '代码审查', '审查代码', 'code review', 'pr审查',
        'review代码', '代码review', '审查代码',
        'review', '审代码', '阅代码',
    ],
    'ce-debug': [
        'debug', 'fix bug', 'bug fix', 'root cause', 'error', 'issue',
        '调试', '修bug', '修复bug', '错误', '根因',
        'bug', '找bug', '排查', '问题排查',
    ],
    'ce-report-bug': [
        'report bug', 'bug report', 'issue report', 'bug template',
        '报告bug', 'bug报告', '提交issue',
    ],
    'ce-compound': [
        'compound', 'document', 'knowledge', 'learnings', 'postmortem',
        '沉淀', '文档', '知识', '经验', '总结', '记录经验',
    ],
    'ce-compound-refresh': [
        'refresh docs', 'update docs', 'stale docs', 'documentation refresh',
        '更新文档', '刷新文档', '过时文档',
    ],
    'ce-doc-review': [
        'doc review', 'documentation review', 'review docs',
        '文档审查', '审查文档', '文档review',
    ],
    'ce-simplify-code': [
        'simplify', 'refactor', 'clean code', 'reduce complexity',
        '简化', '重构', '代码简化', '降低复杂度', '简化代码',
        '代码重构',
    ],
    'ce-polish': [
        'polish', 'ui polish', 'frontend polish', 'refine ui',
        '打磨', 'ui打磨', '前端打磨', '优化界面',
    ],
    'ce-proof': [
        'proof', 'proofread', 'typo', 'spelling', 'grammar',
        '校对', '拼写', '语法', '错别字',
    ],
    'ce-optimize': [
        'optimize', 'performance', 'speed up', 'bottleneck', 'profiling',
        '优化', '性能', '加速', '瓶颈', '性能分析',
        '性能优化', '慢', '卡顿',
    ],
    'ce-frontend-design': [
        'frontend design', 'ui design', 'component design', 'react component',
        '前端设计', 'ui设计', '组件设计', 'react组件',
        '前端', '界面设计',
    ],
    'ce-product-pulse': [
        'product pulse', 'week in review', 'sprint review', 'product metrics',
        '产品脉搏', '周报', 'sprint回顾', '产品指标',
    ],
    'ce-worktree': [
        'worktree', 'git worktree', 'parallel branch', 'isolated branch',
        'git worktree', '并行分支', '隔离分支',
    ],
    'ce-clean-gone-branches': [
        'clean branches', 'delete branches', 'prune branches', 'gone branches',
        '清理分支', '删除分支', '清理远程分支',
    ],
    'ce-commit': [
        'commit', 'git commit', 'write commit message',
        '提交', 'git提交', '提交信息', 'commit信息',
    ],
    'ce-commit-push-pr': [
        'commit push', 'push pr', 'create pr', 'pull request', 'open pr',
        '提交推送', '创建pr', '拉取请求', '开pr', '提pr',
        '合并请求',
    ],
    'lfg': [
        'full pipeline', 'full workflow', 'end to end', 'auto pipeline',
        '完整流程', '全流程', '端到端', '自动化流程',
    ],
}

# ── Category Info ────────────────────────────────────────
_CATEGORIES = {
    'planning': ['ce-strategy', 'ce-ideate', 'ce-brainstorm', 'ce-plan'],
    'execution': ['ce-work', 'ce-worktree', 'ce-clean-gone-branches'],
    'quality': ['ce-code-review', 'ce-simplify-code', 'ce-polish', 'ce-proof', 'ce-optimize', 'ce-frontend-design'],
    'debugging': ['ce-debug', 'ce-report-bug'],
    'documentation': ['ce-compound', 'ce-compound-refresh', 'ce-doc-review'],
    'git': ['ce-commit', 'ce-commit-push-pr', 'ce-worktree', 'ce-clean-gone-branches'],
    'product': ['ce-product-pulse', 'ce-strategy', 'ce-ideate'],
}

# Category descriptions for suggestions
_CATEGORY_DESC = {
    'planning': '📋 规划 (策略/创意/头脑风暴/计划)',
    'execution': '🔧 执行 (开发/工作树/清理分支)',
    'quality': '✨ 质量 (审查/简化/打磨/校对/优化/前端设计)',
    'debugging': '🐛 调试 (调试/报bug)',
    'documentation': '📝 文档 (知识沉淀/刷新/审查)',
    'git': '🔗 Git (提交/推送PR/工作树/清理分支)',
    'product': '📊 产品 (产品脉搏/战略/创意)',
}


# ── Skill Index Builder ─────────────────────────────────


def _build_skills_index():
    """Parse all SKILL.md files and return a structured index."""
    global _skills_cache
    with _cache_lock:
        if _skills_cache is not None:
            return _skills_cache

        index = []
        if not os.path.isdir(_SKILLS_DIR):
            _skills_cache = []
            return _skills_cache

        for skill_name in sorted(os.listdir(_SKILLS_DIR)):
            skill_path = os.path.join(_SKILLS_DIR, skill_name)
            if not os.path.isdir(skill_path):
                continue
            skill_md = os.path.join(skill_path, 'SKILL.md')
            if not os.path.exists(skill_md):
                continue

            with open(skill_md, 'r', encoding='utf-8') as f:
                content = f.read()

            name = skill_name
            description = ''
            hint = ''

            fm_match = re.match(r'^---\s*\n(.*?)\n---', content, re.DOTALL)
            if fm_match:
                fm_text = fm_match.group(1)
                n = re.search(r'^name:\s*(.+)$', fm_text, re.MULTILINE)
                d = re.search(r'^description:\s*(.+?)$', fm_text, re.MULTILINE)
                a = re.search(r'^argument-hint:\s*(.+?)$', fm_text, re.MULTILINE)
                if n:
                    name = n.group(1).strip().strip("'\"")
                if d:
                    description = d.group(1).strip().strip("'\"")
                if a:
                    hint = a.group(1).strip().strip("'\"")
                body = content[fm_match.end():].strip()
            else:
                body = content.strip()

            index.append({
                'name': name,
                'desc': description[:300],
                'full_desc': description,
                'hint': hint[:200],
                'file': os.path.relpath(skill_md, _PROJECT_ROOT).replace('\\', '/'),
            })

        _skills_cache = index
        return _skills_cache


# ── Intent Matching Engine ──────────────────────────────


def suggest_skills(query, max_results=3):
    """Match a user query to relevant CE skills.

    Args:
        query: User's question or task description (str)
        max_results: Max skills to suggest (default 3)

    Returns:
        List of dicts with matched skills, sorted by relevance
    """
    if not query:
        return []

    query_lower = query.lower()
    skills = _build_skills_index()
    scored = []

    for s in skills:
        name = s['name']
        score = 0
        matched_keywords = []

        # Check intent map keywords
        keywords = _INTENT_MAP.get(name, [])
        for kw in keywords:
            if kw.lower() in query_lower:
                score += 3
                matched_keywords.append(kw)

        # Check description
        desc_lower = s['desc'].lower()
        # Split query into words and check overlap
        query_words = set(re.findall(r'\w+', query_lower))
        desc_words = set(re.findall(r'\w+', desc_lower))
        overlap = query_words & desc_words
        if overlap:
            score += len(overlap) * 0.5

        # Check name match
        name_parts = name.replace('ce-', '').replace('-', ' ')
        name_words = set(name_parts.split())
        name_overlap = query_words & name_words
        if name_overlap:
            score += len(name_overlap) * 2

        if score > 0:
            scored.append({
                'name': name,
                'desc': s['desc'][:120],
                'hint': s['hint'],
                'file': s['file'],
                'score': score,
                'matched_keywords': matched_keywords[:3],
            })

    # Sort by score descending
    scored.sort(key=lambda x: x['score'], reverse=True)
    return scored[:max_results]


def suggest_category(query):
    """Suggest a CE category based on user query.

    Returns:
        (category_key, skills_in_category) tuple, or None
    """
    query_lower = query.lower()
    best_cat = None
    best_score = 0

    cat_keywords = {
        'planning': ['plan', 'design', 'architect', 'strategy', 'requirement', ' brainstorm', 'idea', '规划', '设计', '架构'],
        'execution': ['implement', 'code', 'build', 'develop', 'work on', '实现', '开发', '编码', '执行'],
        'quality': ['review', 'refactor', 'simplify', 'polish', 'optimize', 'performance', '审查', '重构', '优化', '性能'],
        'debugging': ['debug', 'bug', 'fix', 'error', 'issue', 'problem', '调试', 'bug', '修复', '错误'],
        'documentation': ['doc', 'document', 'readme', 'knowledge', '文档', '知识', 'readme'],
        'git': ['commit', 'push', 'pr', 'pull request', 'branch', '提交', '推送', '分支'],
        'product': ['product', 'feature', 'roadmap', 'sprint', '产品', '功能', '路线图'],
    }

    for cat, kws in cat_keywords.items():
        score = 0
        for kw in kws:
            if kw.lower() in query_lower:
                score += 1
        if score > best_score:
            best_score = score
            best_cat = cat

    if best_cat and best_score > 0:
        skills_in_cat = [s for s in _build_skills_index()
                         if s['name'] in _CATEGORIES.get(best_cat, [])]
        return best_cat, skills_in_cat
    return None, []


# ── Prompt Formatting ───────────────────────────────────


def _format_skills_prompt():
    """Generate a concise skill reference block for agent context."""
    skills = _build_skills_index()
    if not skills:
        return ''

    lines = [
        '## 🧠 Compound Engineering Skills Available',
        '',
        f'**{len(skills)} skills** loaded from `plugins/compound-engineering/`.',
        '',
        '| Skill | Description | Usage |',
        '|---|---|---|',
    ]
    for s in skills:
        desc = s['desc'].replace('\n', ' ').strip()[:70]
        hint = s['hint'].replace('\n', ' ').strip()[:50] if s['hint'] else '—'
        lines.append(f"| `{s['name']}` | {desc} | `{hint}` |")

    lines.append('')
    lines.append('### Categories')
    for cat_key, cat_desc in _CATEGORY_DESC.items():
        skill_names = ', '.join(s['name'] for s in skills if s['name'] in _CATEGORIES.get(cat_key, []))
        lines.append(f'- **{cat_desc}**: {skill_names}')

    lines.append('')
    lines.append('### 💡 Auto-Suggestion Rule')
    lines.append('When user asks a dev-related question, match their intent using')
    lines.append('`compound_engineering.suggest_skills(query)` and proactively ask:')
    lines.append('"要不要试试 ce-xxx 技能？它能帮你做 YYY"')
    lines.append('')
    return '\n'.join(lines)


# ── Hooks Registration ─────────────────────────────────

try:
    from plugins.hooks import register

    @register('agent_before')
    def _inject_skills_into_context(ctx):
        """Inject compound engineering skills into agent context at startup."""
        prompt = _format_skills_prompt()
        if prompt:
            # Also inject into the ctx
            ctx['ce_skills'] = _build_skills_index()
            ctx['ce_skills_prompt'] = prompt

        return ctx

    # Mark as loaded
    _skills_count = len(_build_skills_index())
    print(f'[CE] Compound Engineering Plugin loaded ({_skills_count} skills, intent matching enabled)')

except ImportError:
    print('[CE] Cannot load hooks — running outside AG context')

except Exception as e:
    print(f'[CE] Plugin init error: {e}')
