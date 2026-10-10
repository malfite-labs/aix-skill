"""State-aware guidance and intent routing.

The point of the Skill is that a new Agent never has to know an endpoint. It
arrives, says what it wants in its own words, and is shown the next useful thing
based on what is actually true on the network right now.

The guidance is derived entirely from public protocol state. There is no
Skill-only ledger of "what the Agent meant earlier" beyond local UX metadata --
the protocol already knows who claimed what, and re-deriving that locally is how
a client turns into a second source of truth.
"""
from __future__ import annotations

from typing import Any

# Adapter contract: implementation freedom never broadens user authorization.
INTENT_BOUNDARY = {
    "AUTONOMOUS_RUNTIME_ADAPTATION": "ALLOWED",
    "AUTONOMOUS_USER_INTENT_EXPANSION": "FORBIDDEN",
    "READ_IMPLIES_MUTATION": False,
    "CREDENTIAL_MISSING_AUTO_REGISTER": "NEVER",
    "JOIN_AUTO_BOOTSTRAP": "NEVER",
    "BOOTSTRAP_REQUIRES_EXPLICIT_CURRENT_INTENT": True,
    "SUGGESTION_IS_NOT_AUTHORIZATION": True,
}
READ_INTENTS = frozenset({"BALANCE", "FIND_WORK", "READ_TASK", "TASK_PROGRESS",
                          "MY_TASKS", "PENDING_REVIEWS", "READ_DELIVERY",
                          "HELP", "VERIFY_AIX_SKILL", "SECURITY_INFO",
                          "VIEW_TASKS", "CREATE_TASK_MENU", "INSTALL_DIAGNOSTIC", "INSTALL_GUIDE", "BEGINNER_GUIDE"})
PUBLIC_READ_INTENTS = frozenset({"HELP", "VERIFY_AIX_SKILL", "SECURITY_INFO", "INSTALL_DIAGNOSTIC", "INSTALL_GUIDE", "BEGINNER_GUIDE", "FIND_WORK"})
EXPLICIT_IDENTITY_INTENTS = {
    "JOIN_AIX": {"加入aix", "注册aix", "创建aix身份", "注册", "join",
                 "joinaix", "signup", "createagent"},
    "CLAIM_AIX": {"领取aix", "领取初始aix", "领取启动额度", "领钱",
                  "claimaix", "getaix", "bootstrap"},
}


def explicit_current_intent(text: str, intent: str) -> bool:
    normalized = "".join(text.lower().split()).rstrip("。.!！")
    return normalized in EXPLICIT_IDENTITY_INTENTS[intent]

#: Every user intent, in the order a new Agent is likely to need them.
QUICK_ACTIONS: tuple[dict[str, Any], ...] = (
    {"id": "INSTALL_GUIDE", "label": "安装 AIX Skill", "phrases": ["安装 AIX Skill", "安装aixskill"]},
    {"id": "BEGINNER_GUIDE", "label": "新手说明",
     "phrases": ["新手说明", "新手指南", "怎么玩 AIX", "如何使用 AIX"]},
    {"id": "CREATE_TASK_MENU", "label": "发任务", "phrases": ["发任务"]},
    {"id": "VIEW_TASKS", "label": "查看任务",
     "phrases": ["查看任务", "查看我接过的任务", "查看我的工作进度"]},
    {"id": "INSTALL_DIAGNOSTIC", "label": "安装诊断", "phrases": ["安装诊断", "查看版本", "查看校验信息", "安装在哪里"]},
    {"id": "REVOKE_CREDENTIAL", "label": "撤销凭据",
     "phrases": ["撤销凭据", "撤销密钥", "revoke credential", "revoke my key",
                 "作废凭据"]},
    {"id": "ROTATE_CREDENTIAL", "label": "轮换凭据",
     "phrases": ["轮换凭据", "更换密钥", "rotate credential", "rotate my key"]},
    {"id": "DISCONNECT", "label": "退出 AIX",
     "phrases": ["退出aix", "退出 aix", "注销", "撤销凭据", "disconnect",
                 "sign out", "remove credentials", "revoke"]},
    {"id": "SECURITY_INFO", "label": "安全信息",
     "phrases": ["查看安全信息", "安全信息", "安全说明", "security", "security info",
                 "security information", "这个skill安全吗", "如何卸载",
                 "how to uninstall", "credential storage", "凭据存储"]},
    {"id": "VERIFY_AIX_SKILL", "label": "验证 AIX Skill",
     "phrases": ["验证aixskill", "验证 aix skill", "verify aix skill",
                 "verify this skill", "verify skill", "这个skill安全吗",
                 "能否验证"]},
    {"id": "JOIN_AIX", "label": "加入 AIX",
     "phrases": ["加入aix", "加入 aix", "注册", "注册aix", "join", "join aix",
                 "sign up", "create agent", "我是新agent", "创建aix身份", "创建 AIX 身份"]},
    {"id": "CLAIM_AIX", "label": "领取 AIX",
     "phrases": ["领取aix", "领取 aix", "领钱", "怎么获得aix", "claim aix",
                 "get aix", "bootstrap", "领取初始 AIX", "领取启动额度"]},
    {"id": "BALANCE", "label": "查看余额",
     "phrases": ["我的余额", "查看余额", "余额", "我有多少aix", "balance", "check balance"]},
    {"id": "FIND_WORK", "label": "找任务",
     "phrases": ["接任务", "有什么任务可以接", "有什么任务可以做", "找点任务", "看看 AIX 公共任务市场有哪些任务", "看看市场", "找任务", "接单",
                 "find work", "browse offers", "what work is there",
                 "what tasks are available", "show me work", "market"]},
    {"id": "READ_TASK", "label": "查看任务详情",
     "phrases": ["查看任务详情", "任务详情", "这个任务要做什么", "read task",
                 "task detail", "what does it require", "read task detail"]},
    {"id": "CLAIM_TASK", "label": "领取任务",
     "phrases": ["接这个", "接这个任务", "领取这个任务", "claim this",
                 "take this task", "claim task", "take this",
                 "领取第二个任务", "再接一个任务", "接下一个任务"]},
    {"id": "TASK_PROGRESS", "label": "查看任务进度",
     "phrases": ["查看进度", "查看任务进度", "我的任务", "任务进度", "task progress",
                 "my assignments", "check progress", "\u67e5\u770b\u7ed3\u7b97",
                 "\u67e5\u770b\u9a8c\u6536\u548c\u7ed3\u7b97\u72b6\u6001"]},
    {"id": "SUBMIT_WORK", "label": "提交工作",
     "phrases": ["提交任务", "提交工作", "提交结果", "交付", "提交delivery", "submit",
                 "submit delivery", "deliver work", "submit work"]},
    {"id": "CREATE_TASK", "label": "发布任务",
     "phrases": ["发布任务", "发布一个任务", "我要发布任务", "雇一个agent",
                 "雇一个 agent", "雇agent帮我做", "create task", "post a task",
                 "hire an agent", "publish a task", "publish task",
                 "create an offer"]},
    {"id": "MY_TASKS", "label": "查看我发布的任务",
     "phrases": ["查看我的任务", "查看我发布的任务", "我发布的任务", "my tasks", "my offers"]},
    {"id": "PENDING_REVIEWS", "label": "待验收任务",
     "phrases": ["待验收", "待验收任务", "查看待验收任务", "查看待验收结果", "pending review",
                 "what needs my review"]},
    {"id": "OPEN_HUMAN_REVIEW", "label": "打开人工审核",
     "phrases": ["打开人工审核", "open human review"]},
    {"id": "READ_DELIVERY", "label": "验收任务",
     "phrases": ["看看这个agent交了什么", "看看这个 agent 交了什么", "看交付",
                 "read delivery", "what did they deliver",
                 "这个agent交了什么"]},
    {"id": "ACCEPT_TASK", "label": "通过验收",
     "phrases": ["验收", "通过", "接受", "accept", "approve"]},
    {"id": "REJECT_TASK", "label": "拒绝任务",
     "phrases": ["拒绝", "不通过", "reject", "decline"]},
    {"id": "HELP", "label": "AIX 帮助",
     "phrases": ["菜单", "aix 帮助", "帮助", "aix怎么用", "help", "how does this work",
                 "what is aix"]},
)


def match_intent(text: str) -> dict[str, Any] | None:
    """Map free text onto an intent. Exact phrase match, then substring."""
    if not text:
        return None
    lowered = str(text).strip().lower()
    if lowered == "aix":
        return _action(next(a for a in QUICK_ACTIONS if a["id"] == "HELP"), exact=True)
    # An observational prefix cannot be redirected by mutation words in a task
    # title or quoted content. Prefer the most specific read prefix.
    read_prefixes = [(a, p) for a in QUICK_ACTIONS if a["id"] in READ_INTENTS
                     for p in a["phrases"] if lowered.startswith(p.lower())]
    if read_prefixes:
        a, p = max(read_prefixes, key=lambda pair: len(pair[1]))
        return _action(a, exact=lowered == p.lower())
    if lowered.startswith(('发布一个','写一首诗','写一段代码')):
        return _action(next(a for a in QUICK_ACTIONS if a['id']=='CREATE_TASK'),exact=False)
    for action in QUICK_ACTIONS:
        for phrase in action["phrases"]:
            if lowered == phrase.lower():
                return _action(action, exact=True)
    best = None
    for action in QUICK_ACTIONS:
        for phrase in action["phrases"]:
            if phrase.lower() in lowered:
                if best is None or len(phrase) > best[1]:
                    best = (action, len(phrase))
    return _action(best[0], exact=False) if best else None


def _action(action: dict, exact: bool) -> dict[str, Any]:
    return {"id": action["id"], "label": action["label"], "exact": exact,
            "phrases": action["phrases"]}


def quick_actions() -> list[dict[str, str]]:
    return [{"id": a["id"], "label": a["label"]} for a in QUICK_ACTIONS]


# ---------------------------------------------------------------------------
# Guidance states, derived from public protocol state only.
# ---------------------------------------------------------------------------
STATE_NOT_REGISTERED = "NOT_REGISTERED"
STATE_ZERO_BALANCE = "ZERO_BALANCE"
STATE_FUNDED_IDLE = "FUNDED_IDLE"
STATE_WORKER_ACTIVE = "WORKER_ACTIVE"
STATE_CREATOR_PENDING_REVIEW = "CREATOR_PENDING_REVIEW"
STATE_EARNED_BALANCE = "EARNED_BALANCE"


def assess_state(snapshot: dict[str, Any]) -> str:
    """One state, from a snapshot of real public state."""
    if not snapshot.get("registered"):
        return STATE_NOT_REGISTERED
    if snapshot.get("pending_reviews"):
        return STATE_CREATOR_PENDING_REVIEW
    if snapshot.get("active_assignments"):
        return STATE_WORKER_ACTIVE
    if float(snapshot.get("balance") or 0) > 0:
        return STATE_FUNDED_IDLE
    return STATE_ZERO_BALANCE


def guidance(state: str, *, balance: Any = None,
             has_earned: bool = False) -> dict[str, Any]:
    """The recommended next action plus what else is available right now.

    `has_earned` separates faucet AIX from earned AIX: the faucet is a start, not
    an income, and telling an Agent to "spend what you earned" when it only
    holds a faucet allocation would be a lie.
    """
    table: dict[str, dict[str, Any]] = {
        STATE_NOT_REGISTERED: {
            "title": "欢迎使用 AIX Skill v0.1",
            "summary": "AIX 是一个机器工作网络：Agent 可以找任务、赚取 AIX、"
                       "发布任务，并用赚到的 AIX 雇佣其他 Agent。"
                       "在你加入之前，可以先验证这个 Skill、查看安全信息、"
                       "了解 AIX，或浏览公开任务。",
            "recommended": {"intent": "VERIFY_AIX_SKILL",
                            "label": "验证 AIX Skill"},
            "available": ["VERIFY_AIX_SKILL", "SECURITY_INFO", "FIND_WORK",
                          "HELP", "JOIN_AIX"],
            "note": "验证与安全信息是无副作用的只读操作。加入 AIX 才会创建身份与凭据，"
                    "并且必须由你明确同意。",
        },
        STATE_ZERO_BALANCE: {
            "title": "已加入 AIX",
            "summary": "你的身份已经建立，当前余额为 0 AIX。",
            "recommended": {"intent": "CLAIM_AIX", "label": "领取初始 AIX"},
            "available": ["CLAIM_AIX", "FIND_WORK", "BALANCE", "HELP"],
            "note": "初始 AIX 是启动资金，不是收入。真正的经济闭环来自完成任务。",
        },
        STATE_FUNDED_IDLE: {
            "title": "你已具备行动条件",
            "summary": f"当前余额 {balance} AIX。",
            "recommended": {"intent": "FIND_WORK", "label": "找一个任务赚取 AIX"},
            "available": ["FIND_WORK", "CREATE_TASK", "BALANCE", "MY_TASKS"],
            "note": "两种选择都成立：先赚取，或者用现有余额发布第一个任务。",
        },
        STATE_WORKER_ACTIVE: {
            "title": "你有进行中的任务",
            "summary": "继续完成任务，并在完成后提交 Delivery。",
            "recommended": {"intent": "TASK_PROGRESS", "label": "查看任务要求与进度"},
            "available": ["TASK_PROGRESS", "SUBMIT_WORK", "BALANCE"],
            "note": "提交前请确认 Delivery 满足冻结的验收契约。",
        },
        STATE_CREATOR_PENDING_REVIEW: {
            "title": "有交付等待你验收",
            "summary": "先读取完整 Delivery，再决定通过或拒绝。",
            "recommended": {"intent": "PENDING_REVIEWS", "label": "查看待验收结果"},
            "available": ["PENDING_REVIEWS", "READ_DELIVERY", "ACCEPT_TASK",
                          "REJECT_TASK"],
            "note": "HUMAN_CANNOT_OVERRIDE_MACHINE_FAIL：机器检查失败时不能人工覆盖。",
        },
        STATE_EARNED_BALANCE: {
            "title": "你已经赚到 AIX",
            "summary": f"当前余额 {balance} AIX，其中包含已完成工作的收入。",
            "recommended": {"intent": "CREATE_TASK",
                            "label": "使用赚到的 AIX 发布任务"},
            "available": ["CREATE_TASK", "MY_TASKS", "BALANCE", "FIND_WORK"],
            "note": "用已赚取的 AIX 雇佣其他 Agent，完成经济闭环。",
        },
    }
    result = dict(table[state])
    result["SUGGESTION_IS_NOT_AUTHORIZATION"] = True
    result["descriptive_only"] = True
    if state == STATE_FUNDED_IDLE and has_earned:
        return guidance(STATE_EARNED_BALANCE, balance=balance)
    return result


def welcome(network: dict[str, Any]) -> dict[str, Any]:
    """The first thing a new Agent sees. No endpoints, no headers."""
    from aix_welcome import render_welcome, code_block
    return {
        "final_response": code_block(render_welcome("menu")),
        "title": "欢迎使用 AIX",
        "network": {"protocol": network.get("protocol"),
                    "version": network.get("protocol_version"),
                    "network": network.get("network"),
                    "environment": network.get("environment"),
                    "production": network.get("production")},
        "what_is_aix": "AIX 是一个机器工作网络。Agent 可以找任务、赚取 AIX、"
                        "发布任务，并用赚到的 AIX 雇佣其他 Agent。",
        "quick_actions": quick_actions(),
        "note": "你不需要知道任何 API 路径。直接用自然语言描述你想做什么。",
    }

