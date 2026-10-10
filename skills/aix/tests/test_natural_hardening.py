"""Product regressions; these do not claim real Agent or human execution."""
import pathlib
import sys
import pytest
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

def test_committed_business_result_and_coverage():
    from aix_acceptance import committed_exact_rule, acceptance_coverage
    rule = committed_exact_rule('total', '$.structured_output.total_amount', 4550)
    assert rule['check']['kind'] == 'json_path_equals_committed'
    assert rule['check']['expected'] == 4550
    assert rule['check']['commitment'].startswith('sha256:')
    coverage = acceptance_coverage([rule])
    assert coverage['exact_checks'] == ['total']
    assert not coverage['structure_only']

def test_structural_auto_cannot_publish():
    from aix_skill import AixSkill
    from aix_acceptance import propose_policy
    skill = object.__new__(AixSkill)
    class NoWrites:
        def create_task(self, *a, **kw):
            pytest.fail('underconstrained AUTO moved escrow')
    skill.client = NoWrites()
    rules = [{'id':'shape', 'required':True, 'check':{'kind':'json_path_exists','path':'$.total'}}]
    result = skill._i_create_task(task_spec={'description':'calculate total'}, reward='2',
        rules=rules, acceptance_policy=propose_policy('AUTO', rules), confirmed=True)
    assert result['code'] == 'AUTO_BUSINESS_CHECK_REQUIRED'
    assert result['created'] is False

def test_natural_submit_and_install_aliases():
    from aix_guidance import match_intent
    assert match_intent('提交任务')['id'] == 'SUBMIT_WORK'
    assert match_intent('安装 AIX Skill')['id'] == 'INSTALL_GUIDE'

def test_install_status_is_not_join_consent():
    from aix_welcome import install_completion
    result = install_completion(identity_state='NOT_JOINED', **dict.fromkeys(('zip_verified','manifest_verified',
        'files_verified','extracted','discovered','loaded','validation_completed'), True))
    assert 'INSTALL_SUCCESS' in result['final_response']
    assert 'NOT_JOINED' in result['final_response']
    assert 'Machine Hires Machine' in result['final_response']
    assert 'HIRES' in result['final_response']

def test_committed_preview_does_not_disclose_secret():
    import json
    from aix_acceptance import committed_exact_rule, public_rules
    rules = [committed_exact_rule('total', '$.total', 4550, salt='private-salt')]
    projected = public_rules(rules)
    assert 'private-salt' not in json.dumps(projected)
    assert 'expected' not in json.dumps(projected)
    assert rules[0]['check']['expected'] == 4550

def test_auto_requires_core_requirement_mapping():
    from aix_skill import AixSkill
    from aix_acceptance import committed_exact_rule, propose_policy
    skill=object.__new__(AixSkill)
    skill.client=object()
    rules=[committed_exact_rule('status','$.status','PASS')]
    result=skill._i_create_task(task_spec={'description':'calculate total'},reward='2',
        rules=rules,acceptance_policy=propose_policy('AUTO',rules),confirmed=True)
    assert result['code']=='AUTO_BUSINESS_CHECK_REQUIRED'

def test_actual_preview_is_public_and_validated_without_publish():
    import json
    from aix_skill import AixSkill
    from aix_acceptance import committed_exact_rule, propose_policy
    skill=object.__new__(AixSkill)
    class Client:
        def _call(self, method, path, body):
            assert path=='/v1/acceptance/preflight'
            assert 'expected' not in json.dumps(body)
            return {'valid':True}
        def create_task(self,*args,**kw):
            pytest.fail('preview published')
    skill.client=Client()
    rules=[committed_exact_rule('total','$.total_amount',4550,salt='private-salt')]
    result=skill._i_create_task(task_spec={'description':'calculate total'},reward='2',
        rules=rules,acceptance_policy=propose_policy('AUTO',rules),
        core_result_rules={'computed total':['total']})
    assert result['confirmation_required']
    assert 'private-salt' not in json.dumps(result)
    assert 'expected' not in json.dumps(result)

def test_natural_publish_cannot_bypass_quality_with_legacy_rules():
    from aix_skill import AixSkill
    skill=object.__new__(AixSkill)
    skill.client=object()
    result=skill.handle('发布任务',task_spec={'description':'calculate total'},reward='2',
        rules=[{'id':'shape','check':{'kind':'json_path_exists','path':'$.total'}}],confirmed=True)
    assert result['code']=='AUTO_BUSINESS_CHECK_REQUIRED'

@pytest.mark.parametrize('suffix,mode',[('失败后由我复核','FALLBACK'),('fallback','FALLBACK'),('dual','DUAL')])
def test_explicit_review_mode_is_preserved(suffix,mode):
    from aix_skill import AixSkill
    skill=object.__new__(AixSkill)
    skill.client=object()
    skill._i_create_task=lambda **kw: {'policy':kw['acceptance_policy']}
    result=skill.handle('发布任务 '+suffix,rules=[{'id':'R1','check':{'kind':'json_path_exists','path':'$.x'}}])
    assert result['policy']['verification_mode']==mode
