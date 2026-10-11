"""Deterministic reliability tests for the defects found in real Agent use.

Everything here is offline: no network, no ledger, no credential. Ambiguity is
injected by making a fake transport fail in a chosen way, so a timeout on
"create" and a timeout on "claim" are reproducible facts rather than hopes.
"""
from __future__ import annotations

import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from aix_client import (AMBIGUOUS_OUTCOME, CLAIM_ALREADY_SUCCEEDED,  # noqa: E402
                        RECOVERED_SUCCESS, AixClient, AixError, AmbiguousOutcome,
                        _NewIdempotencyKey, _looks_like_connectivity_failure)
from aix_credentials import CredentialStore, probe_store  # noqa: E402
from aix_guidance import guidance  # noqa: E402
from aix_skill import AixSkill  # noqa: E402

FAKE_KEY = "fake_key_not_a_real_credential"


ROBOT_EXPECTED = (pathlib.Path(__file__).parents[1] / "welcome.txt").read_bytes().decode("utf-8")
APPROVED_HOME_SHA256 = "6bb74ae00f618dfa4b3c9cf2daee763339f5d91d760d434267478905781446a8"


def test_robot_install_and_menu_exact():
    from aix_welcome import render_welcome, install_final_response
    assert render_welcome("install") == ROBOT_EXPECTED
    menu = ROBOT_EXPECTED.replace("      ✦ 安装完成，欢迎入场 ✦", "      ✦ 欢迎回来，选择操作 ✦")
    assert render_welcome("menu") == menu
    facts = dict(zip_verified=True, manifest_verified=True, files_verified=True,
                 extracted=True, discovered=True, loaded=True, validation_completed=True)
    assert install_final_response(**facts).startswith("```text\n" + ROBOT_EXPECTED + "```")


@pytest.mark.parametrize("gate", ["zip_verified", "manifest_verified", "files_verified",
    "extracted", "discovered", "loaded", "validation_completed", "reload_required", "restart_required"])
def test_robot_incomplete_never_success(gate):
    from aix_welcome import install_final_response
    facts = dict(zip_verified=True, manifest_verified=True, files_verified=True,
                 extracted=True, discovered=True, loaded=True, validation_completed=True)
    facts[gate] = gate.endswith("required")
    reply = install_final_response(**facts)
    assert "安装完成" not in reply and "--HIRES-->" not in reply
    assert "STATUS" in reply and "REASON" in reply and "NEXT ACTION" in reply


@pytest.mark.parametrize("command", ["帮助", "菜单", "AIX 帮助"])
def test_robot_help_final_menu_exact_and_zero_mutation(tmp_path, command):
    s = boundary_skill(tmp_path)
    s.client._call = lambda *a, **kw: pytest.fail("help contacted protocol")
    s.client.register = lambda *a, **kw: pytest.fail("help registered")
    result = s.handle(command)
    expected = ROBOT_EXPECTED.replace("      ✦ 安装完成，欢迎入场 ✦", "      ✦ 欢迎回来，选择操作 ✦")
    assert result["final_response"] == "```text\n" + expected + "```"


def test_robot_menu_entries_use_real_read_flows(tmp_path):
    s = boundary_skill(tmp_path, authenticated=True)
    seen = []
    def read(method, path, *a, **kw):
        assert method == "GET"
        seen.append(path)
        if path == "/v1/balance":
            return {"balance": "8", "escrow_active": "2", "currency": "AIX"}
        return {"offers": []}
    s.client._call = read
    s.client.claim_task = lambda *a: pytest.fail("browse auto-Claim")
    assert s.handle("接任务")["total"] == 0
    assert "/v1/offers" in seen
    result = s.handle("我的余额")
    assert result["balance"] == "8"
    assert "8" in result["final_response"]
    assert "2" in result["final_response"]
    assert s.handle("查看任务")["action_required"] == "select_task_role"


def test_robot_create_menu_does_not_publish_or_invent_fields(tmp_path):
    s = boundary_skill(tmp_path, authenticated=True)
    s.client.create_task = lambda *a, **kw: pytest.fail("menu created Offer")
    result = s.handle("发任务")
    assert result["action_required"] == "provide_task_details"
    assert "reward" in result["missing"] and "rules" in result["missing"]
    assert result["claim_window_seconds"] == 86400
    result = s.handle("发任务", task_spec={"title": "t"}, reward="2", rules=[{"id": "R1"}], claim_window_seconds=21600)
    assert result["action_required"] == "explicit_publish_intent"
    assert result["claim_window_seconds"] == 21600


def test_robot_diagnostic_sanitized_and_unknown_truthful(tmp_path):
    s = boundary_skill(tmp_path)
    result = s.handle("安装诊断")
    assert result["installation_status"] == "UNKNOWN"
    assert result["integrity_status"] == "NOT_VERIFIED"
    assert result["credential_available"] is False
    assert FAKE_KEY not in json.dumps(result)


@pytest.mark.parametrize("operation", ["fresh", "reinstall", "update"])
def test_robot_install_render_preserves_native_user_state(tmp_path, operation):
    from aix_welcome import install_final_response
    store = boundary_skill(tmp_path).store
    store.save("fake_existing_agent", FAKE_KEY)
    config = tmp_path / "adapter.json"
    config.write_text('{"preferences":"preserve"}', encoding="utf-8")
    tracked = [store._path, store._path.with_name(store._path.name + ".identity.json"), config]
    before = {p: p.read_bytes() for p in tracked}
    install_final_response(zip_verified=True, manifest_verified=True, files_verified=True,
                           extracted=True, discovered=True, loaded=True, validation_completed=True)
    assert {p: p.read_bytes() for p in tracked} == before
    assert store.load("fake_existing_agent") == FAKE_KEY


@pytest.mark.parametrize("command", ["接任务", "发任务", "查看任务", "我的余额", "帮助", "菜单", "安装诊断"])
@pytest.mark.parametrize("authenticated", [False, True])
def test_robot_menu_mutation_sentinel(tmp_path, command, authenticated):
    s = boundary_skill(tmp_path, authenticated)
    counts = {}
    for name in ("register", "claim_initial_aix", "create_task", "claim_task",
                 "submit_delivery", "review_delivery", "rotate_credential", "revoke_credential", "_mutate", "transfer"):
        counts[name] = 0
        def forbidden(*a, _name=name, **kw):
            counts[_name] += 1
            raise AssertionError(_name)
        setattr(s.client, name, forbidden)
    s.handle(command, consent=True)
    assert all(value == 0 for value in counts.values())


def test_robot_known_worker_view_includes_submission_settlement_readonly(tmp_path):
    s = boundary_skill(tmp_path, True)
    s.client.remember_assignment("fake_assignment", "worker")
    def read(method, path, *a, **kw):
        assert method == "GET"
        if path.endswith("submission"):
            return {"structured_output": {"answer": "done"}}
        return {"assignment_id": "fake_assignment", "status": "SETTLED", "settlement": {"amount": "2"}}
    s.client._call = read
    result = s.handle("查看任务")
    assert result["items"][0]["assignment"]["status"] == "SETTLED"
    assert result["items"][0]["submission"]["structured_output"]["answer"] == "done"


def test_robot_known_creator_closed_offer_remains_inspectable(tmp_path):
    s = boundary_skill(tmp_path, True)
    s.client.remember_offer("fake_closed_offer")
    def read(method, path, *a, **kw):
        assert method == "GET"
        return {"offers": []} if path == "/v1/offers" else {"offer_id": "fake_closed_offer", "status": "CLOSED"}
    s.client._call = read
    assert s.handle("查看任务")["items"][0]["status"] == "CLOSED"


def test_robot_missing_balance_bucket_is_unknown_not_zero(tmp_path):
    s = boundary_skill(tmp_path, True)
    assert "UNKNOWN" in s.handle("我的余额")["final_response"]


def test_robot_diagnostics_never_print_synthetic_credential(tmp_path):
    s = boundary_skill(tmp_path, True)
    s.store.save("fake_existing_agent", FAKE_KEY)
    result = s.handle("安装诊断")
    assert result["credential_available"] is True
    assert FAKE_KEY not in json.dumps(result)


def test_robot_unknown_install_facts_are_not_truthy_success():
    from aix_welcome import install_final_response
    assert "安装完成" not in install_final_response(zip_verified="YES")


def test_robot_resource_zip_roundtrip_exact(tmp_path):
    import zipfile
    data = pathlib.Path(__file__).resolve().parents[1].joinpath("welcome.txt").read_bytes()
    assert data == ROBOT_EXPECTED.encode("utf-8")
    archive = tmp_path / "test.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("AIX-Skill-v0.1/welcome.txt", data)
    with zipfile.ZipFile(archive) as z:
        assert z.read("AIX-Skill-v0.1/welcome.txt") == data
        z.extractall(tmp_path / "extracted")
    assert (tmp_path / "extracted/AIX-Skill-v0.1/welcome.txt").read_bytes() == data


def test_robot_diagnostic_locked_store_is_sanitized_unknown(tmp_path):
    s = boundary_skill(tmp_path)
    s.store.agent_ids = lambda: ["fake_existing_agent"]
    def locked(*a):
        raise RuntimeError(FAKE_KEY)
    s.store.load = locked
    result = s.handle("安装诊断")
    assert result["credential_available"] == "UNKNOWN"
    assert FAKE_KEY not in json.dumps(result)


def test_robot_diagnostic_malformed_manifest_is_unknown(tmp_path, monkeypatch):
    s = boundary_skill(tmp_path)
    original = pathlib.Path.read_text
    def malformed(path, *a, **kw):
        if path.name == "AIX_SKILL_V0_1_RELEASE_MANIFEST.json":
            return "[]"
        return original(path, *a, **kw)
    monkeypatch.setattr(pathlib.Path, "read_text", malformed)
    assert s.handle("安装诊断")["build_id"] is None


@pytest.mark.parametrize("window,expected", [(None, 86400), (3600, 3600),
                                            (21600, 21600), (259200, 259200),
                                            (604800, 604800)])
def test_claim_window_sent_without_changing_reward_or_contract(window, expected):
    client = AixClient("https://example.invalid")
    calls = []
    def mutate(operation, method, path, body, **kw):
        calls.append(body)
        return 201, {"offer_id": "fake_offer", "reward": "2", "escrow_amount": "2",
                     "acceptance_contract": {"acceptance_contract_id": "fake_contract"}}
    client._mutate = mutate
    result = client.create_task({"title": "t"}, "2", [{"id": "R1"}],
                                claim_window_seconds=window)
    assert len(calls) == 1
    assert calls[0]["claim_window_seconds"] == expected
    assert calls[0]["reward"] == "2" and calls[0]["rules"] == [{"id": "R1"}]
    assert result["escrow_amount"] == "2"
    assert result["acceptance_contract"]["acceptance_contract_id"] == "fake_contract"


@pytest.mark.parametrize("window", [0, -1, "oops", "3600", 1.5, True, False, [], float("inf")])
def test_claim_window_invalid_rejected_before_mutation(window):
    client = AixClient("https://example.invalid")
    client._mutate = lambda *a, **kw: pytest.fail("invalid window mutated")
    with pytest.raises(AixError) as error:
        client.create_task({}, "2", [], claim_window_seconds=window)
    assert error.value.code == "INVALID_CLAIM_WINDOW"


@pytest.mark.parametrize("window,seconds", [(None, 86400), (3600, 3600)])
def test_claim_window_creator_sees_server_deadline(tmp_path, window, seconds):
    s = boundary_skill(tmp_path, authenticated=True)
    sent = []
    def mutate(operation, method, path, body, **kw):
        sent.append(body)
        return 201, {"offer_id": "fake_offer", "reward": "2", "claim_deadline": 1791360000}
    s.client._mutate = mutate
    result = s._i_create_task(task_spec={"title": "t"}, reward="2",
                      claim_window_seconds=window, rules=[{'id':'R1','requirement':'answer',
                          'check':{'kind':'json_path_exists','path':'$.answer'}}])
    assert sent[0]["claim_window_seconds"] == seconds
    assert result["claim_window_seconds"] == seconds
    assert result["CLAIM_DEADLINE"] == 1791360000
    assert result["claim_deadline_utc"].endswith("Z")
    assert result["CLAIM_WINDOW"]


def test_claim_window_timeout_never_replays_mutation():
    c = FakeClient("/v1/offers", AixError(0, {"code": "NETWORK_UNREACHABLE"}))
    c.gets = {"/v1/offers": {"offers": [{"offer_id": "fake_offer",
        "creator_agent_id": c.agent_id, "reward": "2", "status": "OPEN",
        "task_spec": {"title": "t"}, "created_at": 1000, "claim_deadline": 87400}]}}
    assert c.create_task({"title": "t"}, "2", [], claim_window_seconds=86400)["recovered"]
    assert c.calls.count("POST /v1/offers") == 1


def test_claim_window_recovery_does_not_adopt_different_duration():
    c = FakeClient("/v1/offers", AixError(0, {"code": "NETWORK_UNREACHABLE"}))
    c.gets = {"/v1/offers": {"offers": [{"offer_id": "fake_old_offer",
        "creator_agent_id": c.agent_id, "reward": "2", "status": "OPEN",
        "task_spec": {"title": "t"}, "created_at": 1000, "claim_deadline": 4600}]}}
    with pytest.raises(AmbiguousOutcome):
        c.create_task({"title": "t"}, "2", [], claim_window_seconds=86400)
    assert c.calls.count("POST /v1/offers") == 1


def test_claim_window_large_deadline_does_not_hide_successful_creation(tmp_path):
    s = boundary_skill(tmp_path, authenticated=True)
    calls = []
    def mutate(operation, method, path, body, **kw):
        calls.append(body)
        return 201, {"offer_id": "fake_offer", "claim_deadline": 10**12}
    s.client._mutate = mutate
    result = s._i_create_task(claim_window_seconds=10**12,
                     rules=[{'id':'R1','requirement':'answer',
                             'check':{'kind':'json_path_exists','path':'$.answer'}}])
    assert result["created"] is True and result["CLAIM_DEADLINE"] == 10**12
    assert result["claim_deadline_utc"] is None
    assert result["claim_deadline_display_status"] == "OUTSIDE_DATETIME_RANGE"
    assert len(calls) == 1


@pytest.mark.parametrize("deadline", [None, "invalid", float("nan"), float("inf")])
def test_claim_window_recovery_requires_usable_deadline(deadline):
    c = FakeClient("/v1/offers", AixError(0, {"code": "NETWORK_UNREACHABLE"}))
    c.gets = {"/v1/offers": {"offers": [{"offer_id": "fake_offer",
        "creator_agent_id": c.agent_id, "reward": "2", "status": "OPEN",
        "task_spec": {"title": "t"}, "created_at": 1000, "claim_deadline": deadline}]}}
    with pytest.raises(AmbiguousOutcome):
        c.create_task({"title": "t"}, "2", [], claim_window_seconds=86400)
    assert c.calls.count("POST /v1/offers") == 1


@pytest.fixture(autouse=True)
def isolated_boundary_storage(tmp_path, monkeypatch):
    # Existing fallback protection must never inspect the test runner's home.
    monkeypatch.setenv("AIX_SKILL_CREDENTIAL_FILE", str(tmp_path / "fallback.json"))

# Permanent read-intent mutation sentinel. All transport here is synthetic.
READ_PHRASES = ["\u67e5\u770b\u6211\u7684\u4efb\u52a1", "\u67e5\u770b\u4efb\u52a1", "\u67e5\u770b\u4f59\u989d", "\u67e5\u770b\u8fdb\u5ea6",
                "\u6709\u4ec0\u4e48\u4efb\u52a1\u53ef\u4ee5\u63a5", "\u627e\u4efb\u52a1", "\u67e5\u770b\u5f85\u9a8c\u6536", "AIX \u5e2e\u52a9",
                "\u9a8c\u8bc1 AIX Skill", "\u5b89\u5168\u4fe1\u606f"]


def boundary_skill(tmp_path, authenticated=False):
    store = CredentialStore("boundary")
    store._backend = "isolated_file"
    store._path = tmp_path / "credential.json"
    store.file_store = lambda: store
    s = AixSkill(store=store)
    s.client.discover = lambda: {}
    if authenticated:
        s.client.agent_id = "fake_agent_boundary"
        s.client._api_key = FAKE_KEY
    def read(method, path, *args, **kw):
        assert method == "GET", "read intent reached a mutation transport"
        return {"agent_id": "fake_agent_boundary", "balance": 0,
                "offers": [], "assignments": []}
    s.client._call = read
    return s


@pytest.mark.parametrize("phrase", READ_PHRASES)
@pytest.mark.parametrize("authenticated", [False, True])
def test_boundary_read_mutation_sentinel(tmp_path, phrase, authenticated):
    s = boundary_skill(tmp_path, authenticated)
    counts = {}
    for name in ("register", "claim_initial_aix", "create_task", "claim_task",
                 "submit_delivery", "review_delivery", "rotate_credential",
                 "revoke_credential", "_mutate"):
        counts[name] = 0
        def forbidden(*a, _name=name, **kw):
            counts[_name] += 1
            raise AssertionError(_name)
        setattr(s.client, name, forbidden)
    result = s.handle(phrase, consent=True)
    assert all(n == 0 for n in counts.values())
    assert result["authorization_boundary"]["SUGGESTION_IS_NOT_AUTHORIZATION"] is True
    if (not authenticated and phrase not in READ_PHRASES[-3:]
            and phrase not in ("\u627e\u4efb\u52a1", "\u6709\u4ec0\u4e48\u4efb\u52a1\u53ef\u4ee5\u63a5")):
        assert result["status"] == "AUTH_REQUIRED"
        assert result["stop"] is True


def test_unregistered_find_work_reads_public_market_without_mutation(tmp_path):
    s = boundary_skill(tmp_path)
    calls = []
    s.client.find_work = lambda **kw: calls.append(kw) or {"total": 0, "offers": []}
    result = s.handle("\u627e\u4efb\u52a1")
    assert result["ok"] is True
    assert result["intent"] == "FIND_WORK"
    assert result["total"] == 0
    assert result["final_response"] == "\u5f53\u524d\u6ca1\u6709\u53ef\u9886\u53d6\u4efb\u52a1\u3002"
    assert calls == [{"limit": 10}]
    assert s.client.agent_id is None
    assert s.client._api_key is None


def test_find_work_client_marks_public_list_request_anonymous(monkeypatch):
    client = AixClient("https://beta.aixprotocol.org")
    requests = []

    def request(method, path, body=None, **kwargs):
        requests.append((method, path, kwargs))
        return 200, {"offers": [], "total": 0}

    monkeypatch.setattr(client, "_request", request)
    assert client.find_work(limit=10) == {"total": 0, "offers": []}
    assert len(requests) == 1
    assert requests[0][0:2] == ("GET", "/v1/offers")
    assert requests[0][2]["auth"] is False


def test_settlement_status_language_routes_to_native_task_progress():
    from aix_guidance import match_intent

    assert match_intent("\u67e5\u770b\u9a8c\u6536\u548c\u7ed3\u7b97\u72b6\u6001")["id"] == "TASK_PROGRESS"


def test_anonymous_market_fix_does_not_authorize_claim(tmp_path):
    s = boundary_skill(tmp_path)
    calls = []

    def authenticated_only(method, path, body=None, **kwargs):
        calls.append((method, path, kwargs.get("auth", True)))
        raise AixError(401, {"code": "UNAUTHORIZED"})

    s.client._call = lambda method, path, body=None, **kwargs: AixClient._call(
        s.client, method, path, body, **kwargs)
    s.client._request = authenticated_only
    result = s.handle("\u63a5\u8fd9\u4e2a\u4efb\u52a1")
    assert result["ok"] is False
    assert result["code"] == "UNAUTHORIZED"
    assert len(calls) == 1
    assert calls[0][0] == "GET"
    assert calls[0][2] is True


def test_boundary_known_missing_credential_stops_join(tmp_path):
    s = boundary_skill(tmp_path)
    s.store.save("fake_previous_agent", FAKE_KEY)
    s.store._path.unlink()
    replacement = CredentialStore("boundary")
    replacement._backend = "isolated_file"
    replacement._path = s.store._path
    s = AixSkill(store=replacement)
    s.client.register = lambda *a, **kw: pytest.fail("replacement registration")
    result = s.handle("加入 AIX", consent=True)
    assert result["status"] == "CREDENTIAL_UNAVAILABLE"
    assert result["agent_id"] == "fake_previous_agent"
    assert result["stop"] is True


def test_boundary_existing_identity_join_is_noop(tmp_path):
    s = boundary_skill(tmp_path, True)
    s.client.register = lambda *a, **kw: pytest.fail("duplicate identity")
    result = s.handle("加入 AIX", consent=True)
    assert result["already_registered"] is True
    assert result["stop"] is True


@pytest.mark.parametrize("text", ["下一步可以领取 AIX", "怎么获得aix",
                                 "建议加入 AIX", "不要加入 AIX"])
def test_boundary_suggestion_is_not_current_authorization(tmp_path, text):
    s = boundary_skill(tmp_path, True)
    s.client.register = lambda *a, **kw: pytest.fail("suggestion registered")
    s.client.claim_initial_aix = lambda: pytest.fail("suggestion bootstrapped")
    assert s.handle(text, consent=True)["code"] == "EXPLICIT_CURRENT_INTENT_REQUIRED"


def test_boundary_bootstrap_requires_scoped_current_intent(tmp_path):
    s = boundary_skill(tmp_path, True)
    calls = []
    s.client.claim_initial_aix = lambda: calls.append("bootstrap") or {"balance": 10}
    assert s._i_claim_aix()["code"] == "EXPLICIT_CURRENT_INTENT_REQUIRED"
    for text in ("领取 AIX", "领取初始 AIX", "领取启动额度"):
        assert s.handle(text, consent=True)["ok"] is True
    assert calls == ["bootstrap"] * 3


def test_boundary_join_stops_before_recommendation(tmp_path):
    s = boundary_skill(tmp_path)
    calls = []
    def register(*a, **kw):
        calls.append("register")
        s.client.agent_id = "fake_agent_boundary"
        s.client._api_key = FAKE_KEY
        return {"agent_id": s.client.agent_id}
    s.client.register = register
    s.client.claim_initial_aix = lambda: pytest.fail("Join recommendation executed")
    result = s.handle("加入 AIX", consent=True)
    assert calls == ["register"]
    assert result["stop"] is True
    assert result["next"]["recommended"]["intent"] == "CLAIM_AIX"
    assert result["next"]["SUGGESTION_IS_NOT_AUTHORIZATION"] is True
    assert result["credential_storage"]["PERSISTENCE_VERIFIED"] is True
    assert result["credential_storage"]["CREDENTIAL_LOCATION_CLASS"] == "runtime_selected_isolated_file"


def test_boundary_current_read_cannot_reuse_join_scope(tmp_path):
    s = boundary_skill(tmp_path)
    for text in ("查看我的任务", "查看余额"):
        result = s.handle(text, consent=True, _authorized_intent="JOIN_AIX")
        assert result["status"] == "AUTH_REQUIRED"


def test_boundary_native_known_identity_hint(tmp_path):
    s = boundary_skill(tmp_path)
    s.client.agent_id = "fake_previous_agent"
    assert s.handle("查看我的任务")["agent_id"] == "fake_previous_agent"
    assert s.handle("加入 AIX", consent=True)["status"] == "CREDENTIAL_UNAVAILABLE"
    assert s.handle("continue", consent=True)["status"] == "CREDENTIAL_UNAVAILABLE"


@pytest.mark.parametrize("payload", ["not-json", "{}", "[42]"])
def test_boundary_corrupt_identity_hint_fails_closed(tmp_path, payload):
    s = boundary_skill(tmp_path)
    hint = s.store._path.with_name(s.store._path.name + ".identity.json")
    hint.write_text(payload, encoding="utf-8")
    s.client.register = lambda *a, **kw: pytest.fail("corrupt metadata registered")
    assert s.handle("加入 AIX", consent=True)["status"] == "CREDENTIAL_UNAVAILABLE"


def test_boundary_keyring_identity_index_reloads_without_registration(tmp_path):
    from types import SimpleNamespace
    s = boundary_skill(tmp_path)
    values = {}
    s.store._backend = "os_keyring"
    s.store._keyring = SimpleNamespace(
        set_password=lambda service, name, value: values.__setitem__(name, value),
        get_password=lambda service, name: values.get(name),
        delete_password=lambda service, name: values.pop(name, None))
    s.store.save("fake_keyring_agent", FAKE_KEY)
    s.client.register = lambda *a, **kw: pytest.fail("duplicate keyring identity")
    assert s.handle("加入 AIX", consent=True)["already_registered"] is True
    s.client._api_key = None
    values.pop("fake_keyring_agent")
    assert s.handle("加入 AIX", consent=True)["status"] == "CREDENTIAL_UNAVAILABLE"


@pytest.mark.parametrize("text", ["查看我的任务：发布任务", "查看任务详情：提交工作",
                                 "有什么任务可以接：接这个任务", "看交付 发布一个任务",
                                 "help publish a task"])
def test_boundary_read_prefix_cannot_become_mutation(tmp_path, text):
    s = boundary_skill(tmp_path)
    result = s.handle(text, consent=True)
    assert result["intent"] in ("MY_TASKS", "READ_TASK", "FIND_WORK", "READ_DELIVERY", "HELP")
    assert result["authorization_boundary"]["READ_IMPLIES_MUTATION"] is False


def test_boundary_direct_join_boolean_is_not_scope(tmp_path):
    s = boundary_skill(tmp_path)
    assert s._i_join_aix(consent=True)["code"] == "EXPLICIT_CURRENT_INTENT_REQUIRED"


def test_boundary_store_probe_does_not_leave_identity_hint(tmp_path):
    s = boundary_skill(tmp_path)
    assert probe_store(s.store)[0] is True
    assert s.store.agent_ids() == []
    assert not s.store._path.with_name(s.store._path.name + ".identity.json").exists()


@pytest.mark.parametrize("raw", ["corrupt", "{}", "[42]", "unavailable"])
def test_boundary_keyring_metadata_failure_stops_join(tmp_path, raw):
    from types import SimpleNamespace
    s = boundary_skill(tmp_path)
    s.store._backend = "os_keyring"
    fallback = boundary_skill(tmp_path / "fallback").store
    s.store.file_store = lambda: fallback
    def read(*a):
        if raw == "unavailable":
            raise RuntimeError("locked keyring")
        return raw
    s.store._keyring = SimpleNamespace(get_password=read)
    assert s.handle("加入 AIX", consent=True)["status"] == "CREDENTIAL_UNAVAILABLE"


@pytest.mark.parametrize("missing", [False, True])
@pytest.mark.parametrize("backend", ["os_keyring", "isolated_file"])
def test_boundary_previous_file_fallback_identity_protected(tmp_path, missing, backend):
    from types import SimpleNamespace
    s = boundary_skill(tmp_path)
    fallback = boundary_skill(tmp_path / "fallback").store
    fallback.save("fake_fallback_agent", FAKE_KEY)
    if missing:
        fallback._path.unlink()
    s.store._backend = backend
    s.store._keyring = SimpleNamespace(get_password=lambda *a: None)
    s.store.file_store = lambda: fallback
    s.client.register = lambda *a, **kw: pytest.fail("fallback identity replaced")
    result = s.handle("加入 AIX", consent=True)
    if missing:
        assert result["status"] == "CREDENTIAL_UNAVAILABLE"
    else:
        assert result["already_registered"] is True
    assert s.client.store is fallback


def skill(tmp_path=None) -> AixSkill:
    import tempfile
    store = CredentialStore("rel").file_store()
    store._path = pathlib.Path(tempfile.mkdtemp()) / "c.json"
    return AixSkill("https://beta.aixprotocol.org", store=store)


# --------------------------------------------- A. credential storage preflight
def test_keyring_absent_falls_back_to_file(tmp_path):
    store = CredentialStore("a")
    store._backend = "isolated_file"
    store._path = tmp_path / "cred.json"
    ok, detail = probe_store(store)
    assert ok, detail


def test_keyring_imported_but_backend_unavailable_is_a_false_positive(tmp_path):
    """The observed defect: the package imports, nothing works behind it."""
    store = CredentialStore("a")
    store._backend = "os_keyring"
    store._path = tmp_path / "cred.json"

    def boom(*a, **k):
        raise RuntimeError("No recommended backend was available")

    store.save = boom
    ok, detail = probe_store(store)
    assert ok is False
    assert "os_keyring" in detail


def test_keyring_write_succeeds_but_read_fails(tmp_path):
    store = CredentialStore("a")
    store._backend = "isolated_file"
    store._path = tmp_path / "cred.json"
    calls = {"n": 0}
    real_load = store.load

    def flaky(agent_id):
        calls["n"] += 1
        return "wrong" if calls["n"] == 1 else real_load(agent_id)

    store.load = flaky
    ok, detail = probe_store(store)
    assert ok is False and "read-back mismatch" in detail


def test_keyring_delete_does_not_take_effect(tmp_path):
    store = CredentialStore("a")
    store._backend = "isolated_file"
    store._path = tmp_path / "cred.json"
    store.forget = lambda agent_id: None
    ok, detail = probe_store(store)
    assert ok is False and "delete" in detail


def test_fallback_preflight_prepares_parent_and_permissions(tmp_path):
    store = CredentialStore("a").file_store()
    store._path = tmp_path / "nested" / "deep" / "cred.json"
    store.prepare_file_path()
    assert store._path.parent.is_dir()
    if sys.platform != "win32":
        assert store._path.parent.stat().st_mode & 0o777 == 0o700
    assert not store._path.exists()
    ok, _ = probe_store(store)
    assert ok
    assert not store._path.exists()


def test_registration_refused_before_store_ready():
    c = AixClient("https://beta.aixprotocol.org")
    with pytest.raises(AixError) as exc:
        c.register("x", store_ready=False)
    assert exc.value.code == "CREDENTIAL_STORE_NOT_READY"


def test_post_register_uses_same_credential_on_fallback(monkeypatch):
    """A broken keyring must not cause a second registration."""
    s = skill()
    c = s.client
    c.agent_id = "aix8_ag_real"
    c._api_key = "the-one-real-credential"
    preferred = c.store
    preferred.save = lambda *a, **k: (_ for _ in ()).throw(
        RuntimeError("keyring exploded"))

    class Store(CredentialStore):
        def save(self, agent_id, api_key):
            self.saved = (agent_id, api_key)
            super().save(agent_id, api_key)

    fallback = Store.__new__(Store)
    fallback.profile = "rel"
    fallback._backend = "isolated_file"
    fallback._memory = {}
    fallback._keyring = None
    import tempfile
    fallback._path = pathlib.Path(tempfile.mkdtemp()) / "f.json"
    fallback.save(  # monkeypatch capture below
        lambda *a, **k: None) if False else None
    fallback_store = fallback
    with monkeypatch.context() as patch:
        patch.setattr(type(c.store), "file_store", lambda self: fallback_store)
        c.identity = lambda: {"agent_id": c.agent_id}
        result = c.store_credential()
    assert result["stored"] is True
    assert fallback_store.saved[1] == "the-one-real-credential"
    assert fallback_store.load("aix8_ag_real") == "the-one-real-credential"


# -------------------------------------------- B. mutation ambiguity handling
class FakeClient(AixClient):
    """Records calls and injects a failure on the first POST to a path."""

    def __init__(self, fail_path: str, exc: Exception, **kw):
        super().__init__("https://beta.aixprotocol.org", **kw)
        self.agent_id = "aix8_ag_self"
        self._api_key = FAKE_KEY
        self.calls: list[str] = []
        self.fail_path = fail_path
        self.exc = exc
        # Track POSTs only: a read that happens before the mutation must not
        # consume the one failure we meant to inject.
        self.failed_once = False
        self.gets: dict[str, Any] = {}

    def _call(self, method, path, body=None, **kw):
        if method == "POST" and self.fail_path in path and not self.failed_once:
            self.failed_once = True
            self.calls.append(f"POST {path}")
            raise self.exc
        self.calls.append(f"{method} {path}")
        if method == "POST":
            return {"offer_id": "aix8_of_new", "assignment_id": "aix8_as_new",
                    "api_key": "rotated", "status": "OK"}
        return self.gets.get(path, {})


from typing import Any  # noqa: E402


def test_create_offer_timeout_does_not_retry_blindly():
    c = FakeClient("/v1/offers", AixError(0, {"code": "NETWORK_UNREACHABLE",
                                              "message": "timeout"}))
    c.gets = {"/v1/offers": {"offers": []}}
    with pytest.raises(AmbiguousOutcome):
        c.create_task({"title": "t"}, "2", [])
    posts = [x for x in c.calls if x.startswith("POST /v1/offers")]
    assert len(posts) == 1, c.calls
    assert c.calls.count("GET /v1/offers") == 1  # reconciled, not replayed


def test_create_offer_timeout_after_commit_recovers_single_offer():
    c = FakeClient("/v1/offers", AixError(0, {"code": "NETWORK_UNREACHABLE"}))
    c.gets = {"/v1/offers": {"offers": [
        {"offer_id": "aix8_of_mine", "creator_agent_id": "aix8_ag_self",
         "reward": "2", "status": "OPEN",
         "task_spec": {"title": "t"}, "created_at": 1000, "claim_deadline": 87400}]}}
    out = c.create_task({"title": "t"}, "2", [])
    assert out["outcome"] == RECOVERED_SUCCESS
    assert len([x for x in c.calls if x.startswith("POST /v1/offers")]) == 1


def _self_owned_assignment():
    """The v0.8 documents, exactly as the node publishes them.

    The offer carries the assignment id inside its slot and NEVER an owner
    field; the owner is on the assignment record. These fixtures used to put
    ``worker_agent_id`` on the offer, which the node never sends -- so they
    passed while the real recovery path was broken.
    """
    return {"/v1/offers/o1": {"offer_id": "o1",
                              "slots": [{"slot_index": 0, "state": "CLAIMED",
                                         "assignment_id": "aix8_as_mine"}]},
            "/v1/assignments/aix8_as_mine": {"assignment_id": "aix8_as_mine",
                                             "worker_agent_id": "aix8_ag_self",
                                             "status": "CLAIMED"}}


def test_claim_timeout_recovers_self_owned_assignment():
    c = FakeClient("/claim", AixError(0, {"code": "NETWORK_UNREACHABLE"}))
    c.gets = _self_owned_assignment()
    out = c.claim_task("o1")
    assert out["outcome"] == RECOVERED_SUCCESS
    assert out["assignment_id"] == "aix8_as_mine"
    assert out["state"] == CLAIM_ALREADY_SUCCEEDED
    assert out["worker_agent_id"] == "aix8_ag_self"


def test_claim_conflict_owner_self_is_not_reported_as_lost():
    c = FakeClient("/claim", AixError(409, {"code": "CLAIM_CONFLICT"}))
    c.gets = _self_owned_assignment()
    out = c.claim_task("o1")
    assert out["recovered"] is True
    assert out["state"] == CLAIM_ALREADY_SUCCEEDED


def test_offer_never_publishes_an_owner_field():
    """Guards the defect itself: ownership may only come from the assignment."""
    c = FakeClient("/claim", AixError(409, {"code": "CLAIM_CONFLICT"}))
    c.gets = {"/v1/offers/o1": {"offer_id": "o1",
                                "worker_agent_id": "aix8_ag_self",
                                "assignment_id": "aix8_as_mine"}}
    assert c.recover_claim("o1") is None, \
        "an owner field on the offer must not be believed: the protocol does " \
        "not publish one, and believing it would report a lost race as a win"


def test_released_assignment_is_not_recovered_as_a_live_claim():
    c = FakeClient("/claim", AixError(409, {"code": "CLAIM_CONFLICT"}))
    c.gets = {"/v1/offers/o1": {"offer_id": "o1",
                                "slots": [{"slot_index": 0, "state": "RELEASED",
                                           "assignment_id": "aix8_as_old"}]},
              "/v1/assignments/aix8_as_old": {"assignment_id": "aix8_as_old",
                                              "worker_agent_id": "aix8_ag_self",
                                              "status": "RELEASED"}}
    assert c.recover_claim("o1") is None, \
        "a released assignment is history, not a claim to resume"


def test_claim_conflict_owner_other_really_is_lost():
    c = FakeClient("/claim", AixError(409, {"code": "CLAIM_CONFLICT"}))
    c.gets = {"/v1/offers/o1": {"offer_id": "o1",
                                "slots": [{"slot_index": 0, "state": "CLAIMED",
                                           "assignment_id": "aix8_as_theirs"}]},
              "/v1/assignments/aix8_as_theirs": {
                  "assignment_id": "aix8_as_theirs",
                  "worker_agent_id": "aix8_ag_other", "status": "CLAIMED"}}
    with pytest.raises(AixError) as exc:
        c.claim_task("o1")
    assert exc.value.code == "CLAIM_CONFLICT"
    assert "其他 Agent" in exc.value.message


@pytest.mark.parametrize("server_code", ["SLOT_UNAVAILABLE", "EXPECTED_CONFLICT"])
def test_real_lost_race_codes_are_reported_as_claim_conflict(server_code):
    c = FakeClient("/claim", AixError(409, {"code": server_code}))
    c.gets = {"/v1/offers/o1": {"offer_id": "o1", "slots": []}}
    with pytest.raises(AixError) as exc:
        c.claim_task("o1")
    assert exc.value.code == "CLAIM_CONFLICT"


@pytest.mark.parametrize("server_code", ["CLAIM_DEADLINE_PASSED",
                                         "IDEMPOTENCY_KEY_CONFLICT",
                                         "ILLEGAL_STATE_TRANSITION"])
def test_other_409s_are_not_misreported_as_taken_by_another_agent(server_code):
    """A passed claim deadline is also a 409; it is not someone else's claim."""
    c = FakeClient("/claim", AixError(409, {"code": server_code,
                                            "message": "server reason"}))
    c.gets = {"/v1/offers/o1": {"offer_id": "o1", "slots": []}}
    with pytest.raises(AixError) as exc:
        c.claim_task("o1")
    assert exc.value.code == server_code
    assert "其他 Agent" not in exc.value.agent_message()


def test_claim_deadline_message_tells_the_agent_what_to_do():
    message = AixError(409, {"code": "CLAIM_DEADLINE_PASSED"}).agent_message()
    assert "截止" in message and "其他任务" in message
    assert "[code=CLAIM_DEADLINE_PASSED]" in message


def test_submit_timeout_recovers_committed_delivery():
    c = FakeClient("/result", AixError(0, {"code": "NETWORK_UNREACHABLE"}))
    c.gets = {"/v1/assignments/a1/submission": {"assignment_id": "a1"}}
    out = c.submit_delivery("a1", {"answer": "ok"})
    assert out["outcome"] == RECOVERED_SUCCESS


def test_accept_timeout_recovers_after_settlement():
    c = FakeClient("/accept", AixError(0, {"code": "NETWORK_UNREACHABLE"}))
    c.gets = {"/v1/assignments/a1": {"status": "SETTLED"}}
    out = c.review_delivery("a1", "accept")
    assert out["outcome"] == RECOVERED_SUCCESS


def test_accept_timeout_before_settlement_stays_ambiguous():
    c = FakeClient("/accept", AixError(0, {"code": "NETWORK_UNREACHABLE"}))
    c.gets = {"/v1/assignments/a1": {"status": "IN_PROGRESS"}}
    with pytest.raises(AmbiguousOutcome):
        c.review_delivery("a1", "accept")


def test_bootstrap_timeout_after_allocation_is_not_double_claimed():
    # The allocation lands, but the response is lost. Balance proves it.
    c = FakeClient("/v1/bootstrap/claim",
                   AixError(0, {"code": "NETWORK_UNREACHABLE"}))
    c.gets = {"/v1/balance": {"balance": 0.0}}
    original = c._call
    reads = {"n": 0}

    def balance_after_allocation(method, path, body=None, **kw):
        # 0 before the allocation, 10 once it has landed.
        reads["n"] += 1
        c.gets["/v1/balance"] = {"balance": 0.0 if reads["n"] == 1 else 10.0}
        return original(method, path, body, **kw)

    c._call = balance_after_allocation
    out = c.claim_initial_aix()
    assert out["claimed"] is True and out["outcome"] == RECOVERED_SUCCESS
    assert len([x for x in c.calls if "bootstrap" in x]) == 1


def test_bootstrap_timeout_with_unchanged_balance_stays_ambiguous():
    """When state cannot prove either way, say so instead of guessing."""
    c = FakeClient("/v1/bootstrap/claim",
                   AixError(0, {"code": "NETWORK_UNREACHABLE"}))
    c.gets = {"/v1/balance": {"balance": 0.0}}
    out = c.claim_initial_aix()
    assert out["claimed"] is False
    assert out["code"] == AMBIGUOUS_OUTCOME
    assert len([x for x in c.calls if "bootstrap" in x]) == 1


def test_ambiguous_message_is_not_stated_as_fact():
    err = AmbiguousOutcome("timeout", "create_offer")
    text = err.agent_message()
    assert "不确定" in text
    assert AMBIGUOUS_OUTCOME in text


def test_idempotency_key_is_stable_across_a_logical_attempt():
    k = _NewIdempotencyKey()
    assert k() == k()


def test_http_error_is_never_treated_as_connectivity_failure():
    assert _looks_like_connectivity_failure(
        __import__("urllib.error", fromlist=["x"]).HTTPError("u", 500, "boom", {}, None)) is False


# ------------------------------------------------ C. lease / assignment choice
#: The real v0.8 shape. An offer publishes the assignment id it currently holds
#: inside slots[]; the owner and the state live on the assignment record. There
#: is no /v1/offers/{id}/assignments route -- it answers 404 -- so a fixture
#: that serves one is modelling a contract the node does not implement.
def _offer_with_slots(*slots) -> dict:
    oid = 0
    out = []
    for slot in slots:
        out.append({"slot_index": oid, "state": slot.get("state", "CLAIMED"),
                    "assignment_id": slot.get("assignment_id")})
        oid += 1
    return {"offer_id": "o1", "slots": out}


def _fabricated_node(pages: dict):
    c = AixClient("https://x")
    c.agent_id = "aix8_ag_self"
    c._call = lambda m, path, body=None, **kw: pages.get(path, {})
    return c


def test_current_assignment_404_path_is_not_used():
    """The Skill must never call the route frozen v0.8 does not publish."""
    calls: list[str] = []

    def recording_call(method, path, body=None, **kw):
        calls.append(path)
        if path == "/v1/offers/o1":
            return _offer_with_slots({"assignment_id": "a1", "state": "CLAIMED"})
        if path == "/v1/assignments/a1":
            return {"assignment_id": "a1", "worker_agent_id": "aix8_ag_self",
                    "status": "IN_PROGRESS", "claimed_at": 1.0}
        raise AssertionError(f"unexpected call: {method} {path}")

    c = AixClient("https://x")
    c.agent_id = "aix8_ag_self"
    c._call = recording_call
    assert c.current_assignment("o1") is not None
    assert not any(p.endswith("/assignments") and "/v1/offers/" in p for p in calls), \
        f"must not call the 404 route; calls were {calls}"


def test_current_assignment_none_when_no_slot_holds_one():
    c = _fabricated_node({
        "/v1/offers/o1": _offer_with_slots({"assignment_id": None,
                                            "state": "AVAILABLE"})})
    assert c.current_assignment("o1") is None


def test_current_assignment_returns_the_live_one():
    c = _fabricated_node({
        "/v1/offers/o1": _offer_with_slots({"assignment_id": "a1"}),
        "/v1/assignments/a1": {"assignment_id": "a1", "worker_agent_id": "aix8_ag_self",
                               "status": "CLAIMED", "claimed_at": 10.0}})
    out = c.current_assignment("o1")
    assert out["assignment_id"] == "a1"
    assert out["worker_agent_id"] == "aix8_ag_self"
    assert out["status"] == "CLAIMED"


def test_expired_assignment_is_history_not_current():
    """A slot still pointing at a finished assignment is not a live claim.

    The slot is reset to AVAILABLE on release, so this is the defensive case:
    even if a terminal assignment is reachable, it must not be reported live.
    """
    c = _fabricated_node({
        "/v1/offers/o1": _offer_with_slots({"assignment_id": "a_old"}),
        "/v1/assignments/a_old": {"assignment_id": "a_old",
                                  "worker_agent_id": "aix8_ag_self",
                                  "status": "EXPIRED", "claimed_at": 1.0}})
    assert c.current_assignment("o1") is None


def test_settled_assignment_is_not_reported_as_current():
    c = _fabricated_node({
        "/v1/offers/o1": _offer_with_slots({"assignment_id": "a_done"}),
        "/v1/assignments/a_done": {"assignment_id": "a_done",
                                   "worker_agent_id": "aix8_ag_self",
                                   "status": "SETTLED", "claimed_at": 5.0}})
    assert c.current_assignment("o1") is None


def test_replacement_assignment_is_selected_over_the_released_one():
    """A lapsed slot reclaimed by someone else yields the NEW assignment.

    The released assignment is no longer referenced by any slot, so the offer
    cannot resurrect it; the current one is returned even though the old record
    still exists in the ledger.
    """
    c = _fabricated_node({
        "/v1/offers/o1": _offer_with_slots({"assignment_id": "a_new"}),
        "/v1/assignments/a_new": {"assignment_id": "a_new",
                                  "worker_agent_id": "aix8_ag_other",
                                  "status": "CLAIMED", "claimed_at": 99.0}})
    out = c.current_assignment("o1")
    assert out["assignment_id"] == "a_new"
    assert out["worker_agent_id"] == "aix8_ag_other"


def test_current_assignment_can_be_filtered_to_one_agent():
    c = _fabricated_node({
        "/v1/offers/o1": _offer_with_slots({"assignment_id": "a1"}),
        "/v1/assignments/a1": {"assignment_id": "a1",
                               "worker_agent_id": "aix8_ag_other",
                               "status": "CLAIMED", "claimed_at": 1.0}})
    assert c.current_assignment("o1", agent_id="aix8_ag_self") is None
    assert c.current_assignment("o1", agent_id="aix8_ag_other") is not None


def test_two_slots_are_not_reported_as_a_double_assignment():
    """Two slots are two legitimate claims, not corruption."""
    c = _fabricated_node({
        "/v1/offers/o1": _offer_with_slots({"assignment_id": "a1"},
                                           {"assignment_id": "a2"}),
        "/v1/assignments/a1": {"assignment_id": "a1",
                               "worker_agent_id": "aix8_ag_a",
                               "status": "CLAIMED", "claimed_at": 1.0},
        "/v1/assignments/a2": {"assignment_id": "a2",
                               "worker_agent_id": "aix8_ag_b",
                               "status": "CLAIMED", "claimed_at": 2.0}})
    out = c.current_assignment("o1")
    assert out["assignment_id"] == "a2"  # most recently claimed


# ------------------------------------------------------------- D. join UX
def test_join_creates_identity_only_and_does_not_claim():
    s = skill()
    s.client.discover = lambda: None
    s.client.load_stored = lambda: False
    s.client.register = lambda *a, **k: {"agent_id": "aix8_ag_new",
                                          "api_key": FAKE_KEY}
    s.client.store_credential = lambda: {"stored": True, "backend": "isolated_file",
                                         "verified": True}
    s.client.identity = lambda: {"agent_id": "aix8_ag_new", "balance": 0}
    s.client.balance = lambda: {"balance": 0}
    r = s.handle("join aix", display_name="x", consent=True)
    assert r["identity"]["balance"] == 0
    assert r["next"]["recommended"]["intent"] == "CLAIM_AIX"


def test_join_without_consent_still_refuses():
    s = skill()
    r = s.handle("join aix", display_name="x")
    assert r["ok"] is False and r["action_required"] == "confirm_consent"
    assert "Production" in " ".join(r["consent_summary"]["will_not"])


# ------------------------------------------------------------- E. networking
def test_ipv6_failure_triggers_scoped_ipv4_retry(monkeypatch):
    import aix_client as ac
    import urllib.request

    attempts = {"n": 0}

    class R:
        status = 200
        def read(self): return b"{}"

        def __enter__(self): return self

        def __exit__(self, *a): return False

    def fake_urlopen(req, timeout=None):
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise TimeoutError("timed out")
        return R()

    monkeypatch.setattr(ac.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(ac, "_open_ipv4", fake_urlopen)
    assert ac._IPV4_FALLBACK is True
    ac._urlopen_with_ipv4_fallback(urllib.request.Request("https://fixture.invalid"), 1)
    assert attempts["n"] == 2


def test_http_error_never_triggers_the_ipv4_retry(monkeypatch):
    import aix_client as ac
    import urllib.error

    attempts = {"n": 0}

    def fake_urlopen(req, timeout=None):
        attempts["n"] += 1
        raise urllib.error.HTTPError("u", 503, "busy", {}, None)

    monkeypatch.setattr(ac.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(urllib.error.HTTPError):
        ac._urlopen_with_ipv4_fallback(ac.urllib.request.Request("https://fixture.invalid"), 1)
    assert attempts["n"] == 1  # a real answer is never re-sent


def test_tls_verification_is_never_disabled():
    # The encoding is explicit because the source carries the Chinese agent
    # messages, and the default is the process locale: on a GBK machine the
    # read raised UnicodeDecodeError and this security check never ran at all.
    src = (pathlib.Path(__file__).resolve().parents[1]
           / "aix_client.py").read_text(encoding="utf-8")
    for forbidden in ("_create_unverified_context", "CERT_NONE",
                      "check_hostname = False", "verify=False"):
        assert forbidden not in src, forbidden


# ------------------------------------------- F. rotate / revoke (real routes)
class TransportResponse:
    def __init__(self, body=b'{"ok": true}', error=None, status=200):
        self.body, self.error, self.status = body, error, status
        self.closed = False

    def read(self):
        if self.error:
            raise self.error
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.closed = True


@pytest.mark.parametrize("failure", ["remote", "incomplete", "timeout", "reset"])
def test_transport_get_recovers_connection_and_body(monkeypatch, failure):
    import http.client
    import aix_client as ac
    errors = {"remote": http.client.RemoteDisconnected("closed"),
              "incomplete": http.client.IncompleteRead(b'{', 20),
              "timeout": TimeoutError("timed out"),
              "reset": ConnectionResetError("reset")}
    calls = []
    response = TransportResponse(error=errors[failure])

    def default(req, timeout):
        calls.append("default")
        if failure == "incomplete":
            return response
        raise errors[failure]

    def ipv4(req, timeout):
        calls.append("ipv4")
        return TransportResponse()

    monkeypatch.setattr(ac.urllib.request, "urlopen", default)
    monkeypatch.setattr(ac, "_open_ipv4", ipv4, raising=False)
    assert AixClient("https://fixture.invalid")._request("GET", "/v1/healthz", auth=False) == (200, {"ok": True})
    assert calls == ["default", "ipv4"]
    if failure == "incomplete":
        assert response.closed


def test_transport_default_success_does_not_fallback(monkeypatch):
    import aix_client as ac
    response = TransportResponse()
    monkeypatch.setattr(ac.urllib.request, "urlopen", lambda *a, **kw: response)
    monkeypatch.setattr(ac, "_open_ipv4", lambda *a, **kw: pytest.fail("unexpected fallback"), raising=False)
    assert AixClient("https://fixture.invalid")._request("GET", "/x", auth=False)[0] == 200
    assert response.closed


@pytest.mark.parametrize("status", [401, 403, 409, 500, 503])
def test_transport_http_errors_preserve_status_without_retry(monkeypatch, status):
    import io
    import urllib.error
    import aix_client as ac
    calls = []
    def default(*args, **kwargs):
        calls.append("default")
        raise urllib.error.HTTPError("https://fixture.invalid", status, "response", {}, io.BytesIO(b'{"code":"EXPECTED"}'))
    monkeypatch.setattr(ac.urllib.request, "urlopen", default)
    monkeypatch.setattr(ac, "_open_ipv4", lambda *a, **kw: pytest.fail("HTTP error retried"), raising=False)
    result = AixClient("https://fixture.invalid")._request("GET", "/x", auth=False)
    assert result == (status, {"code": "EXPECTED"})
    assert calls == ["default"]


def test_transport_fallback_is_bounded_and_does_not_change_global_resolver(monkeypatch):
    import aix_client as ac
    original = ac.socket.getaddrinfo
    calls = []
    def fail(label):
        def request(*a, **kw):
            calls.append(label)
            assert ac.socket.getaddrinfo is original
            raise TimeoutError("timed out")
        return request
    monkeypatch.setattr(ac.urllib.request, "urlopen", fail("default"))
    monkeypatch.setattr(ac, "_open_ipv4", fail("ipv4"), raising=False)
    with pytest.raises(AixError) as caught:
        AixClient("https://fixture.invalid")._request("GET", "/x", auth=False)
    assert caught.value.status == 0
    assert calls == ["default", "ipv4"]
    assert ac.socket.getaddrinfo is original


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
@pytest.mark.parametrize("body_failure", [False, True])
def test_transport_mutation_never_replays_ambiguous_exchange(monkeypatch, method, body_failure):
    import http.client
    import aix_client as ac
    calls = []
    def default(*a, **kw):
        calls.append(method)
        if body_failure:
            return TransportResponse(error=http.client.IncompleteRead(b'{', 20))
        raise TimeoutError("commit may have happened")
    monkeypatch.setattr(ac.urllib.request, "urlopen", default)
    monkeypatch.setattr(ac, "_open_ipv4", lambda *a, **kw: pytest.fail("mutation replay"), raising=False)
    with pytest.raises(AmbiguousOutcome):
        AixClient("https://fixture.invalid")._mutate("economic_operation", method, "/x", {}, auth=False)
    assert calls == [method]


def test_transport_registration_never_replays(monkeypatch):
    import aix_client as ac
    calls = []
    def default(*a, **kw):
        calls.append("register")
        raise TimeoutError("identity may exist")
    monkeypatch.setattr(ac.urllib.request, "urlopen", default)
    monkeypatch.setattr(ac, "_open_ipv4", lambda *a, **kw: pytest.fail("duplicate identity"), raising=False)
    with pytest.raises(AixError):
        AixClient("https://fixture.invalid").register("fixture", store_ready=True)
    assert calls == ["register"]


@pytest.mark.parametrize("keyword", [False, True])
def test_transport_ipv4_resolver_preserves_non_family_arguments(monkeypatch, keyword):
    import aix_client as ac
    captured = []
    def resolver(host, port, family=0, type=0, proto=0, flags=0):
        captured.append((host, port, family, type, proto, flags))
        return []
    monkeypatch.setattr(ac.socket, "getaddrinfo", resolver)
    fn = getattr(ac, "_getaddrinfo_ipv4", None)
    assert callable(fn), "IPv4 resolver must avoid global monkey-patching"
    if keyword:
        fn("fixture.invalid", 443, family=ac.socket.AF_INET6, type=ac.socket.SOCK_STREAM, proto=6, flags=1)
    else:
        fn("fixture.invalid", 443, ac.socket.AF_INET6, ac.socket.SOCK_STREAM, 6, 1)
    assert captured == [("fixture.invalid", 443, ac.socket.AF_INET, ac.socket.SOCK_STREAM, 6, 1)]


def test_transport_malformed_json_is_not_retried(monkeypatch):
    import aix_client as ac
    monkeypatch.setattr(ac.urllib.request, "urlopen", lambda *a, **kw: TransportResponse(b'not json'))
    monkeypatch.setattr(ac, "_open_ipv4", lambda *a, **kw: pytest.fail("JSON error retry"), raising=False)
    with pytest.raises(ValueError):
        AixClient("https://fixture.invalid")._request("GET", "/x", auth=False)


@pytest.mark.parametrize("error", [ValueError("application timeout"), TypeError("ssl application error")])
def test_transport_application_exception_is_not_connectivity(error):
    assert not _looks_like_connectivity_failure(error)


def test_transport_certificate_failure_does_not_retry(monkeypatch):
    import ssl
    import aix_client as ac
    def fail(*a, **kw):
        raise ssl.SSLCertVerificationError("certificate verification failed")
    monkeypatch.setattr(ac.urllib.request, "urlopen", fail)
    monkeypatch.setattr(ac, "_open_ipv4", lambda *a, **kw: pytest.fail("TLS identity failure retried"))
    with pytest.raises(ssl.SSLCertVerificationError):
        AixClient("https://fixture.invalid")._request("GET", "/x", auth=False)


@pytest.mark.parametrize("status", [401, 409])
def test_transport_truncated_http_error_keeps_status(monkeypatch, status):
    import http.client
    import urllib.error
    import aix_client as ac
    body = TransportResponse(error=http.client.IncompleteRead(b'{', 10))
    body.close = lambda: None
    def fail(*a, **kw):
        raise urllib.error.HTTPError("https://fixture.invalid", status, "response", {}, body)
    monkeypatch.setattr(ac.urllib.request, "urlopen", fail)
    monkeypatch.setattr(ac, "_open_ipv4", lambda *a, **kw: pytest.fail("HTTP status retry"))
    assert AixClient("https://fixture.invalid")._request("GET", "/x", auth=False)[0] == status


@pytest.mark.parametrize("operation", ["create", "claim", "delivery", "accept", "bootstrap"])
def test_transport_committed_mutation_reconciles_without_replay(monkeypatch, operation):
    import http.client
    from urllib.parse import urlsplit
    import aix_client as ac
    client = AixClient("https://beta.aixprotocol.org")
    client.agent_id = "aix8_ag_self"
    client._api_key = FAKE_KEY
    committed = False
    mutations = []
    def exchange(req, timeout):
        nonlocal committed
        path = urlsplit(req.full_url).path
        if req.get_method() == "POST":
            mutations.append(path)
            committed = True
            return TransportResponse(error=http.client.IncompleteRead(b'{', 20))
        data = _self_owned_assignment().get(path, {})
        if path == "/v1/offers":
            data = {"offers": [{"offer_id": "aix8_of_mine", "creator_agent_id": client.agent_id,
                                "reward": "2", "status": "OPEN", "task_spec": {"title": "t"},
                                "created_at": 1000, "claim_deadline": 87400}]}
        if path == "/v1/assignments/a1":
            data = {"status": "SETTLED"}
        if path == "/v1/assignments/a1/submission":
            data = {"assignment_id": "a1"}
        if path == "/v1/balance":
            data = {"balance": 10 if committed else 0}
        return TransportResponse(json.dumps(data).encode())
    from types import SimpleNamespace
    monkeypatch.setattr(ac.urllib.request, "build_opener", lambda *args: SimpleNamespace(open=exchange))
    monkeypatch.setattr(ac.urllib.request, "urlopen", exchange)
    monkeypatch.setattr(ac, "_open_ipv4", lambda *a, **kw: pytest.fail("economic replay"))
    if operation == "create":
        result = client.create_task({"title": "t"}, "2", [])
    elif operation == "claim":
        result = client.claim_task("o1")
    elif operation == "delivery":
        result = client.submit_delivery("a1", {"answer": "ok"})
    elif operation == "accept":
        result = client.review_delivery("a1", "accept")
    else:
        result = client.claim_initial_aix()
    assert result["outcome"] == RECOVERED_SUCCESS
    assert len(mutations) == 1


def test_transport_ipv4_socket_factory_and_tls_verification(monkeypatch):
    import ssl
    import aix_client as ac
    events = []
    class FakeSocket:
        def settimeout(self, value): events.append(("timeout", value))
        def bind(self, value): events.append(("bind", value))
        def connect(self, value): events.append(("connect", value))
        def close(self): events.append(("close",))
    monkeypatch.setattr(ac, "_getaddrinfo_ipv4", lambda *a, **kw: [(ac.socket.AF_INET, ac.socket.SOCK_STREAM, 6, "", ("192.0.2.1", 443))])
    sock = FakeSocket()
    monkeypatch.setattr(ac.socket, "socket", lambda *a: sock)
    assert ac._ipv4_create_connection(("fixture.invalid", 443), 2, ("127.0.0.1", 0)) is sock
    assert events == [("timeout", 2), ("bind", ("127.0.0.1", 0)), ("connect", ("192.0.2.1", 443))]
    connection = ac._IPv4HTTPSConnection("fixture.invalid")
    assert connection._create_connection is ac._ipv4_create_connection
    assert connection._context.verify_mode == ssl.CERT_REQUIRED
    assert connection._context.check_hostname is True


def test_transport_disabled_fallback_is_one_attempt(monkeypatch):
    import aix_client as ac
    calls = []
    def fail(*a, **kw):
        calls.append("default")
        raise TimeoutError("timed out")
    monkeypatch.setattr(ac, "_IPV4_FALLBACK", False)
    monkeypatch.setattr(ac.urllib.request, "urlopen", fail)
    monkeypatch.setattr(ac, "_open_ipv4", lambda *a, **kw: pytest.fail("disabled fallback"))
    with pytest.raises(AixError):
        AixClient("https://fixture.invalid")._request("GET", "/x", auth=False)
    assert calls == ["default"]


def test_transport_ipv4_failure_closes_socket(monkeypatch):
    import aix_client as ac
    closed = []
    class FailedSocket:
        def settimeout(self, value): pass
        def connect(self, value): raise ConnectionRefusedError("refused")
        def close(self): closed.append(True)
    monkeypatch.setattr(ac, "_getaddrinfo_ipv4", lambda *a, **kw: [(ac.socket.AF_INET, ac.socket.SOCK_STREAM, 6, "", ("192.0.2.1", 443))])
    monkeypatch.setattr(ac.socket, "socket", lambda *a: FailedSocket())
    with pytest.raises(ConnectionRefusedError):
        ac._ipv4_create_connection(("fixture.invalid", 443), 1)
    assert closed == [True]


def test_rotate_and_revoke_exist_and_are_wired():
    c = AixClient("https://x")
    assert hasattr(c, "rotate_credential")
    assert hasattr(c, "revoke_credential")


def test_revoke_clears_local_state():
    s = skill()
    s.client.agent_id = "aix8_ag_self"
    s.client._api_key = FAKE_KEY
    s.store.save("aix8_ag_self", FAKE_KEY)
    s.client._mutate = lambda *a, **k: ("SUCCESS", {"revoked": True})
    out = s.client.revoke_credential()
    assert out["revoked"] is True and out["local_state_cleared"] is True
    assert s.store.agent_ids() == []


@pytest.mark.parametrize("command", ["新手说明", "新手指南", "怎么玩 AIX", "如何使用 AIX"])
@pytest.mark.parametrize("authenticated", [False, True])
def test_trust_beginner_guidance_readonly(tmp_path, command, authenticated):
    s = boundary_skill(tmp_path, authenticated)
    for name in ("register", "claim_initial_aix", "create_task", "claim_task",
                 "submit_delivery", "review_delivery", "rotate_credential", "revoke_credential", "transfer", "_mutate", "_request"):
        setattr(s.client, name, lambda *a, **kw: pytest.fail("guidance performed network/mutation"))
    result = s.handle(command, consent=True, _authorized_intent="JOIN_AIX")
    assert result["intent"] == "BEGINNER_GUIDE"
    text = result["final_response"]
    for required in ("安装 ≠ 加入", "加入 ≠ 领取 AIX", "不是工作收入", "没有货币价值", "验收通过后才结算", "浏览任务 ≠ 自动接单"):
        assert required in text
    assert result["used_protocol"] == []
    assert result["suggestion_is_authorization"] is False
    assert result["menu_commands"] == ["加入 AIX", "新手说明", "接任务", "发任务", "查看任务", "我的余额"]


def test_first_run_approved_resource_digest():
    import hashlib
    assert hashlib.sha256(ROBOT_EXPECTED.encode()).hexdigest() == APPROVED_HOME_SHA256
    assert ROBOT_EXPECTED.count("[ ") == 6


def test_first_run_bare_aix_home(tmp_path):
    s = boundary_skill(tmp_path)
    assert s.handle("AIX")["final_response"] == s.handle("菜单")["final_response"]


@pytest.mark.parametrize("phrase", ["查看版本", "查看校验信息", "安装在哪里"])
def test_first_run_pull_diagnostics(tmp_path, phrase):
    result = boundary_skill(tmp_path).handle(phrase)
    assert result["intent"] == "INSTALL_DIAGNOSTIC"
    assert result["installation_status"] == "UNKNOWN"
    assert "PACKAGE_SHA256" not in json.dumps(result)


def test_first_run_guide_concise_product(tmp_path):
    result = boundary_skill(tmp_path).handle("新手说明")
    text = result["final_response"]
    assert "Agent 互相发布任务" in text
    assert "安装 ≠ 加入" in text
    assert "没有货币价值" in text
    assert len(text) < 550
    assert not any(x in text for x in ("endpoint", "JSON", "Claim", "PASS", "凭据"))
    assert result["used_protocol"] == []


def test_first_run_hash_name_exact_object(tmp_path):
    result = boundary_skill(tmp_path).handle("验证 AIX Skill")
    assert "package_sha256" not in result
    assert "sha256sums_sha256" in result
    assert "checksum_manifest_verified" in result


def test_first_run_create_form_asks_only_missing(tmp_path):
    result = boundary_skill(tmp_path, True).handle("发任务", task_spec={"title":"t"})
    assert "任务是什么" not in result["final_response"]
    assert "奖励多少" in result["final_response"]
    assert "怎样算完成" in result["final_response"]


def test_first_run_host_policy_language():
    text = (pathlib.Path(__file__).parents[1] / "SKILL.md").read_text(encoding="utf-8")
    assert "higher-priority host-runtime security policy" in text
    assert "ONLY the canonical code block" not in text


def test_first_run_internal_checks_no_push(tmp_path):
    facts=dict(zip_verified=True,manifest_verified=True,files_verified=True,
               extracted=True,discovered=True,loaded=True,validation_completed=True)
    text=AixSkill.install_response(**facts)
    assert text.startswith("```text\n"+ROBOT_EXPECTED+"```")
    for dump in ("SHA256", "Build ID", "manifest", "权限", "安全信息", "没有自动", "PROVENANCE", "C:\\"):
        assert dump not in text
    for field in ('zip_verified','files_verified','loaded'):
        bad=dict(facts);bad[field]=False
        assert "安装完成" not in AixSkill.install_response(**bad)


def test_first_run_read_journey_zero_mutation(tmp_path):
    s=boundary_skill(tmp_path,True)
    for name in ('register','claim_initial_aix','create_task','claim_task','submit_delivery','review_delivery','transfer','_mutate'):
        setattr(s.client,name,lambda *a,**kw:pytest.fail('read journey mutated'))
    for phrase in ('AIX','菜单','新手说明','接任务','查看任务','我的余额','查看安全信息','安装诊断','查看校验信息'):
        result=s.handle(phrase,consent=True)
        assert result['ok']
    assert s.handle('查看安全信息')['final_response']


def test_runtime_install_lifecycle_verified_activation_home(tmp_path):
    from aix_welcome import InstallLifecycle
    runtime=InstallLifecycle()
    assert runtime.state=='INSTALL_VERIFYING'
    assert '安装完成' not in runtime.response()
    runtime.verify(zip_verified=True,manifest_verified=True,files_verified=True,
                   extracted=True,validation_completed=True)
    assert runtime.state=='INSTALL_INCOMPLETE'
    assert '安装完成' not in runtime.response()
    runtime.activate(discovered=True,loaded=True)
    assert runtime.state=='AIX_HOME'
    assert runtime.transitions==['INSTALL_VERIFYING','INSTALL_INCOMPLETE','INSTALL_ACTIVATED','AIX_HOME']
    assert runtime.response().startswith('```text\n'+ROBOT_EXPECTED+'```')
    assert boundary_skill(tmp_path).handle('安装诊断')['installation_status']=='UNKNOWN'
    assert boundary_skill(tmp_path).handle('查看安全信息')['final_response']


@pytest.mark.parametrize('field',['zip_verified','manifest_verified','files_verified'])
def test_runtime_install_lifecycle_integrity_failure(field):
    from aix_welcome import InstallLifecycle
    runtime=InstallLifecycle()
    facts=dict(zip_verified=True,manifest_verified=True,files_verified=True,extracted=True,validation_completed=True)
    facts[field]=False
    runtime.verify(**facts)
    runtime.activate(discovered=True,loaded=True)
    assert runtime.state=='INSTALL_FAILED'
    assert '安装完成' not in runtime.response()


def test_runtime_install_lifecycle_no_activation_shortcut():
    from aix_welcome import InstallLifecycle
    runtime=InstallLifecycle()
    runtime.activate(discovered=True,loaded=True)
    assert runtime.state!='AIX_HOME'
    assert '安装完成' not in runtime.response()


def test_headless_importable_keyring_fresh_join_auto_fallback(tmp_path,monkeypatch):
    from types import SimpleNamespace
    def unavailable(*args):raise RuntimeError('No recommended backend available')
    monkeypatch.setitem(sys.modules,'keyring',SimpleNamespace(get_password=unavailable,set_password=unavailable,delete_password=unavailable))
    monkeypatch.setenv('AIX_SKILL_CREDENTIAL_FILE',str(tmp_path/'fallback.json'))
    store=CredentialStore('headless')
    s=AixSkill(store=store)
    s.client.claim_initial_aix=lambda *a,**kw:pytest.fail('Join must not bootstrap')
    result=s.handle('加入 AIX')
    assert result['action_required']=='confirm_consent'
    assert result['consent_summary']['SELECTED_BACKEND']=='isolated_file'
    assert not (tmp_path/'fallback.json').exists()


def test_simulated_runtime_extract_verify_activate_home(tmp_path):
    import hashlib,zipfile,importlib.util
    source=pathlib.Path(__file__).parents[1]
    entries={name:(source/name).read_bytes() for name in ('welcome.txt','aix_welcome.py')}
    sums=''.join(hashlib.sha256(body).hexdigest()+'  '+name+'\n' for name,body in sorted(entries.items()))
    package=tmp_path/'runtime-package.zip'
    with zipfile.ZipFile(package,'w') as archive:
        for name,body in entries.items():archive.writestr(name,body)
        archive.writestr('SHA256SUMS.txt',sums)
    manifest={'package_sha256':hashlib.sha256(package.read_bytes()).hexdigest()}
    assert hashlib.sha256(package.read_bytes()).hexdigest()==manifest['package_sha256']
    activated=tmp_path/'native-skill';activated.mkdir()
    with zipfile.ZipFile(package) as archive:
        for row in archive.read('SHA256SUMS.txt').decode().splitlines():
            expected,name=row.split('  ',1)
            assert hashlib.sha256(archive.read(name)).hexdigest()==expected
        archive.extractall(activated)
    spec=importlib.util.spec_from_file_location('isolated_runtime_home',activated/'aix_welcome.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    result=module.install_completion(zip_verified=True,manifest_verified=True,
              files_verified=True,extracted=True,validation_completed=True,
              discovered=True,loaded=True)
    assert result['status']=='AIX_HOME'
    assert result['final_response'].startswith('```text\n'+ROBOT_EXPECTED+'```')


def test_public_market_natural_phrase_routes_to_anonymous_find_work(tmp_path):
    s = boundary_skill(tmp_path)
    calls = []
    s.client.find_work = lambda **kw: calls.append(kw) or {"total": 0, "offers": []}

    result = s.handle("看看 AIX 公共任务市场有哪些任务")

    assert result["ok"] is True
    assert result["intent"] == "FIND_WORK"
    assert calls == [{"limit": 10}]
    assert s.client.agent_id is None
    assert s.client._api_key is None



# ------------------------------------------- own-work listing (fresh process)
def test_fresh_process_lists_its_own_work_from_the_protocol():
    """A restarted Agent remembers no ids; it must still find its claims."""
    c = FakeClient("/never", AixError(0, {"code": "UNUSED"}))
    assert c.known_assignments == []
    c.gets = {"/v1/agents/me/assignments?limit=100": {
        "items": [{"assignment_id": "aix8_as_a", "status": "IN_PROGRESS",
                   "next_action": "deliver"}], "next_cursor": None}}
    listing = c.my_tasks("worker")
    assert listing["complete"] is True
    assert [i["assignment_id"] for i in listing["items"]] == ["aix8_as_a"]
    assert c.known_assignments == [{"assignment_id": "aix8_as_a", "role": "worker"}]


def test_own_work_listing_follows_cursors():
    c = FakeClient("/never", AixError(0, {"code": "UNUSED"}))
    c.gets = {"/v1/agents/me/offers?limit=100": {"items": [{"offer_id": "o1"}],
                                                 "next_cursor": "o1"},
              "/v1/agents/me/offers?limit=100&cursor=o1": {"items": [{"offer_id": "o2"}],
                                                           "next_cursor": None}}
    listing = c.my_tasks("creator")
    assert [i["offer_id"] for i in listing["items"]] == ["o1", "o2"]
    assert listing["complete"] is True


def test_older_node_without_listing_falls_back_honestly():
    class OldNode(FakeClient):
        def _call(self, method, path, body=None, **kw):
            if path.startswith("/v1/agents/me/"):
                raise AixError(404, {"code": "NOT_FOUND"})
            return super()._call(method, path, body, **kw)
    c = OldNode("/never", AixError(0, {"code": "UNUSED"}))
    c.remember_assignment("aix8_as_known", "worker")
    listing = c.my_tasks("worker")
    assert listing["complete"] is False
    assert listing["source"] == "remembered_ids_only"
    assert [i["assignment_id"] for i in listing["items"]] == ["aix8_as_known"]


@pytest.mark.parametrize("command,endpoint", [
    ("查看我接过的任务", "assignments"),
    ("查看我发布的任务", "offers"),
    ("查看我的工作进度", "assignments"),
])
def test_natural_own_work_commands_are_authenticated_reads(tmp_path, command, endpoint):
    s = boundary_skill(tmp_path, authenticated=True)
    calls = []
    identifier = "assignment_id" if endpoint == "assignments" else "offer_id"
    def read(method, path, *args, **kw):
        assert method == "GET"
        calls.append(path)
        assert path == f"/v1/agents/me/{endpoint}?limit=100"
        return {"items": [{identifier: "own-work", "status": "IN_PROGRESS",
                           "task_spec": {"title": "自己的任务"},
                           "api_key": FAKE_KEY}], "next_cursor": None}
    s.client._call = read
    result = s.handle(command)
    assert result["ok"] and result["complete"] is True
    assert calls == [f"/v1/agents/me/{endpoint}?limit=100"]
    assert "自己的任务" in result["final_response"]
    assert FAKE_KEY not in json.dumps(result)


@pytest.mark.parametrize("command,role", [
    ("查看我接过的任务", "worker"), ("查看我的工作进度", "worker"),
    ("查看我发布的任务", "creator"), ("查看任务", "creator"),
])
def test_capped_own_work_never_claims_complete_history(tmp_path, command, role):
    s = boundary_skill(tmp_path, authenticated=True)
    calls = []
    identifier = "assignment_id" if role == "worker" else "offer_id"
    def read(method, path, *args, **kw):
        assert method == "GET"
        calls.append(path)
        return {"items": [{identifier: str(len(calls)), "status": "CLAIMED"}],
                "next_cursor": str(len(calls))}
    s.client._call = read
    result = s.handle(command, role=role)
    assert len(calls) == 20
    assert result["complete"] is False
    assert "结果不完整" in result["final_response"]
    assert "全部" not in result.get("scope", result.get("note", ""))


@pytest.mark.parametrize("command,role", [
    ("查看我接过的任务", "worker"), ("查看我的工作进度", "worker"),
    ("查看我发布的任务", "creator"), ("查看任务", "creator"),
])
def test_legacy_empty_own_work_is_explicitly_incomplete(tmp_path, command, role):
    s = boundary_skill(tmp_path, authenticated=True)
    def read(method, path, *args, **kw):
        assert method == "GET"
        if path.startswith("/v1/agents/me/"):
            raise AixError(404, {"code": "NOT_FOUND"})
        assert path == "/v1/offers"
        return {"offers": []}
    s.client._call = read
    result = s.handle(command, role=role)
    assert result["complete"] is False
    assert result["source"] == "remembered_ids_only"
    assert "结果不完整" in result["final_response"]
    assert "当前没有相关任务" not in result["final_response"]


def test_legacy_creator_fallback_includes_only_own_known_and_public_offers(tmp_path):
    s = boundary_skill(tmp_path, authenticated=True)
    s.client.remember_offer("own-closed", "creator")
    def read(method, path, *args, **kw):
        assert method == "GET"
        if path.startswith("/v1/agents/me/"):
            raise AixError(404, {"code": "NOT_FOUND"})
        if path == "/v1/offers":
            return {"offers": [{"offer_id": "own-open", "creator_agent_id": s.client.agent_id},
                               {"offer_id": "other-offer", "creator_agent_id": "other"}]}
        assert path == "/v1/offers/own-closed"
        return {"offer_id": "own-closed", "creator_agent_id": s.client.agent_id,
                "status": "CLOSED", "api_key": FAKE_KEY}
    s.client._call = read
    result = s.handle("查看我发布的任务")
    assert {x["offer_id"] for x in result["offers"]} == {"own-open", "own-closed"}
    assert result["complete"] is False and "结果不完整" in result["final_response"]
    assert FAKE_KEY not in json.dumps(result)


def test_public_registration_instructions_need_no_invitation():
    root = pathlib.Path(__file__).resolve().parents[1]
    text = (root / "SKILL.md").read_text(encoding="utf-8")
    assert "Registration does not require an invitation code" in text
    assert "X-Beta-Invitation" not in text
    assert "Registration still requires explicit current user consent" in text
    assert "persist the Agent ID and API key" in text
    assert "versions `0.8` or `0.8.1`" in text


def test_public_registration_transport_is_anonymous_and_preserves_identity(tmp_path, monkeypatch):
    from aix_credentials import CredentialStore
    from aix_client import AixClient
    from aix_article_zero import registration_consent
    monkeypatch.setenv("AIX_SKILL_CREDENTIAL_FILE", str(tmp_path / "state.json"))
    store = CredentialStore().file_store()
    client = AixClient("https://beta.aixprotocol.org", store=store)
    calls = []
    def request(method, path, body=None, **kw):
        calls.append((method, path, body, kw))
        return 201, {"agent_id": "synthetic_public_join", "api_key": "fake_key_not_a_real_credential"}
    client._request = request
    consent = registration_consent()
    client.register("synthetic", metadata=consent, store_ready=True)
    assert calls == [("POST", "/v1/agents", {"display_name": "synthetic", "metadata": consent}, {"auth": False})]
    assert client.store_credential()["verified"] is True
    restored = AixClient("https://beta.aixprotocol.org", store=store)
    restored._request = lambda *args, **kw: (200, {"agent_id": "synthetic_public_join"})
    assert restored.load_stored() is True
    assert restored.agent_id == "synthetic_public_join"
    assert restored._api_key == "fake_key_not_a_real_credential"
