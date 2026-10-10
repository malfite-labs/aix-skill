"""Natural mode suggestions are previews; publication needs confirmation."""
import pytest
import pathlib, sys
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
from aix_acceptance import propose_policy

@pytest.mark.parametrize('text,mode',[
    ('写一首诗，40 AIX，我来验收','HUMAN_ONLY'),
    ('写一首诗，先检查字数和格式，再由我挑选','DUAL'),
    ('自动检查，失败时让我复核','FALLBACK'),
    ('代码测试通过就自动付款','AUTO'),
])
def test_natural_mode_recommendation(text,mode):
    result=propose_policy(text)
    assert result['verification_mode']==mode
    assert result['actor_assurance']==('creator_authorized' if mode=='AUTO' else 'webauthn_user_verified')
    assert result['timeout_disposition']=='REFUND'

def test_no_request_is_not_silently_auto():
    assert propose_policy('发布一个任务')['verification_mode']=='HUMAN_ONLY'

def test_preview_cannot_move_money_and_confirmed_policy_is_forwarded(monkeypatch):
    from aix_skill import AixSkill
    skill=object.__new__(AixSkill)
    class Client:
        def _call(self,method,path,body):
            assert path=='/v1/acceptance/preflight'
            return {'valid':True,'money_moved':'0'}
        def create_task(self,*args,**kw):
            assert kw['acceptance_policy']['verification_mode']=='HUMAN_ONLY'
            return {'offer_id':'o','reward':'40'}
        def remember_offer(self,*args):pass
    skill.client=Client()
    monkeypatch.setattr(skill,'snapshot',lambda:{'registered':True,'balance':40})
    preview=skill._i_create_task(_request_text='写一首诗，40 AIX，我来验收',reward='40')
    assert not preview['created'] and preview['confirmation_required']
    made=skill._i_create_task(_request_text='写一首诗，40 AIX，我来验收',reward='40',confirmed=True)
    assert made['created']

def test_pending_reviews_use_authenticated_review_view_not_market():
    from aix_skill import AixSkill
    skill=object.__new__(AixSkill)
    class Client:
        def _call(self,method,path):
            assert method=='GET' and path.startswith('/v1/reviews/pending?')
            return {'items':[{'assignment_id':'filled-offer-delivery','can_approve':True,
                             'evaluation':{'machine_verdict':'NOT_APPLICABLE','final_acceptance':'PENDING'}}]}
    skill.client=Client()
    view=skill._i_pending_reviews()
    assert view['count']==1 and view['read_only']
    assert view['items'][0]['can_approve'] is True
