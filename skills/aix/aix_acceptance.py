"""Explain frozen contract-level modes; never publish a recommendation."""
import hashlib
import json
import secrets

def committed_exact_rule(rule_id, path, expected, *, salt=None):
    """Creator-only frozen DSL check; never disclose expected/salt to Workers."""
    salt = secrets.token_hex(32) if salt is None else salt
    material = json.dumps({'expected': expected, 'path': path,
                           'rule_id': rule_id, 'salt': salt}, sort_keys=True,
                          separators=(',', ':'), ensure_ascii=False,
                          allow_nan=False).encode('utf-8')
    return {'id': rule_id, 'requirement': 'Exact result at ' + path,
            'required': True, 'verification_mode': 'MACHINE',
            'check': {'kind': 'json_path_equals_committed', 'path': path,
                      'expected': expected, 'salt': salt,
                      'commitment': 'sha256:' + hashlib.sha256(material).hexdigest()}}

def acceptance_coverage(rules):
    """Describe checks, never infer complete correctness from structure."""
    exact = {'json_path_equals', 'json_path_equals_committed', 'text_sha256_equals'}
    business = [r['id'] for r in rules if r.get('required', True)
                and r.get('verification_mode', 'MACHINE') == 'MACHINE'
                and (r.get('check') or {}).get('kind') in exact]
    return {'exact_checks': business,
            'other_checks': [r['id'] for r in rules if r['id'] not in business],
            'structure_only': not business,
            'scope': 'Only listed paths/values are verified; unlisted business requirements remain unverified.'}

def public_rules(rules):
    """Frozen committed projection suitable for previews and audit traces."""
    import copy
    result = copy.deepcopy(rules)
    for rule in result:
        check = rule.get('check') or {}
        if check.get('kind') == 'json_path_equals_committed':
            check.pop('expected', None)
            check.pop('salt', None)
    return result

def propose_policy(text, rules=()):
    text=text or ''
    if any(word in text for word in ('失败时','失败后','复核','fallback','FALLBACK')):
        mode='FALLBACK'
    elif any(word in text for word in ('再由我','再人工','挑选','DUAL','dual')):
        mode='DUAL'
    elif any(word in text for word in ('自动付款','自动验收','测试通过','AUTO','auto')):
        mode='AUTO'
    else:
        mode='HUMAN_ONLY'
    return {'schema_version':'aix-acceptance-policy-v0.8.1',
            'verification_mode':mode,
            'override_rule_ids':[r['id'] for r in rules if r.get('required',True)] if mode=='FALLBACK' else [],
            'unknown_disposition':'WAIT','review_window_seconds':86400,
            'timeout_disposition':'REFUND','reviewer':'CREATOR',
            'actor_assurance':'creator_authorized' if mode=='AUTO' else 'webauthn_user_verified',
            'acceptance_criteria':[text.strip() or 'Creator 按公开任务要求审核交付']}
