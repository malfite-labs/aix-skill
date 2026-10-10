import pathlib,sys
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
from aix_guidance import match_intent
from aix_skill import AixSkill

def test_natural_review_entry_routes_without_approving():
    assert match_intent('打开人工审核')['id']=='OPEN_HUMAN_REVIEW'
    assert match_intent('查看待验收任务')['id']=='PENDING_REVIEWS'
    source=pathlib.Path(__file__).resolve().parents[1].joinpath('aix_skill.py').read_text(encoding='utf-8')
    assert '尚无可信真人验证入口' not in source

def test_review_entry_without_enrolled_reviewer_pairs_only():
    skill=object.__new__(AixSkill);calls=[]
    class Client:
        def _call(self,method,path,body=None):
            calls.append(path)
            if method=='GET':return {'items':[]}
            assert body['assignment_id']=='a'
            return {'pairing_url':'https://beta.aixprotocol.org/review#pair=synthetic-example'}
    skill.client=Client()
    result=skill._i_open_human_review(assignment_id='a')
    assert result['review_url'].startswith('https://beta.aixprotocol.org/review#pair=')
    assert result['human_verified'] is False
    assert calls==['/v1/review/reviewers','/v1/review/pairings']

def test_new_human_policy_requires_passkey_but_auto_keeps_fast_path():
    from aix_acceptance import propose_policy
    assert propose_policy('我来验收')['actor_assurance']=='webauthn_user_verified'
    assert propose_policy('AUTO')['actor_assurance']=='creator_authorized'

def test_progress_keeps_machine_human_and_money_separate(monkeypatch):
    import aix_skill
    skill=object.__new__(AixSkill)
    class Client:
        def task_progress(self,aid):
            return {'assignment':{'state':'SETTLED'},'submission':{
                'evaluation':{'machine_verdict':'PASS','human_verdict':'APPROVE'},
                'review_actor_assurance':'webauthn_user_verified','human_verified':True,
                'financial_status':'SETTLED'}}
    skill.client=Client();skill.snapshot=lambda:{}
    monkeypatch.setattr(aix_skill,'assess_state',lambda _: 'synthetic')
    monkeypatch.setattr(aix_skill,'guidance',lambda _: {})
    progress=skill._i_task_progress(assignment_id='a')['verification_progress']
    assert progress=={'machine':'PASS','human':'APPROVE','actor_assurance':'webauthn_user_verified','human_verified':True,'settlement':'SETTLED'}
