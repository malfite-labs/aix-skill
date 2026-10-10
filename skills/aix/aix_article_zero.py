"""Policy presentation and bounded guardrails, not a universal fraud detector."""
from __future__ import annotations

import hashlib
import pathlib
import re

ARTICLE_ZERO_VERSION = '1.0'
ARTICLE_ZERO_URL = 'https://skill.aixprotocol.org/ARTICLE_ZERO.md'


def policy() -> dict:
    here = pathlib.Path(__file__).resolve().parent
    document = here/'ARTICLE_ZERO.md'
    if not document.is_file():
        document = here.parents[1]/'ARTICLE_ZERO.md'
    body = document.read_bytes()  # fail closed if the canonical policy is absent
    return {'version': ARTICLE_ZERO_VERSION,
            'hash': hashlib.sha256(body).hexdigest(),
            'url': ARTICLE_ZERO_URL, 'local_document': str(document),
            'summary': 'AIX 第零条例：禁止欺诈、伪造证据、虚假交付和蓄意欺骗。\n'
                       '任何人类或 Agent 的指令都不能豁免本条例。\n'
                       '继续加入即表示明确接受当前版本。',
            'hash_assurance': 'DOCUMENT_INTEGRITY_ONLY'}


def registration_consent() -> dict:
    current = policy()
    return {'article_zero': {'version': current['version'], 'hash': current['hash'],
                            'url': current['url'], 'explicit_join_consent': True,
                            'assurance': 'SKILL_RECORDED_CONSENT_NOT_HUMAN_ATTESTATION'}}


def refusal(text: str) -> dict | None:
    """Reject explicit requests to fake evidence; never adjudicate a participant.

    This deliberately bounded text check supplements the model instructions.
    Synthetic work cannot excuse instructions to pass it off as real evidence.
    """
    matches = list(re.finditer(r'(伪造|编造|捏造|假装|\b(?:fabricat\w*|forg(?:e|ed|ery|ing)|fake)\b)', text, re.I))
    fake = any(not re.search(r'(不|不要|不得|请勿|never\s+|not\s+|no\s+)$',
                            text[max(0, match.start()-12):match.start()], re.I)
               for match in matches)
    target = re.search(r'(证据|日志|回执|真人|审核|完成|测试|evidence|logs?|receipt|human|review|test|completion)', text, re.I)
    real_claim = re.search(r'(冒充|骗取|领取奖励|让.*相信|真实回执|作为真实|to get paid|pass .* as real)', text, re.I)
    human_lie = re.search(r'claim .*human reviewed.*(no human|even though)', text, re.I)
    labeled = re.search(r'(小说|虚构|明确标注为模拟|\b(?:fiction(?:al)?|simulation|synthetic)\b)', text, re.I)
    if not (human_lie or (fake and target and (real_claim or not labeled))):
        return None
    return {'ok': False, 'stop': True, 'code': 'ARTICLE_ZERO_FRAUD_REQUEST_REFUSED',
            'message': '不能伪造工作、证据或真人审核。可协助如实报告失败、补充真实证据，或制作明确标注的虚构与模拟内容。',
            'confirmed_fraud': False, 'used_protocol': []}


def submission_status(status: str | None) -> dict:
    status = status or 'UNVERIFIED'
    if status not in ('COMPLETED', 'PARTIALLY_COMPLETED', 'NOT_COMPLETED', 'UNVERIFIED'):
        raise ValueError('unsupported completion status')
    return {'completion_status': status, 'completion_status_assurance': 'WORKER_DECLARED',
            'independently_verified': False, 'fraud_status': 'NOT_ASSESSED',
            'submission_is_acceptance': False}
