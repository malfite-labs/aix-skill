"""Automated tests for AIX Skill v0.1.

No test contacts a live network, and no test may print or snapshot a real
credential: everything runs against fixtures with obviously fake keys.
"""
from __future__ import annotations

import json
import pathlib
import sys

import pytest


@pytest.fixture(autouse=True)
def isolated_boundary_storage(tmp_path, monkeypatch):
    monkeypatch.setenv("AIX_SKILL_CREDENTIAL_FILE", str(tmp_path / "fallback.json"))

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from aix_client import (UNSUPPORTED_RULE_KINDS, AixClient, AixError,  # noqa: E402
                        contract_summary, operations)
from aix_credentials import (REDACTED, CredentialStore, is_secret_field,  # noqa: E402
                             redact, summarize)
from aix_guidance import (assess_state, guidance, match_intent,  # noqa: E402
                          quick_actions)
from aix_skill import AixSkill  # noqa: E402

FAKE_KEY = "fake_key_not_a_real_credential"


class ProbeKeyring:
    def __init__(self, unavailable=False):
        self.data = {}
        self.unavailable = unavailable

    def set_password(self, service, key, value):
        if self.unavailable:
            raise RuntimeError("no D-Bus / SecretService")
        self.data[service, key] = value

    def get_password(self, service, key):
        if self.unavailable:
            raise RuntimeError("backend unavailable")
        return self.data.get((service, key))

    def delete_password(self, service, key):
        self.data.pop((service, key), None)


def test_headless_importable_keyring_auto_fallback(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "keyring", ProbeKeyring(unavailable=True))
    store = CredentialStore()
    assert store.backend == "isolated_file"
    assert store.identity_state() == "NO_IDENTITY"
    assert list(tmp_path.iterdir()) == []


def test_storage_probe_creates_no_production_files(tmp_path):
    from aix_credentials import probe_store
    store = CredentialStore().file_store()
    assert probe_store(store)[0]
    assert list(tmp_path.iterdir()) == []


def test_real_capable_keyring_probe_is_clean(tmp_path, monkeypatch):
    keyring = ProbeKeyring()
    monkeypatch.setitem(sys.modules, "keyring", keyring)
    store = CredentialStore()
    assert store.backend == "os_keyring"
    assert keyring.data == {}
    assert list(tmp_path.iterdir()) == []


def test_corrupt_file_never_overwritten(tmp_path):
    store = CredentialStore().file_store()
    store.isolated_file.write_text('{broken', encoding='utf-8')
    assert store.identity_state() == "IDENTITY_STATE_CORRUPT"
    with pytest.raises(Exception):
        store.save('replacement', FAKE_KEY)
    assert store.isolated_file.read_text() == '{broken'


def test_keyring_outage_preserves_local_identity_evidence(tmp_path, monkeypatch):
    keyring = ProbeKeyring()
    monkeypatch.setitem(sys.modules, "keyring", keyring)
    store = CredentialStore()
    store.save('existing', FAKE_KEY)
    keyring.unavailable = True
    reopened = CredentialStore()
    assert reopened.identity_state() == "BACKEND_UNAVAILABLE"
    assert reopened.agent_ids() == ['existing']
    skill = AixSkill(store=reopened)
    assert skill.handle('加入 AIX', consent=True)['status'] == 'CREDENTIAL_UNAVAILABLE'


def test_atomic_failure_preserves_existing_secret(tmp_path, monkeypatch):
    import aix_credentials
    store = CredentialStore().file_store()
    store.save('existing', FAKE_KEY)
    before = store.isolated_file.read_bytes()
    monkeypatch.setattr(aix_credentials, '_durable_replace', lambda *a: (_ for _ in ()).throw(OSError('disk')))
    with pytest.raises(OSError):
        store.save('new', 'another-fake-secret')
    assert store.isolated_file.read_bytes() == before
    assert sorted(p.name for p in tmp_path.iterdir()) == ['fallback.json', 'fallback.json.identity.json']


def test_join_discloses_unknown_durability_and_stable_identity():
    store = CredentialStore().file_store()
    result = AixSkill(store=store).handle('加入 AIX')
    summary = result['consent_summary']
    assert '如果运行环境被删除，本地凭据可能丢失。' in summary['warning']
    assert summary['DURABILITY_STATUS'] == 'UNKNOWN'
    assert 'disposable' not in json.dumps(summary)


def test_probe_failed_delete_and_read_cannot_confirm_absence(monkeypatch):
    from aix_credentials import probe_store
    keyring = ProbeKeyring()
    monkeypatch.setitem(sys.modules, 'keyring', keyring)
    store = CredentialStore()
    keyring.delete_password = lambda *a: (_ for _ in ()).throw(RuntimeError('delete blocked'))
    original_get = keyring.get_password
    reads = []
    def read(service, key):
        if key.startswith('_aix_probe_'):
            reads.append(key)
            if len(reads) > 1:
                raise RuntimeError('read blocked')
        return original_get(service, key)
    keyring.get_password = read
    assert probe_store(store)[0] is False


def test_keyring_empty_index_is_corrupt(monkeypatch):
    keyring = ProbeKeyring()
    monkeypatch.setitem(sys.modules, 'keyring', keyring)
    store = CredentialStore()
    keyring.data[store._account(), '__aix_identity_index__'] = ''
    assert store.identity_state() == 'IDENTITY_STATE_CORRUPT'


def test_keyring_metadata_destination_must_be_usable(tmp_path, monkeypatch):
    keyring = ProbeKeyring()
    monkeypatch.setitem(sys.modules, 'keyring', keyring)
    parent = tmp_path / 'blocked'
    parent.write_text('regular file')
    monkeypatch.setenv('AIX_SKILL_CREDENTIAL_FILE', str(parent / 'credentials.json'))
    store = CredentialStore()
    from aix_credentials import probe_store
    assert probe_store(store)[0] is False


def test_reopen_recovers_same_identity_after_keyring_write_fallback(monkeypatch):
    from aix_client import AixClient
    keyring = ProbeKeyring()
    monkeypatch.setitem(sys.modules, 'keyring', keyring)
    store = CredentialStore()
    client = AixClient('https://beta.aixprotocol.org', store=store)
    client.agent_id, client._api_key = 'existing', FAKE_KEY
    original = keyring.set_password
    def failing(service, key, value):
        if key == 'existing':
            raise RuntimeError('post-registration outage')
        original(service, key, value)
    keyring.set_password = failing
    client.identity = lambda: {'agent_id': 'existing'}
    assert client.store_credential()['backend'] == 'isolated_file'
    reopened = AixSkill(store=CredentialStore())
    reopened.client.identity = lambda: {'agent_id': 'existing'}
    result = reopened.handle('加入 AIX', consent=True)
    assert result['already_registered']
    assert reopened.client._api_key == FAKE_KEY


def test_active_identity_wording_is_stable():
    import re
    root = pathlib.Path(__file__).parents[1]
    pattern = re.compile(r'one.time identity|disposable(?: AIX Agent)? identity|一次性身份|临时身份', re.I)
    for name in ('SKILL.md', 'SECURITY.md', 'PERMISSIONS.md', 'aix_skill.py'):
        assert not pattern.search((root / name).read_text(encoding='utf-8')), name


def test_probe_cleanup_failure_returns_failure_without_throwing(monkeypatch, tmp_path):
    import aix_credentials
    original = aix_credentials.tempfile.TemporaryDirectory.cleanup
    def failure(self):
        original(self)
        raise OSError('cleanup failed')
    monkeypatch.setattr(aix_credentials.tempfile.TemporaryDirectory, 'cleanup', failure)
    store = CredentialStore().file_store()
    ok, detail = aix_credentials.probe_store(store)
    assert not ok and 'cleanup' in detail
    assert list(tmp_path.iterdir()) == []


def test_failed_fallback_probe_is_not_labeled_not_run(monkeypatch):
    import aix_credentials
    store = CredentialStore().file_store()
    skill = AixSkill(store=store)
    skill.client.discover = lambda: {}
    monkeypatch.setattr(aix_credentials, 'probe_store', lambda *a: (False, 'isolated_file: PermissionError'))
    result = skill.handle('加入 AIX', consent=True)
    assert result['code'] == 'CREDENTIAL_STORE_NOT_READY'
    probe = result['preflight']['PROBE_RESULT']
    assert probe['fallback'] == 'FAIL'
    assert probe['fallback_detail'] == 'isolated_file: PermissionError'


def test_keyring_consent_discloses_possible_ephemeral_file_fallback(monkeypatch):
    monkeypatch.setitem(sys.modules, 'keyring', ProbeKeyring())
    skill = AixSkill(store=CredentialStore())
    summary = skill.handle('加入 AIX')['consent_summary']
    assert summary['SELECTED_BACKEND'] == 'os_keyring'
    assert '本地隔离文件' in summary['warning']
    assert '本地凭据可能丢失' in summary['warning']


@pytest.mark.skipif(sys.platform == 'win32', reason='POSIX directory ownership')
def test_probe_rejects_nonowned_writable_parent_without_registering(tmp_path):
    import os
    if os.geteuid() != 0:
        pytest.skip('isolated root container required for owner-change fixture')
    from aix_credentials import probe_store
    store = CredentialStore().file_store()
    parent = tmp_path / 'other-owner'
    parent.mkdir(mode=0o777)
    os.chown(parent, 65534, 65534)
    store._path = parent / 'credentials.json'
    assert probe_store(store)[0] is False
    assert list(parent.iterdir()) == []


@pytest.mark.skipif(sys.platform == 'win32', reason='POSIX modes require POSIX')
def test_fallback_metadata_and_directory_permissions():
    store = CredentialStore().file_store()
    store.save('existing', FAKE_KEY)
    assert store.isolated_file.stat().st_mode & 0o777 == 0o600
    assert store.isolated_file.with_name(store.isolated_file.name + '.identity.json').stat().st_mode & 0o777 == 0o600
    assert store.isolated_file.parent.stat().st_mode & 0o777 == 0o700


@pytest.mark.parametrize('host', ['skill.aixprotocol.org', 'aixprotocol.org',
    'other-network.aixprotocol.org', 'beta.aixprotocol.org.example.invalid', 'example.invalid'])
def test_beta_build_refuses_credential_on_other_hosts(host, monkeypatch):
    import aix_client
    sent = []
    monkeypatch.setattr(aix_client, '_urlopen_with_ipv4_fallback', lambda *a, **k: sent.append(a))
    client = AixClient('https://' + host, agent_id='fixture_agent')
    client._api_key = FAKE_KEY
    with pytest.raises(AixError) as error:
        client._request('GET', '/v1/agents/me')
    assert error.value.code == 'CREDENTIAL_HOST_SCOPE'
    assert sent == []


def test_beta_build_authentication_reaches_only_canonical_host(monkeypatch):
    import aix_client
    sent = []
    def capture(req, timeout):
        sent.append(req)
        return 200, b'{}'
    monkeypatch.setattr(aix_client, '_urlopen_with_ipv4_fallback', capture)
    client = AixClient('https://beta.aixprotocol.org', agent_id='fixture_agent')
    client._api_key = FAKE_KEY
    client._request('GET', '/v1/agents/me')
    assert sent[0].host == 'beta.aixprotocol.org'
    assert sent[0].get_header('Authorization') == 'Bearer ' + FAKE_KEY


def test_authenticated_redirect_is_not_followed():
    import urllib.request
    from aix_client import _NoCredentialRedirect
    req = urllib.request.Request('https://beta.aixprotocol.org/v1/agents/me',
                                 headers={'Authorization':'Bearer '+FAKE_KEY})
    with pytest.raises(urllib.error.HTTPError):
        _NoCredentialRedirect().redirect_request(req,None,302,'Found',{},'https://example.invalid/')


# --------------------------------------------------------------- 28. intents
@pytest.mark.parametrize("text,intent", [
    ("加入AIX", "JOIN_AIX"),
    ("注册", "JOIN_AIX"),
    ("join aix", "JOIN_AIX"),
    ("领取AIX", "CLAIM_AIX"),
    ("claim aix", "CLAIM_AIX"),
    ("查看余额", "BALANCE"),
    ("check balance", "BALANCE"),
    ("有什么任务可以做？", "FIND_WORK"),
    ("找点任务", "FIND_WORK"),
    ("看看市场", "FIND_WORK"),
    ("browse offers", "FIND_WORK"),
    ("查看任务详情", "READ_TASK"),
    ("接这个", "CLAIM_TASK"),
    ("领取第二个任务", "CLAIM_TASK"),
    ("take this task", "CLAIM_TASK"),
    ("查看任务进度", "TASK_PROGRESS"),
    ("提交工作", "SUBMIT_WORK"),
    ("我要发布一个任务", "CREATE_TASK"),
    ("发布任务", "CREATE_TASK"),
    ("雇一个 Agent 帮我做", "CREATE_TASK"),
    ("查看我发布的任务", "MY_TASKS"),
    ("查看待验收结果", "PENDING_REVIEWS"),
    ("看看这个 Agent 交了什么", "READ_DELIVERY"),
    ("验收", "ACCEPT_TASK"),
    ("拒绝", "REJECT_TASK"),
    ("AIX 帮助", "HELP"),
])
def test_intent_mapping(text, intent):
    assert match_intent(text)["id"] == intent


def test_unmatched_text_falls_back_to_guidance():
    """Unknown text is answered with help, not rejected."""
    assert match_intent("zzz nonsense") is None


def test_all_required_intents_exist():
    ids = {a["id"] for a in quick_actions()}
    required = {"JOIN_AIX", "CLAIM_AIX", "BALANCE", "FIND_WORK", "READ_TASK",
                "CLAIM_TASK", "TASK_PROGRESS", "SUBMIT_WORK", "CREATE_TASK",
                "MY_TASKS", "PENDING_REVIEWS", "READ_DELIVERY", "ACCEPT_TASK",
                "REJECT_TASK", "HELP"}
    assert required <= ids


# -------------------------------------------------------------- 28. guidance
@pytest.mark.parametrize("snapshot,state", [
    ({"registered": False}, "NOT_REGISTERED"),
    ({"registered": True, "balance": 0}, "ZERO_BALANCE"),
    ({"registered": True, "balance": 10}, "FUNDED_IDLE"),
    ({"registered": True, "balance": 10, "active_assignments": ["a"]}, "WORKER_ACTIVE"),
    ({"registered": True, "balance": 10, "pending_reviews": ["a"]},
     "CREATOR_PENDING_REVIEW"),
])
def test_guidance_state_machine(snapshot, state):
    assert assess_state(snapshot) == state


def test_guidance_changes_with_state():
    recommended = {s: guidance(s, balance=5)["recommended"]["intent"]
                   for s in ("NOT_REGISTERED", "ZERO_BALANCE", "FUNDED_IDLE",
                             "WORKER_ACTIVE", "CREATOR_PENDING_REVIEW",
                             "EARNED_BALANCE")}
    # A new Agent is pointed at verification first: trust before economics.
    assert recommended["NOT_REGISTERED"] == "VERIFY_AIX_SKILL"
    assert recommended["ZERO_BALANCE"] == "CLAIM_AIX"
    assert recommended["CREATOR_PENDING_REVIEW"] == "PENDING_REVIEWS"
    assert recommended["WORKER_ACTIVE"] == "TASK_PROGRESS"
    assert recommended["EARNED_BALANCE"] == "CREATE_TASK"
    assert len(set(recommended.values())) >= 5


def test_faucet_aix_is_not_presented_as_earned():
    """A funded Agent that only ever held faucet AIX is not told to hire."""
    g = guidance("FUNDED_IDLE", balance=10, has_earned=False)
    assert g["recommended"]["intent"] == "FIND_WORK"


# ------------------------------------------------------- 28. credential safety
def test_redaction_hides_secrets():
    payload = {"api_key": FAKE_KEY, "Authorization": "Bearer x", "nested":
               [{"private_key": "y"}], "agent_id": "aix8_ag_test"}
    out = redact(payload)
    assert out["api_key"] == REDACTED
    assert out["nested"][0]["private_key"] == REDACTED
    assert out["agent_id"] == "aix8_ag_test"


def test_secret_field_detection():
    assert is_secret_field("api_key") and is_secret_field("Authorization")
    assert not is_secret_field("agent_id")


def test_summarize_omits_credential():
    out = summarize({"agent_id": "aix8_ag_x", "api_key": FAKE_KEY, "balance": 0})
    assert FAKE_KEY not in json.dumps(out)
    assert out["agent_id"] == "aix8_ag_x"


def test_credential_store_roundtrip(tmp_path):
    store = CredentialStore("test").file_store()
    store._path = tmp_path / "cred.json"
    store.save("aix8_ag_x", FAKE_KEY)
    assert store.load("aix8_ag_x") == FAKE_KEY
    assert store.agent_ids() == ["aix8_ag_x"]
    store.forget("aix8_ag_x")
    assert store.load("aix8_ag_x") is None


def test_credential_file_is_owner_only(tmp_path):
    if sys.platform == "win32":
        pytest.skip("POSIX permission bits are not meaningful on Windows")
    store = CredentialStore("test").file_store()
    store._path = tmp_path / "cred.json"
    store.save("aix8_ag_x", FAKE_KEY)
    assert store._path.stat().st_mode & 0o077 == 0


def test_client_requires_credential_before_privileged_call():
    c = AixClient("http://127.0.0.1:1")
    with pytest.raises(AixError) as exc:
        c.balance()
    assert exc.value.code == "UNAUTHORIZED"


# ------------------------------------------------------ 28. error translation
@pytest.mark.parametrize("code,fragment", [
    ("INSUFFICIENT_BALANCE", "余额"),
    ("BOOTSTRAP_EXHAUSTED", "暂时不可领取"),
    ("UNSUPPORTED_RULE", "不支持"),
])
def test_error_translation_keeps_code(code, fragment):
    err = AixError(400, {"code": code, "message": "raw protocol text"})
    text = err.agent_message()
    assert fragment in text
    assert code in text  # machine-readable code stays available


def test_unknown_error_still_carries_code():
    err = AixError(500, {"code": "INTERNAL", "message": "boom"})
    assert "INTERNAL" in err.agent_message()


def test_claim_conflict_is_translated_not_crashed():
    err = AixError(409, {"code": "CLAIM_CONFLICT"})
    assert "Assignment" in err.agent_message() and "可能" in err.agent_message()


# ------------------------------------------- 28. unsupported rule + idempotency
@pytest.mark.parametrize("kind", UNSUPPORTED_RULE_KINDS)
def test_unsupported_rule_kinds_are_filtered_before_publish(kind):
    c = AixClient("http://127.0.0.1:1")
    rules = [{"id": "R1", "check": {"kind": kind}}]
    with pytest.raises(AixError) as exc:
        c.create_task({"title": "t"}, "1", rules)
    assert exc.value.code == "UNSUPPORTED_RULE"


def test_supported_artifact_gate_is_not_blocked():
    """The way to gate artifacts must still work."""
    c = AixClient("http://127.0.0.1:1")
    rules = [{"id": "R1", "check": {"kind": "json_path_exists",
                                    "path": "$.artifacts"}}]
    with pytest.raises(AixError) as exc:
        c.create_task({"title": "t"}, "1", rules)
    # fails on network, not on rule filtering
    assert exc.value.code != "UNSUPPORTED_RULE"


def test_contract_summary_hides_committed_verifier_value():
    """A committed rule publishes its commitment, never the answer."""
    contract = {"rules": [{"id": "R1", "check": {
        "kind": "json_path_equals_committed", "path": "$.total",
        "expected_commitment": "sha256:" + "0" * 64, "expected": 42}}]}
    summary = contract_summary(contract)
    assert "expected" not in summary["rules"][0]
    assert summary["rules"][0]["committed"] is True
    assert "42" not in json.dumps(summary)


# ------------------------------------------------- 28. Delivery serialization
def test_delivery_shape_is_recorded_not_performed():
    """submit_delivery passes the three parts through untouched."""
    captured = {}

    class FakeClient(AixClient):
        def _call(self, method, path, body=None, **kw):
            captured["body"] = body
            return {"assignment_id": "aix8_as_x", "status": "RESULT_SUBMITTED"}

    c = FakeClient("http://127.0.0.1:1")
    c.submit_delivery(
        "aix8_as_x",
        {"answer": "ok"},
        artifacts=[{"name": "r.pdf", "media_type": "application/pdf",
                    "size_bytes": 1, "sha256": "sha256:" + "0" * 64,
                    "uri": "https://example.invalid/r.pdf"}],
        external_actions=[{"action_type": "email_sent",
                           "target": "x@example.invalid",
                           "executed_at": 1.0, "proof": {"id": "m1"}}])
    delivery = captured["body"]["delivery"]
    assert delivery["structured_output"] == {"answer": "ok"}
    assert delivery["artifacts"][0]["name"] == "r.pdf"
    assert delivery["external_actions"][0]["proof"]["id"] == "m1"


def test_operations_extracted_from_openapi():
    spec = {"paths": {"/v1/balance": {"get": {}},
                       "/v1/offers": {"get": {}, "post": {}}}}
    assert operations(spec) == {"GET /v1/balance", "GET /v1/offers",
                                "POST /v1/offers"}
# ------------------------------------------------- 20. trust-hardening tests
@pytest.mark.parametrize("text,intent", [
    ("验证 AIX Skill", "VERIFY_AIX_SKILL"),
    ("verify aix skill", "VERIFY_AIX_SKILL"),
    ("安全信息", "SECURITY_INFO"),
    ("security information", "SECURITY_INFO"),
])
def test_trust_intents_are_reachable(text, intent):
    assert match_intent(text)["id"] == intent


def test_join_requires_explicit_consent():
    """§11 Joining must not happen without a deliberate yes."""
    s = _offline_skill()
    r = s.handle("join aix", display_name="x")
    assert r["ok"] is False
    assert r["action_required"] == "confirm_consent"
    assert r["registered"] is False
    assert s.client.agent_id is None


def test_consent_summary_states_what_will_not_happen():
    s = _offline_skill()
    summary = s.consent_summary("isolated_file")
    joined = " ".join(summary["will_not"])
    for phrase in ("Production", "seed phrase", "private key", "real money"):
        assert phrase in joined
    assert summary["credential"]["displayed_once"] is True


def test_install_has_no_economic_side_effect():
    """§10 start() must register nothing, claim nothing, create nothing."""
    s = _offline_skill()
    # Stub discovery: a unit test must not depend on a live network.
    s.client.discover = lambda: {"protocol": "AIX", "protocol_version": "0.8",
                                 "network": "AIX_V0_8_PREPRODUCTION",
                                 "environment": "preproduction",
                                 "production": False, "operations": 0}
    r = s.start()
    assert s.client.agent_id is None
    assert s.client._api_key is None
    assert r["identity"] == {"registered": False}
    assert s.store.agent_ids() == []


def test_new_user_guidance_puts_trust_before_economics():
    g = guidance("NOT_REGISTERED")
    assert g["recommended"]["intent"] == "VERIFY_AIX_SKILL"
    for a in ("VERIFY_AIX_SKILL", "SECURITY_INFO", "JOIN_AIX"):
        assert a in g["available"]


def test_network_host_allowlist_is_single_host():
    """§9 The credential must go to the AIX host and nowhere else."""
    tm = json.loads((pathlib.Path(__file__).resolve().parents[1] /
                     "AIX_SKILL_V0_1_TRUST_MANIFEST.json").read_text(encoding="utf-8"))
    assert tm["credential_hosts"] == ["https://beta.aixprotocol.org"]
    assert tm["external_network_hosts"] == ["https://beta.aixprotocol.org"]
    assert tm["production_access_required"] is False


def test_trust_manifest_refuses_money_and_wallet():
    tm = json.loads((pathlib.Path(__file__).resolve().parents[1] /
                     "AIX_SKILL_V0_1_TRUST_MANIFEST.json").read_text(encoding="utf-8"))
    for field in ("requires_wallet", "requires_seed_phrase",
                  "requires_wallet_private_key", "requires_payment",
                  "requires_real_money", "can_purchase_aix", "can_withdraw_aix"):
        assert tm[field] is False, field


def test_trust_manifest_does_not_claim_subprocess():
    tm = json.loads((pathlib.Path(__file__).resolve().parents[1] /
                     "AIX_SKILL_V0_1_TRUST_MANIFEST.json").read_text(encoding="utf-8"))
    assert tm["subprocess_usage"] is False
    assert tm["install_scripts"] == []


def test_keyring_is_preferred_and_fallback_disclosed():
    """§12 storage preference is keyring; the fallback is stated, not hidden."""
    s = _offline_skill()
    info = s.handle("security information")
    assert "OS keyring" in " ".join(info["credential_storage_tiers"])
    assert info["active_tier"] in ("os_keyring", "isolated_file", "memory")
    removal = info["removal"]
    assert "local_credential_state" in removal


def test_disconnect_removes_local_credential_state(tmp_path):
    s = _offline_skill()
    s.store._path = tmp_path / "c.json"
    s.store.save("aix8_ag_test", FAKE_KEY)
    assert s.store.agent_ids() == ["aix8_ag_test"]
    r = s.handle("退出 AIX")
    assert r["disconnected"] is True
    # v0.8 does expose revocation; deleting locally alone is not enough
    assert "撤销凭据" in r["note"]
    assert s.store.agent_ids() == []
    assert r["revoked"] is None  # local only unless revoke=True


def test_verify_action_is_read_only_and_says_no_wallet():
    s = _offline_skill()
    s.client.network = {"protocol": "AIX", "protocol_version": "0.8",
                        "environment": "preproduction", "production": False}
    s.client.discover = lambda: {"protocol": "AIX", "protocol_version": "0.8",
                                 "network": "AIX_V0_8_PREPRODUCTION",
                                 "environment": "preproduction",
                                 "production": False, "operations": 0}
    r = s.handle("verify aix skill")
    assert r["requires_wallet"] is False
    assert r["requires_seed_phrase"] is False
    assert r["requires_payment"] is False
    assert r["production_access"] is False
    assert s.client.agent_id is None  # verified without joining
    assert "SECURITY.md" in r["documents"]


def test_package_has_no_install_script_and_no_secrets():
    root = pathlib.Path(__file__).resolve().parents[1]
    names = {p.name for p in root.iterdir() if p.is_file()}
    for forbidden in ("setup.py", "install.sh", "install.bat", "requirements.txt"):
        assert forbidden not in names, forbidden
    for p in root.rglob("*"):
        if p.is_file() and "tests" not in p.parts:
            t = p.read_text(encoding="utf-8", errors="replace")
            assert "aix8_ck_" not in t
            assert "aix8_ag_ar" not in t  # a real agent id prefix, not the fixture


def _offline_skill(tmp_path=None):
    """A Skill wired to a store it will never persist from, for trust tests."""
    import tempfile as _tf
    st = CredentialStore("trust-test").file_store()
    st._path = pathlib.Path(_tf.mkdtemp()) / "c.json"
    sk = AixSkill("https://beta.aixprotocol.org", store=st)
    return sk
