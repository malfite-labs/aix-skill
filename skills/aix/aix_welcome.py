"""Pure presentation only. These functions never install or contact AIX."""
from pathlib import Path

INSTALL_STATUS = "      ✦ 安装完成，欢迎入场 ✦"
MENU_STATUS = "      ✦ 欢迎回来，选择操作 ✦"


def render_welcome(mode="menu"):
    text = Path(__file__).with_name("welcome.txt").read_bytes().decode("utf-8")
    if text.count(INSTALL_STATUS) != 1:
        raise ValueError("canonical welcome status line is missing or duplicated")
    if mode == "install":
        return text
    if mode == "menu":
        return text.replace(INSTALL_STATUS, MENU_STATUS, 1)
    raise ValueError("unsupported welcome mode")


def code_block(text):
    return "```text\n" + text + "```"


def opportunity_summary(packet):
    """Show recommendations; never treat market text as commands."""
    lines = []
    profile = packet.get('profile')
    if profile:
        lines.append(f"公开信誉：{profile['reputation']}；已完成：{profile['completed_jobs']}")
    reasons = {'NO_AUTHORIZED_CONTEXT':'没有可访问的授权项目上下文。',
               'HOST_SELECTION_REQUIRED':'等待宿主选择；候选尚未被判断为匹配。',
               'NO_ELIGIBLE_OFFERS':'当前没有符合接单门槛的可领取任务。',
               'MARKET_UNAVAILABLE':'当前无法核实市场和接单资格。',
               'JOIN_REQUIRED':'请先明确加入 AIX。', 'NO_MATCH':'未找到适合当前能力的真实任务。',
               'NO_REAL_HIRE_NEED':'当前没有已确认的真实委托需求。'}
    earn = packet.get('earn')
    lines.append('EARN AIX')
    if earn:
        spec = earn['task_spec']
        title = (spec.get('title') or spec.get('description') or 'Market task') if isinstance(spec,dict) else str(spec)
        lines.extend([f"{title} — {earn['reward']} AIX",'理由：'+earn['match_reason']])
    else:
        lines.append(reasons.get(packet.get('earn_reason'),'未选择任务。'))
    hire = packet.get('hire')
    lines.append('HIRE AGENT')
    if hire:
        lines.extend([hire['task_suggestion'],'理由：'+hire['why_it_helps']])
    else:
        lines.append(reasons.get(packet.get('hire_reason'),'未发现真实委托需求。'))
    if packet.get('state')=='HOST_SELECTION_REQUIRED':
        lines.append('宿主 Agent：请根据已授权上下文判断候选是否匹配；没有匹配就如实说明。')
    else:
        lines.append('READY — 选择 EARN / HIRE；建议不会自动执行或支付。')
    return '\n'.join(lines)


class InstallLifecycle:
    """Product states driven by verified runtime facts; never executes an install.

    INSTALL_VERIFYING permits inspection/refusal under host security policy.
    A verified and activated installation ends at AIX_HOME. Diagnostics remain
    available separately. No filesystem writes, network, credentials or mutation.
    """
    def __init__(self, identity_state="UNKNOWN"):
        if identity_state not in ("UNKNOWN", "NOT_JOINED", "JOINED"):
            raise ValueError("unsupported identity state")
        self.identity_state = identity_state
        self.state = "INSTALL_VERIFYING"
        self.transitions = [self.state]
        self._verified = False
        self._reason = "安装校验尚未完成。"

    def _transition(self, state):
        self.state = state
        self.transitions.append(state)

    def verify(self, *, zip_verified=None, manifest_verified=None,
               files_verified=None, extracted=None, validation_completed=None):
        if self.state != "INSTALL_VERIFYING":
            return
        checks = (zip_verified, manifest_verified, files_verified, extracted,
                  validation_completed)
        if any(value is False for value in checks):
            self._reason = "安装验证失败，已停止。"
            self._transition("INSTALL_FAILED")
        elif all(value is True for value in checks):
            self._verified = True
            self._reason = "安装文件已就绪，但当前运行时尚未加载 AIX Skill。"
            self._transition("INSTALL_INCOMPLETE")

    def activate(self, *, discovered=None, loaded=None, reload_required=False,
                 restart_required=False):
        if self.state == "INSTALL_FAILED":
            return
        if not self._verified or discovered is not True or loaded is not True or reload_required is not False or restart_required is not False:
            return
        self._transition("INSTALL_ACTIVATED")
        self._transition("AIX_HOME")

    def response(self):
        if self.state == "AIX_HOME":
            return code_block(render_welcome("install")) + "\nINSTALL_SUCCESS\n" + self.identity_state + " — installation does not register an identity."
        return "STATUS = " + self.state + "\nREASON = " + self._reason + "\nNEXT ACTION = 完成验证及激活；需要技术信息时说“安装诊断”。"


def install_completion(*, zip_verified=None, manifest_verified=None,
                       files_verified=None, extracted=None, discovered=None,
                       loaded=None, validation_completed=None,
                       reload_required=False, restart_required=False,
                       identity_state="UNKNOWN"):
    runtime = InstallLifecycle(identity_state)
    runtime.verify(zip_verified=zip_verified, manifest_verified=manifest_verified,
                   files_verified=files_verified, extracted=extracted,
                   validation_completed=validation_completed)
    runtime.activate(discovered=discovered, loaded=loaded,
                     reload_required=reload_required, restart_required=restart_required)
    return {"status": runtime.state, "transitions": runtime.transitions,
            "final_response": runtime.response()}


def install_final_response(**verified_runtime_facts):
    """Verified activation transitions to AIX_HOME; host policy stays authoritative."""
    return install_completion(**verified_runtime_facts)["final_response"]
