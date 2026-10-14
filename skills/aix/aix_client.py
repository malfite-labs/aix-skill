"""AIX Protocol client for the Skill.

Thin on purpose. Every operation here maps onto exactly one public AIX v0.8
endpoint -- no private routes, no local state that shadows the protocol, no
economics of its own. The Skill's job is to make the protocol easy to use, and
the cheapest way to guarantee it never becomes a second protocol is to keep every
call traceable to a public operation.

Discovery is first: the client reads the network and onboarding manifests and
refuses to act against a network that is not AIX v0.8, rather than assuming.
"""
from __future__ import annotations

import json
import math
import errno
import hashlib
import http.client
import os
import pathlib
import secrets
import socket
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from aix_credentials import CredentialStore, redact, summarize
from aix_network import CANONICAL_BETA, BETA_HOST

# Product default only: the frozen protocol still defaults to 3600 seconds.
DEFAULT_SKILL_CLAIM_WINDOW_SECONDS = 86400


def validate_claim_window_seconds(value: int | None) -> int:
    if value is None:
        return DEFAULT_SKILL_CLAIM_WINDOW_SECONDS
    if type(value) is not int or value <= 0:
        raise AixError(400, {"code": "INVALID_CLAIM_WINDOW",
                            "message": "claim_window_seconds must be a positive integer; "
                                       "omit it for the Skill's 24-hour default"})
    return value

#: Rule kinds the frozen v0.8 node refuses with UNSUPPORTED_RULE. They require an
#: artifact resolver that fetches and hashes bytes behind an ArtifactRef URI,
#: which AIX does not have -- a node stores no bytes. Generating one would
#: publish an offer that can never settle.
UNSUPPORTED_RULE_KINDS = ("artifact_mime_type", "artifact_sha256_equals")

#: Assignment statuses that are history, not a current claim. A settled,
#: refunded, expired or released assignment is finished; reporting one as the
#: offer's current assignment would send an Agent to work a slot it no longer
#: holds. Deliberately an exclusion set: a status this list does not know about
#: is treated as still-current rather than silently discarded.
HISTORICAL_ASSIGNMENT_STATUSES = ("SETTLED", "REFUNDED", "EXPIRED", "RELEASED",
                                  "ABANDONED", "RESOLVED", "CLOSED", "CANCELLED")

#: Statuses that mean the slot is no longer this Agent's to work. Recovering
#: one of these would resurrect a finished or abandoned claim.
RELEASED_STATUSES = ("RELEASED", "EXPIRED", "CLOSED", "REFUNDED")

SUPPORTED_PROTOCOL_VERSION = "0.8.1"
SUPPORTED_PROTOCOL_VERSIONS = ("0.8", "0.8.1", "0.9")


class AixError(Exception):
    """A protocol error, with the machine-readable code preserved."""

    def __init__(self, status: int, payload: dict) -> None:
        self.status = status
        self.payload = payload or {}
        self.code = self.payload.get("code") or "UNKNOWN"
        self.classification = self.payload.get("classification") or "HARD"
        self.retryable = bool(self.payload.get("retryable"))
        self.message = self.payload.get("message") or ""
        self.details = self.payload.get("details") or {}
        super().__init__(f"{self.code}: {self.message}")

    def agent_message(self) -> str:
        """A sentence an Agent can act on, keeping the original code."""
        return TRANSLATIONS.get(
            self.code,
            f"操作未成功（{self.code}）。原始信息：{self.message}") + f" [code={self.code}]"


TRANSLATIONS = {
    "JOIN_INITIAL_ALLOCATION_UNAVAILABLE": "New JOIN rolled back because the initial10AIX allocation is unavailable. Preserve the registration token and retry after policy/treasury recovery.",
    "INSUFFICIENT_BALANCE": "当前余额不足以为任务锁定 reward。",
    "BOOTSTRAP_EXHAUSTED": "当前网络的新用户测试资金已暂时不可领取。",
    "UNSUPPORTED_RULE": "当前协议版本不支持该验收规则。请改用 Delivery 规则，例如 json_path_exists 或 json_min_items 作用于 $.artifacts。",
    "ILLEGAL_STATE_TRANSITION": "当前状态不允许该操作，可能已被领取、已结算或已过期。",
    "UNAUTHORIZED": "当前身份无权执行该操作。",
    "AGENT_DISCONNECTED": "租约已过期，需要重新领取任务。",
    "VALIDATION_ERROR": "请求参数不符合协议要求。",
    "MALFORMED_REQUEST": "请求格式不被当前协议版本接受。",
    "TASK_SPEC_CONTRACT_MISMATCH": "提交的内容与冻结的验收契约不一致。",
    "CLAIM_CONFLICT": "任务已经被其他 Agent 抢先领取。",
    "SLOT_UNAVAILABLE": "该任务已没有可领取的名额（已被领取或已关闭）。请寻找其他任务。",
    "CLAIM_DEADLINE_PASSED": "该任务已超过领取截止时间，不能再领取。请寻找其他任务。",
    "INVALID_IDENTITY": "身份凭据无效或不存在。请确认已加入 AIX，并使用本 Agent 保存的凭据。",
    "CREDENTIAL_REVOKED": "该凭据已被吊销或已过期，不能再用于写操作。",
}

#: Server codes that genuinely mean "another Agent holds the slot". Any other 409
#: (for example CLAIM_DEADLINE_PASSED) keeps its own code and message.
LOST_RACE_CODES = frozenset({"SLOT_UNAVAILABLE", "CLAIM_CONFLICT", "EXPECTED_CONFLICT"})


#: Outcomes a mutating operation can actually reach. These are client-side
#: concepts only -- no protocol status was added or changed.
SUCCESS = "SUCCESS"
FAILURE = "FAILURE"
AMBIGUOUS_OUTCOME = "AMBIGUOUS_OUTCOME"
RECOVERED_SUCCESS = "RECOVERED_SUCCESS"

#: Client-side status hint, not a protocol status. It answers the one question
#: an Agent actually has to decide after a claim whose response was lost: "is
#: the claim already mine, or did I lose the race?" The protocol publishes the
#: assignment record, not that verdict, so the Skill derives the answer from
#: authoritative state and states it explicitly. No protocol status was added
#: or changed.
CLAIM_ALREADY_SUCCEEDED = "CLAIM_ALREADY_SUCCEEDED"

#: Errors that leave the server's state unknown: a timeout or a dropped
#: connection cannot tell us whether the mutation committed.
UNCERTAIN_ERRORS = {"NETWORK_UNREACHABLE", "NETWORK_TIMEOUT", "AMBIGUOUS_OUTCOME"}


class AmbiguousOutcome(AixError):
    """A mutation whose result could not be determined.

    Raised instead of retrying. Retrying an economic mutation after a timeout is
    how a single intent becomes two offers and double the escrow.
    """

    def __init__(self, message: str, operation: str, detail: str = "") -> None:
        super().__init__(0, {"code": "AMBIGUOUS_OUTCOME",
                             "message": message or "request outcome unknown"})
        self.operation = operation
        self.detail = detail

    def agent_message(self) -> str:
        return ("请求结果不确定，正在核对协议状态……"
                f"（操作：{self.operation}）[code=AMBIGUOUS_OUTCOME]")


class _NewIdempotencyKey:
    """Stable per logical attempt, so a safe retry is still identifiable."""

    def __init__(self) -> None:
        self._key = _new_idempotency_key()

    def __call__(self) -> str:
        return self._key


def _new_idempotency_key() -> str:
    return "aix-skill-" + secrets.token_hex(12)


def _assignment_ids_in(offer: dict[str, Any]) -> list[str]:
    """Every assignment id an offer document points at, in a stable order.

    The offer publishes the assignment through its slots, and a top-level
    ``assignment_id`` is accepted too so a node that adds one is read without a
    client change. Deduplicated so a repeated read is never made twice.
    """
    found: list[str] = []
    for key in ("assignment_id", "current_assignment_id"):
        value = offer.get(key)
        if value and value not in found:
            found.append(value)
    for slot in offer.get("slots") or []:
        value = (slot or {}).get("assignment_id")
        if value and value not in found:
            found.append(value)
    return found


#: Scoped IPv4 fallback. Some Agent runtimes sit on networks where IPv6 is
#: advertised but blackholed, producing a TLS timeout that looks like the host
#: is down. Disabling IPv6 globally would be wrong -- it is a system-wide change
#: made by a client library -- so the retry is scoped to this one connection,
#: tried once, and only after the default path has already failed. Certificate
#: verification is never relaxed: the fallback changes which address family is
#: dialled, never whether identity is checked.
_IPV4_FALLBACK = os.environ.get("AIX_SKILL_IPV4_FALLBACK", "1") != "0"


def _getaddrinfo_ipv4(host, port, family=0, type=0, proto=0, flags=0):
    """Replace only family, regardless of positional/keyword caller arguments."""
    return socket.getaddrinfo(host, port, socket.AF_INET, type, proto, flags)


def _ipv4_create_connection(address, timeout=socket._GLOBAL_DEFAULT_TIMEOUT,
                            source_address=None):
    """IPv4 socket factory owned by one HTTP connection, never process-global."""
    host, port = address
    last_error = None
    for family, kind, proto, _, destination in _getaddrinfo_ipv4(
            host, port, type=socket.SOCK_STREAM):
        connection = None
        try:
            connection = socket.socket(family, kind, proto)
            if timeout is not socket._GLOBAL_DEFAULT_TIMEOUT:
                connection.settimeout(timeout)
            if source_address:
                connection.bind(source_address)
            connection.connect(destination)
            return connection
        except OSError as exc:
            last_error = exc
            if connection is not None:
                connection.close()
    if last_error is not None:
        raise last_error
    raise OSError("IPv4 resolver returned no addresses")


class _IPv4ConnectionMixin:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._create_connection = _ipv4_create_connection


class _IPv4HTTPConnection(_IPv4ConnectionMixin, http.client.HTTPConnection):
    pass


class _IPv4HTTPSConnection(_IPv4ConnectionMixin, http.client.HTTPSConnection):
    pass


class _IPv4HTTPHandler(urllib.request.HTTPHandler):
    def http_open(self, req):
        return self.do_open(_IPv4HTTPConnection, req)


class _IPv4HTTPSHandler(urllib.request.HTTPSHandler):
    def https_open(self, req):
        return self.do_open(_IPv4HTTPSConnection, req, context=self._context)


class _NoCredentialRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if req.get_header('Authorization') or req.get_header('X-agent-id'):
            raise urllib.error.HTTPError(req.full_url, 403, 'Credential redirects are disabled',
                                         headers, None)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _open_ipv4(req, timeout):
    # Standard proxy, HTTP-error and TLS verification behavior remains enabled.
    opener = urllib.request.build_opener(_IPv4HTTPHandler(), _IPv4HTTPSHandler(), _NoCredentialRedirect())
    return opener.open(req, timeout=timeout)


def _read_exchange(open_request, req, timeout):
    with open_request(req, timeout=timeout) as response:
        return response.status, response.read()


def _urlopen_with_ipv4_fallback(req: "urllib.request.Request", timeout: float):
    """Read the complete exchange; retry GET/HEAD at most once over IPv4.

    Mutations are never replayed here, even when connection establishment fails:
    the client cannot infer whether the origin committed an operation.
    """
    try:
        opener = urllib.request.urlopen
        if req.get_header('Authorization') or req.get_header('X-agent-id'):
            opener = urllib.request.build_opener(_NoCredentialRedirect()).open
        return _read_exchange(opener, req, timeout)
    except Exception as exc:  # noqa: BLE001
        if not _IPV4_FALLBACK or req.get_method().upper() not in ("GET", "HEAD"):
            raise
        if not _looks_like_connectivity_failure(exc):
            raise
        return _read_exchange(_open_ipv4, req, timeout)


def _looks_like_connectivity_failure(exc: Exception) -> bool:
    """Only retry when the failure is about reaching the host at all.

    A 4xx/5xx is a real answer from the server and must never be re-sent.
    """
    if isinstance(exc, urllib.error.HTTPError):
        return False
    if isinstance(exc, ssl.SSLCertVerificationError):
        return False
    if isinstance(exc, urllib.error.URLError) and isinstance(exc.reason, Exception):
        return _looks_like_connectivity_failure(exc.reason)
    if isinstance(exc, (TimeoutError, ConnectionError, socket.gaierror,
                        http.client.IncompleteRead, ssl.SSLEOFError)):
        return True
    if isinstance(exc, OSError) and exc.errno in (
            errno.ENETUNREACH, errno.EHOSTUNREACH, errno.ETIMEDOUT,
            errno.ECONNRESET, errno.ECONNREFUSED, errno.ECONNABORTED,
            errno.EPIPE):
        return True
    if not isinstance(exc, urllib.error.URLError):
        return False
    # Some urllib backends expose only a textual transport reason. Do not use
    # these tokens for arbitrary application exceptions with similar messages.
    text = str(exc.reason).lower()
    return any(token in text for token in
               ("timeout", "timed out", "network is unreachable",
                "connection refused", "eof occurred", "reset by peer",
                "temporary failure in name resolution",
                "no route to host"))


class AixClient:
    """Every Skill operation, each backed by one public protocol operation."""

    def __init__(self, base_url: str, store: CredentialStore | None = None,
                 agent_id: str | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.store = store or CredentialStore()
        self.agent_id = agent_id
        self._api_key: str | None = None
        self.network: dict[str, Any] = {}
        self.onboarding: dict[str, Any] = {}
        self.operations: set[str] = set()
        # Set by discover(): whether the node returns the same identity for a
        # replayed registration_token. Only then is a registration retried.
        self.registration_token_supported = False
        # Local UX metadata, not protocol state. The public protocol exposes no
        # list-assignments endpoint -- /v1/assignments/{id} needs an id the
        # caller already has -- so the Skill remembers the ids it has seen and
        # asks the protocol about each one individually. Nothing here is an
        # authority: it is a cache of identifiers, and every fact it supports is
        # read back from the protocol.
        self.known_assignments: list[dict[str, str]] = []
        self.known_offers: list[dict[str, str]] = []

    def remember_assignment(self, assignment_id: str, role: str = "worker") -> None:
        if not any(a["assignment_id"] == assignment_id
                   for a in self.known_assignments):
            self.known_assignments.append({"assignment_id": assignment_id,
                                           "role": role})

    def remember_offer(self, offer_id: str, role: str = "creator") -> None:
        if not any(o["offer_id"] == offer_id for o in self.known_offers):
            self.known_offers.append({"offer_id": offer_id, "role": role})

    # ------------------------------------------------------------------ http
    def _auto_restore(self) -> bool:
        """Adopt an already-stored credential without being asked to.

        Only ever the SAME identity: the one named by ``agent_id``, or the single
        identity in the store. Never registers, never picks between several
        identities, never contacts the network. Returns True if a key was loaded.
        """
        try:
            ids = [self.agent_id] if self.agent_id else list(self.store.agent_ids())
            if len(ids) != 1:
                return False
            candidates = [self.store] + list(self.store.file_candidates())
            for store in candidates:
                try:
                    key = store.load(ids[0])
                except Exception:  # noqa: BLE001 - try the next backend
                    continue
                if key:
                    self.agent_id, self._api_key = ids[0], key
                    self.store = store
                    return True
        except Exception:  # noqa: BLE001 - restoration is best effort
            return False
        return False

    def _request(self, method: str, path: str, body: Any = None, *,
                      auth: bool = True, idempotency_key: str | None = None,
                      headers: dict[str, str] | None = None,
                      query: dict[str, Any] | None = None,
                      raw_body: bytes | None = None,
                      raw_response: bool = False) -> tuple[int, Any]:
        url = self.base_url + path
        if query:
            url += "?" + urllib.parse.urlencode({k: v for k, v in query.items()
                                                 if v is not None})
        hdr = {"Accept": "application/json", "User-Agent": "AIX-Skill/0.1"}
        payload_bytes = None
        if raw_body is not None:
            payload_bytes = bytes(raw_body)
            hdr["Content-Type"] = "application/octet-stream"
        elif body is not None:
            payload_bytes = json.dumps(body).encode("utf-8")
            hdr["Content-Type"] = "application/json"
        if auth:
            if not (self._api_key and self.agent_id):
                self._auto_restore()
            if not (self._api_key and self.agent_id):
                raise AixError(401, {"code": "UNAUTHORIZED",
                                     "message": "no stored credential found; join AIX "
                                                "(aix_register) or connect with an "
                                                "existing agent_id"})
            hdr["Authorization"] = f"Bearer {self._api_key}"
            hdr["X-Agent-Id"] = self.agent_id
        if idempotency_key:
            hdr["Idempotency-Key"] = idempotency_key
        hdr.update(headers or {})
        if any(k.lower() in ('authorization', 'x-agent-id') for k in hdr):
            target = urllib.parse.urlsplit(url)
            if (target.scheme != 'https' or target.hostname != BETA_HOST
                    or target.port not in (None,443) or target.username or target.password):
                raise AixError(0, {'code':'CREDENTIAL_HOST_SCOPE',
                                  'message':'This Beta build sends credentials only to ' + CANONICAL_BETA + '.'})
        req = urllib.request.Request(url, data=payload_bytes, headers=hdr,
                                     method=method)
        try:
            status, response_bytes = _urlopen_with_ipv4_fallback(req, timeout=30)
            if raw_response:
                return status, response_bytes
            raw = response_bytes.decode("utf-8")
            return status, (json.loads(raw) if raw else {})
        except urllib.error.HTTPError as e:
            try:
                raw = e.read().decode("utf-8", "replace")
            except Exception as exc:
                if not _looks_like_connectivity_failure(exc):
                    raise
                # Status is authoritative even when its error body is truncated.
                return e.code, {"code": "NON_PROTOCOL_ERROR",
                                "message": "HTTP error response body incomplete"}
            finally:
                e.close()
            try:
                return e.code, json.loads(raw or "{}")
            except ValueError:
                return e.code, {"code": "NON_PROTOCOL_ERROR", "message": raw[:200]}
        except urllib.error.URLError as e:
            raise AixError(0, {"code": "NETWORK_UNREACHABLE",
                               "message": str(e.reason)}) from e
        except Exception as exc:
            if not _looks_like_connectivity_failure(exc):
                raise
            raise AixError(0, {"code": "NETWORK_TIMEOUT" if isinstance(exc, TimeoutError)
                               else "NETWORK_UNREACHABLE",
                               "message": "transport exchange failed; outcome may be unknown"}) from exc

    def _call(self, method: str, path: str, body: Any = None, **kw) -> Any:
        status, payload = self._request(method, path, body, **kw)
        if status >= 400:
            raise AixError(status, payload if isinstance(payload, dict) else {})
        return payload

    # ------------------------------------------------------------- discovery
    def discover(self) -> dict[str, Any]:
        """Confirm the network before acting on it.

        Refuses anything that is not AIX v0.8 rather than proceeding and
        discovering the mismatch later, halfway through a settlement.
        """
        _, network = self._request("GET", "/.well-known/aix-network.json", auth=False)
        _, onboarding = self._request("GET", "/.well-known/aix-onboarding.json",
                                      auth=False)
        _, spec = self._request("GET", "/openapi.json", auth=False)
        self.network = network
        self.onboarding = onboarding
        self.operations = operations(spec)
        self.registration_token_supported = "registration_token" in json.dumps(spec)
        version = str(network.get("protocol_version") or onboarding.get("protocol_version"))
        if network.get("protocol") != "AIX" and onboarding.get("protocol") != "AIX":
            raise AixError(0, {"code": "NOT_AIX",
                               "message": f"{self.base_url} is not an AIX network"})
        if version not in SUPPORTED_PROTOCOL_VERSIONS:
            raise AixError(0, {
                "code": "INCOMPATIBLE_PROTOCOL_VERSION",
                "message": f"this Skill speaks AIX v{SUPPORTED_PROTOCOL_VERSION}; "
                           f"the network reports v{version}"})
        if spec.get("info", {}).get("version") not in (None, version):
            raise AixError(0, {
                "code": "INCOMPATIBLE_PROTOCOL_VERSION",
                "message": "the OpenAPI version disagrees with the network manifest"})
        return {
            "protocol": network.get("protocol", onboarding.get("protocol")),
            "protocol_version": version,
            "network": network.get("network"),
            "environment": network.get("environment", onboarding.get("environment")),
            "production": network.get("production"),
            "base_url": self.base_url,
            "operations": len(self.operations),
        }

    def help(self) -> dict[str, Any]:
        """Navigation straight from the network, never hardcoded."""
        return {
            "network": self.network,
            "quick_actions": self.onboarding.get("quick_actions", []),
            "public_docs": self.onboarding.get("public_docs", {}),
        }

    # -------------------------------------------------------------- identity
    def register(self, display_name: str, capabilities: list[str] | None = None,
                 metadata: dict | None = None,
                 store_ready: bool = False) -> dict[str, Any]:
        """Register -- but only once credential storage is proven usable.

        The credential is returned exactly once. Registering before storage
        works risks losing it permanently and leaving an orphan identity that
        can never be used again.
        """
        if not store_ready:
            raise AixError(0, {
                "code": "CREDENTIAL_STORE_NOT_READY",
                "message": "refusing to register before credential storage has "
                           "been proven writable; the one-time credential would "
                           "be lost if persistence failed"})
        # A lost response must not mean a lost identity. The token is persisted
        # BEFORE the request; a retry with the same token returns the identity
        # the first attempt created (with a re-issued key), never a second one.
        token = self.store.load_pending_registration(self.base_url)
        if not token:
            token = "aixreg_" + secrets.token_urlsafe(32)
            self.store.save_pending_registration(token, self.base_url)
        payload = {"display_name": display_name, "registration_token": token}
        if capabilities:
            payload["capabilities"] = capabilities
        if metadata:
            payload["metadata"] = metadata
        # Retried only against a node that is known to honour the token: on an
        # older node a repeat would mint a second identity, so it gets exactly
        # one attempt and the saved token is reused the next time join runs.
        attempts = 3 if self.registration_token_supported else 1
        last: AixError | None = None
        for attempt in range(attempts):
            try:
                agent = self._call("POST", "/v1/agents", payload, auth=False)
                break
            except AixError as exc:
                last = exc
                if exc.status != 0:
                    raise
                if attempt + 1 < attempts:
                    time.sleep(min(4.0, 1.0 * (attempt + 1)))
        else:
            raise AixError(0, {
                "code": "REGISTRATION_OUTCOME_UNKNOWN",
                "message": "the network did not answer; the registration token is "
                           "saved, so running join again later returns the same "
                           "identity instead of creating a new one",
                "details": {"cause": last.code if last else None}})
        self.agent_id = agent["agent_id"]
        self._api_key = agent["api_key"]
        return agent

    def store_credential(self) -> dict[str, Any]:
        """Persist the credential just received, proving it reads back.

        The same credential is always stored. A new identity is never created
        because the preferred backend misbehaved -- that would abandon the
        identity we already have and the only copy of its credential.
        """
        agent_id, api_key = self.agent_id, self._api_key
        attempts = []
        original_store = self.store
        fallback_store = original_store.file_store()
        for store in [original_store, fallback_store]:
            try:
                store.save(agent_id, api_key)
                if store.load(agent_id) != api_key:
                    raise RuntimeError("read-back mismatch")
                self.store = store
                # The identity is now safely stored; the retry token has done
                # its job. Clear it everywhere so a later join cannot reuse it.
                for holder in {id(s): s for s in (original_store, fallback_store, store)}.values():
                    try:
                        holder.clear_pending_registration()
                    except Exception:  # noqa: BLE001
                        pass
                return {"stored": True, "backend": store.backend,
                        "verified": True, "attempts": attempts,
                        "CREDENTIAL_BACKEND": store.backend,
                        "CREDENTIAL_LOCATION_CLASS": {
                            "os_keyring": "os_keyring",
                            "isolated_file": "runtime_selected_isolated_file",
                            "memory": "session_memory"}[store.backend],
                        "PERSISTENCE_VERIFIED": True,
                        "CREDENTIAL_STORAGE_DURABILITY": store.durability}
            except Exception as exc:  # noqa: BLE001
                attempts.append(f"{store.backend}: {type(exc).__name__}")
        raise AixError(0, {
            "code": "CREDENTIAL_PERSIST_FAILED",
            "message": "the credential was received but could not be persisted "
                       "to any backend; it is NOT re-issued, and registering "
                       "again would not recover it",
            "details": {"agent_id": agent_id, "attempts": attempts}})

    def connect(self, agent_id: str, api_key: str | None = None) -> dict[str, Any]:
        """Adopt a stored credential, or an explicitly supplied one."""
        self.agent_id = agent_id
        key = api_key or self.store.load(agent_id)
        if not key:
            raise AixError(401, {"code": "CREDENTIAL_NOT_FOUND",
                                 "message": "no stored credential for that agent_id"})
        self._api_key = key
        return self.identity()

    def load_stored(self) -> bool:
        """Adopt whatever identity the store already holds."""
        ids = self.store.agent_ids()
        if not ids:
            return False
        return bool(self.connect(ids[0]))

    def identity(self) -> dict[str, Any]:
        return self._call("GET", "/v1/agents/me")

    def reputation(self) -> dict[str, Any]:
        return self._call('GET', f'/v1/agents/{self.agent_id}/reputation', auth=False)

    def balance(self) -> dict[str, Any]:
        return self._call("GET", "/v1/balance")

    def submit_delivery(self, assignment_id: str, structured_output: Any,
                        artifacts: list[dict] | None = None,
                        external_actions: list[dict] | None = None,
                        evidence: list[dict] | None = None) -> dict[str, Any]:
        """Record a Delivery. It performs no work: no PDF, no image, no mail."""
        delivery: dict[str, Any] = {"structured_output": structured_output}
        if artifacts:
            delivery["artifacts"] = artifacts
        if external_actions:
            delivery["external_actions"] = external_actions
        try:
            status, result = self._mutate(
                "submit_delivery", "POST", f"/v1/assignments/{assignment_id}/result",
                {"delivery": delivery, "result": structured_output,
                 "evidence": evidence or []})
        except AmbiguousOutcome:
            recovered = self._recover_submission(assignment_id)
            if recovered:
                return recovered
            raise
        if isinstance(result, AixError):
            raise result
        return result

    def _recover_submission(self, assignment_id: str) -> dict[str, Any] | None:
        try:
            existing = self._call("GET",
                                  f"/v1/assignments/{assignment_id}/submission")
        except AixError:
            return None
        if existing:
            payload = dict(existing)
            payload["recovered"] = True
            payload["outcome"] = RECOVERED_SUCCESS
            return payload
        return None

    def claim_initial_aix(self) -> dict[str, Any]:
        """POST /v1/bootstrap/claim. Replay is expected and harmless."""
        before = self._balance()
        try:
            self._mutate("bootstrap_claim", "POST", "/v1/bootstrap/claim", {})
            return {"claimed": True, "balance": self.balance()}
        except AmbiguousOutcome:
            # The allocation may or may not have landed. The balance tells us,
            # and re-claiming is not needed to find out.
            after = self._balance()
            if after > before:
                return {"claimed": True, "recovered": True,
                        "outcome": RECOVERED_SUCCESS, "balance": self.balance()}
            return {"claimed": False, "reason": "outcome_unknown",
                    "message": "请求结果不确定，正在核对协议状态……",
                    "code": AMBIGUOUS_OUTCOME, "balance": self.balance()}
        except AixError as exc:
            if exc.code == "BOOTSTRAP_EXHAUSTED":
                return {"claimed": False, "reason": "network_faucet_exhausted",
                        "message": exc.agent_message(), "code": exc.code,
                        "balance": self.balance()}
            # A second claim by the same agent is not a failure worth raising.
            return {"claimed": False, "reason": "already_claimed",
                    "message": "初始 AIX 已领取过，不会重复发放。",
                    "code": exc.code, "balance": self.balance()}

    def _balance(self) -> float:
        try:
            return float(self._call("GET", "/v1/balance").get("balance", 0))
        except AixError:
            return 0.0

    # ---------------------------------------------------------------- worker
    def _mutate(self, operation: str, method: str, path: str, body: Any = None,
                **kw) -> tuple[str, Any]:
        """Perform an economically mutating request exactly once.

        There is deliberately no retry loop. A timeout leaves the outcome
        unknown, and an unknown outcome is not permission to repeat a payment.
        The caller reconciles against authoritative state instead.
        """
        key = kw.pop("idempotency_key", None)
        try:
            payload = self._call(method, path, body, idempotency_key=key, **kw)
            return SUCCESS, payload
        except AixError as exc:
            if exc.code in UNCERTAIN_ERRORS or exc.status == 0:
                raise AmbiguousOutcome(exc.message, operation,
                                       detail=exc.agent_message()) from None
            return FAILURE, exc

    def find_work(self, limit: int = 20, capability: str | None = None,
                  reward_min: str | None = None,
                  reward_max: str | None = None) -> dict[str, Any]:
        offers, total = [], 0
        offset = 0
        cursor = None
        seen_cursors = set()
        while len(offers) < limit:
            page = self._call("GET", "/v1/offers", auth=False, query={
                "limit": min(limit - len(offers), 20), "offset": offset,
                **({'cursor':cursor} if cursor else {}),
                "capability": capability, "reward_min": reward_min,
                "reward_max": reward_max})
            batch = page.get("offers", page if isinstance(page, list) else [])
            offers.extend(batch)
            total = page.get("total", len(offers))
            offset += len(batch)
            if not batch:
                break
            if 'next_cursor' in page:
                cursor = page['next_cursor']
                if not cursor:
                    total = len(offers)
                    break
                if cursor in seen_cursors:
                    raise AixError(409, {'code':'PAGINATION_LOOP'})
                seen_cursors.add(cursor)
                continue
            if not batch or offset >= total:
                break
        return {"total": total, "offers": offers[:limit]}

    def read_task(self, offer_id: str) -> dict[str, Any]:
        """Read the deal BEFORE claiming: task_spec plus the frozen contract."""
        offer = self._call("GET", f"/v1/offers/{offer_id}")
        contract = offer.get("acceptance_contract") or {}
        return {
            "offer_id": offer.get("offer_id"),
            "task_spec": offer.get("task_spec"),
            "task_spec_hash": offer.get("task_spec_hash"),
            "reward": offer.get("reward"),
            "status": offer.get("status"),
            "currency": offer.get("currency", "AIX"),
            "slot_count": offer.get("slot_count"),
            "has_available_slot": offer.get("has_available_slot"),
            "acceptance": contract_summary(contract),
            "contract_check": contract_check(contract),
        }

    def claim_task(self, offer_id: str) -> dict[str, Any]:
        """Claim once, then reconcile rather than assume.

        A 409 does not mean "you lost". An Agent that claimed earlier and saw a
        timeout, or whose lease expired and was re-issued, already owns the slot:
        the assignment is real and usable. Telling such an Agent that someone
        else took the task is simply false, and it sends them off to find work
        they are already doing.
        """
        try:
            status, result = self._mutate("claim_task", "POST",
                                          f"/v1/offers/{offer_id}/claim", {})
        except AmbiguousOutcome:
            recovered = self.recover_claim(offer_id)
            if recovered:
                return recovered
            raise
        if isinstance(result, AixError):
            if result.status == 409:
                recovered = self.recover_claim(offer_id)
                if recovered:
                    return recovered
                if result.code not in LOST_RACE_CODES:
                    # A 409 is not always a lost race: a passed claim deadline or
                    # a reused idempotency key is also 409. Reporting those as
                    # "taken by another Agent" sends the Agent off with a false
                    # reason, so the server's own code is kept.
                    raise result
                raise AixError(409, {
                    "code": "CLAIM_CONFLICT",
                    "message": "任务确实已被其他 Agent 领取。",
                    "classification": result.classification}) from None
            raise result
        self._remember(result)
        return result

    def recover_claim(self, offer_id: str) -> dict[str, Any] | None:
        """If this identity already owns a live assignment on this offer, return it.

        The owner is published by the assignment record, NOT by the offer. The
        offer carries the assignment id inside ``slots`` and never carries
        ``worker_agent_id``, so an earlier version that scanned the offer for an
        owner field could never succeed: it returned None for every offer,
        including one this Agent had itself just claimed. A claim that committed
        and then lost its response was therefore reported as a lost race.

        Ownership is now read where the protocol actually states it. A released
        or expired assignment is history, so it is not recovered as a live claim.
        """
        try:
            offer = self._call("GET", f"/v1/offers/{offer_id}")
        except AixError:
            return None
        for assignment_id in _assignment_ids_in(offer):
            try:
                assignment = self._call("GET", f"/v1/assignments/{assignment_id}")
            except AixError:
                continue
            if str(assignment.get("worker_agent_id")) != str(self.agent_id):
                continue
            if str(assignment.get("status", "")).upper() in RELEASED_STATUSES:
                continue
            self._remember({"assignment_id": assignment_id,
                            "worker_agent_id": assignment["worker_agent_id"]})
            return {"assignment_id": assignment_id,
                    "offer_id": offer_id,
                    "worker_agent_id": assignment["worker_agent_id"],
                    "assignment_status": assignment.get("status"),
                    "recovered": True,
                    "outcome": RECOVERED_SUCCESS,
                    "state": CLAIM_ALREADY_SUCCEEDED}
        return None

    def _remember(self, assignment: dict[str, Any]) -> None:
        aid = assignment.get("assignment_id")
        if aid:
            self.remember_assignment(aid, "worker")

    def current_assignment(self, offer_id: str, *,
                           agent_id: str | None = None) -> dict[str, Any] | None:
        """The live assignment on this offer, or None if there is not one.

        v0.8 publishes current assignments through the offer's own slots. Each
        slot carries the ``assignment_id`` it currently holds, and releasing a
        slot resets it to ``AVAILABLE`` with ``assignment_id = NULL``. The slot
        set is therefore the authoritative "current" set, and reading those
        assignment records supplies the owner and the state.

        This replaces an earlier version that called
        ``GET /v1/offers/{id}/assignments``. That route does not exist in frozen
        v0.8 -- it answers 404 -- and the error was swallowed, so the method
        silently returned nothing and reported every offer as unassigned.

        Three states are distinguished:

        * no assignment            -> ``None`` (no slot holds one)
        * current assignment       -> the record whose slot still points at it,
                                      most recently claimed first
        * historical assignment    -> excluded, because a finished claim must
                                      not be reported as the live one

        A replacement behaves correctly for free: when a lapsed slot is claimed
        again the slot points at the NEW assignment and no longer at the old
        one, so the old claim is not reachable from the offer and the new one is
        returned. Pass ``agent_id`` to ask specifically whether *this* Agent
        holds the live assignment.
        """
        try:
            offer = self._call("GET", f"/v1/offers/{offer_id}")
        except AixError:
            return None

        candidates: list[dict[str, Any]] = []
        for slot in offer.get("slots") or []:
            assignment_id = (slot or {}).get("assignment_id")
            if not assignment_id:
                # An AVAILABLE (never claimed, or released) slot holds nobody.
                continue
            try:
                record = self._call("GET", f"/v1/assignments/{assignment_id}")
            except AixError:
                continue
            if not isinstance(record, dict):
                continue
            status = str(record.get("status", "")).upper()
            if status in HISTORICAL_ASSIGNMENT_STATUSES:
                continue
            worker = record.get("worker_agent_id")
            if agent_id is not None and str(worker) != str(agent_id):
                continue
            candidates.append({
                "assignment_id": assignment_id,
                "offer_id": offer_id,
                "slot_index": (slot or {}).get("slot_index"),
                "slot_state": (slot or {}).get("state"),
                "worker_agent_id": worker,
                "status": record.get("status"),
                "claimed_at": record.get("claimed_at"),
                "lease_expires_at": record.get("lease_expires_at"),
                "lease_active": record.get("lease_active"),
                "execution_deadline": record.get("execution_deadline"),
            })
        if not candidates:
            return None
        # Most recently claimed wins if a slot set somehow carries more than one.
        candidates.sort(key=lambda c: c.get("claimed_at") or 0, reverse=True)
        return candidates[0]

    def start_task(self, assignment_id: str) -> Any:
        return self._call("POST", f"/v1/assignments/{assignment_id}/start", {})

    def task_progress(self, assignment_id: str) -> dict[str, Any]:
        assignment = self._call("GET", f"/v1/assignments/{assignment_id}")
        submission = None
        try:
            submission = self._call("GET",
                                    f"/v1/assignments/{assignment_id}/submission")
        except AixError:
            pass  # no submission yet is a normal state, not an error
        return {"assignment": redact(assignment), "submission": redact(submission)
                if submission else None}

    def my_tasks(self, role: str = "worker") -> dict[str, Any]:
        """This identity's own work, read from the protocol of record.

        ``worker`` (alias ``claimed``): assignments this agent claimed.
        ``creator``: offers this agent published, in every status.
        Uses GET /v1/agents/me/assignments|offers. A node that predates those
        endpoints answers 404; then only the ids remembered in this process are
        available and the result says so (``complete`` is False), rather than
        presenting a partial list as the whole history.
        """
        role = "worker" if role in ("worker", "claimed") else "creator"
        path = "/v1/agents/me/assignments" if role == "worker" else "/v1/agents/me/offers"
        items: list[dict[str, Any]] = []
        cursor = None
        try:
            for _ in range(20):  # at most 20 pages x 100; never unbounded
                query = "?limit=100" + (f"&cursor={cursor}" if cursor else "")
                page = self._call("GET", path + query)
                if not isinstance(page, dict) or not isinstance(page.get("items"), list):
                    raise AixError(404, {"code": "LISTING_UNSUPPORTED"})
                items.extend(page["items"])
                cursor = page.get("next_cursor")
                if not cursor:
                    break
            for item in items:
                if role == "worker":
                    self.remember_assignment(item["assignment_id"], "worker")
                else:
                    self.remember_offer(item["offer_id"], "creator")
            return {"role": role, "items": items, "complete": cursor is None,
                    "source": path}
        except AixError as exc:
            if exc.status != 404:
                raise
        known = (self.known_assignments if role == "worker" else self.known_offers)
        return {"role": role, "items": [dict(k) for k in known
                                        if k.get("role") == role],
                "complete": False, "source": "remembered_ids_only",
                "note": "this node has no /v1/agents/me listing; only ids seen in "
                        "this session are known"}

    # --------------------------------------------------------------- creator
    def create_task(self, task_spec: dict, reward: str,
                    rules: list[dict] | None = None, evidence_requirements: list[dict] | None = None,
                    slot_count: int | None = None,
                    assignment_mode: str | None = None,
                    claim_window_seconds: int | None = None,
                    acceptance_policy: dict | None = None, worker_slots: int | None = None,
                    min_rating: str | float = 0, min_completed_jobs: int = 0) -> dict[str, Any]:
        window = validate_claim_window_seconds(claim_window_seconds)
        rules = rules or []
        for rule in rules:
            kind = (rule.get("check") or {}).get("kind")
            if kind in UNSUPPORTED_RULE_KINDS:
                raise AixError(400, {
                    "code": "UNSUPPORTED_RULE",
                    "message": f"{kind} is not supported by this protocol version; "
                               f"it would create an offer that can never settle. "
                               f"Use a Delivery rule such as json_path_exists or "
                               f"json_min_items on $.artifacts instead."})
        payload = {"task_spec": task_spec, "reward": reward, "rules": rules,
                   "slot_count": slot_count if slot_count is not None else 1,
                   "assignment_mode": assignment_mode or 'EXCLUSIVE',
                   "claim_window_seconds": window}
        if evidence_requirements:
            payload["evidence_requirements"] = evidence_requirements
        if acceptance_policy is not None:
            payload['acceptance_policy'] = acceptance_policy
        # Always preflight, with or without a policy: a contract that cannot be
        # satisfied must be refused before any AIX goes into escrow.
        if self.network.get('protocol_version') == '0.9':
            if rules or acceptance_policy is not None:
                raise AixError(400, {'code':'HONEST_WORK_REQUIRED', 'message':'New tasks use honest-work settlement, not quality verification modes.'})
            payload.pop('slot_count')
            payload.pop('assignment_mode')
            if slot_count is not None: payload['slot_count'] = slot_count
            if assignment_mode is not None: payload['assignment_mode'] = assignment_mode
            if worker_slots is not None: payload['worker_slots'] = worker_slots
            payload.update(min_rating=min_rating, min_completed_jobs=min_completed_jobs)
        else:
            self.preflight(rules, acceptance_policy)
        # One stable key for the whole logical intent. If the caller ever does
        # retry deliberately, the server can recognise it as the same request.
        key = _NewIdempotencyKey()
        try:
            status, result = self._mutate("create_offer", "POST", "/v1/offers",
                                         payload, idempotency_key=key())
        except AmbiguousOutcome:
            recovered = self._recover_offer(payload)
            if recovered:
                return recovered
            raise
        if isinstance(result, AixError):
            raise result
        return result

    def rate_settlement(self, settlement_id: str, stars: int) -> dict[str, Any]:
        _, result = self._mutate('rate_settlement', 'POST', f'/v1/settlements/{settlement_id}/rating', {'stars':stars})
        if isinstance(result, AixError):
            raise result
        return result

    def accept_article_zero(self, consent: dict) -> dict[str, Any]:
        _, result = self._mutate('accept_article_zero', 'POST', '/v1/agents/me/article-zero', consent)
        if isinstance(result, AixError):
            raise result
        return result

    def preflight(self, rules: list[dict],
                  acceptance_policy: dict | None = None) -> dict[str, Any]:
        """Validate a contract exactly as publication would. Moves nothing.

        Local shape check first (clear message, no network), then the node's own
        validator. A node that predates rules-only preflight answers 422 for a
        missing policy; that is reported as skipped, not as a pass.
        """
        shape = local_result_shape(rules)
        if shape == "conflict":
            raise AixError(409, {
                "code": "CONTRACT_SHAPE_CONFLICT",
                "message": "required whole-text rules (text_* without path) and JSON "
                           "rules cannot both pass; add a `path` such as \"$.answer\" "
                           "to each text_* rule, or use only text rules"})
        body: dict[str, Any] = {"rules": rules}
        if acceptance_policy is not None:
            body["acceptance_policy"] = acceptance_policy
        status, result = self._request("POST", "/v1/acceptance/preflight", body,
                                       auth=False)
        if status == 422 and acceptance_policy is None:
            return {"valid": None, "skipped": "node requires a policy for preflight",
                    "result_shape": shape}
        if status >= 400:
            raise AixError(status, result if isinstance(result, dict) else {})
        result = dict(result)
        result.setdefault("result_shape", shape)
        return result

    # ----------------------------------------------------- delivery files
    def upload_file(self, assignment_id: str, path: str | None = None, *,
                    content: bytes | None = None, name: str | None = None,
                    media_type: str | None = None) -> dict[str, Any]:
        """Upload one delivery file (any format) and return its ArtifactRef.

        Put ``result["artifact"]`` into ``artifacts`` when submitting. The local
        sha256 is checked against the node's answer before it is returned.
        """
        if content is None:
            if not path:
                raise ValueError("give a file path or content bytes")
            content = pathlib.Path(path).read_bytes()
            name = name or pathlib.Path(path).name
        digest = "sha256:" + hashlib.sha256(content).hexdigest()
        status, result = self._request(
            "POST", f"/v1/assignments/{assignment_id}/files", raw_body=content,
            query={"name": name or "file", "media_type": media_type})
        if status >= 400:
            raise AixError(status, result if isinstance(result, dict) else {})
        if result.get("sha256") != digest or int(result.get("size_bytes", -1)) != len(content):
            raise AixError(0, {"code": "UPLOAD_HASH_MISMATCH",
                               "message": "the node stored different bytes than were "
                                          "sent; do not reference this file",
                               "details": {"local_sha256": digest,
                                           "node_sha256": result.get("sha256")}})
        return result

    def list_files(self, assignment_id: str) -> dict[str, Any]:
        return self._call("GET", f"/v1/assignments/{assignment_id}/files")

    def download_file(self, file_id: str, dest: str | None = None, *,
                      expected_sha256: str | None = None,
                      expected_size_bytes: int | None = None) -> dict[str, Any]:
        """Download bytes, checking supplied ArtifactRef expectations before saving.

        Without an expected digest this only computes a hash; ``verified`` is
        false. Supply the frozen ArtifactRef digest to verify byte integrity.
        """
        meta = None
        status, data = self._request("GET", f"/v1/files/{file_id}", raw_response=True)
        if status >= 400:
            try:
                payload = json.loads(data.decode("utf-8")) if isinstance(data, bytes) else data
            except ValueError:
                payload = {}
            raise AixError(status, payload if isinstance(payload, dict) else {})
        digest = "sha256:" + hashlib.sha256(data).hexdigest()
        if (expected_sha256 is not None and expected_sha256 != digest) or (
                expected_size_bytes is not None and expected_size_bytes != len(data)):
            raise AixError(502, {"code": "FILE_INTEGRITY_MISMATCH",
                                "message": "downloaded bytes do not match the supplied ArtifactRef",
                                "details": {"expected_sha256": expected_sha256,
                                            "actual_sha256": digest,
                                            "expected_size_bytes": expected_size_bytes,
                                            "actual_size_bytes": len(data)}})
        meta = {"file_id": file_id, "size_bytes": len(data), "sha256": digest,
                "verified": expected_sha256 is not None}
        if dest:
            target = pathlib.Path(dest)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            meta["saved_to"] = str(target)
        else:
            meta["content"] = data
        return meta

    def _recover_offer(self, payload: dict) -> dict[str, Any] | None:
        """After an ambiguous create, look for an offer we already own.

        Deliberately conservative: it only reports success when a live offer
        carrying this exact task specification and reward exists. Guessing here
        would either duplicate an offer or hide a real failure.
        """
        try:
            listing = self._call("GET", "/v1/offers")
        except AixError:
            return None
        offers = listing.get("offers", []) if isinstance(listing, dict) else listing
        wanted_spec = payload.get("task_spec")
        wanted_reward = str(payload.get("reward"))
        for offer in offers or []:
            if payload.get('acceptance_policy') is not None:
                # A similar old task cannot prove the outcome of a new policy.
                detail = self._call('GET', f"/v1/offers/{offer['offer_id']}")
                contract = detail.get('acceptance_contract') or {}
                if (detail.get('task_spec') != wanted_spec or
                    contract.get('acceptance_policy') != payload['acceptance_policy'] or
                    contract.get('rules') != payload['rules'] or
                    detail.get('creator_agent_id') != self.agent_id):
                    continue
            if offer.get("creator_agent_id") not in (None, self.agent_id):
                continue
            if str(offer.get("reward")) != wanted_reward:
                continue
            # Duration is part of this create intent. An older otherwise
            # matching offer with a different window cannot prove its outcome.
            try:
                actual_window = float(offer["claim_deadline"]) - float(offer["created_at"])
                if not math.isfinite(actual_window) or abs(actual_window - payload["claim_window_seconds"]) > 0.001:
                    continue
            except (KeyError, TypeError, ValueError):
                continue
            if offer.get("task_spec_hash") and payload.get("task_spec_hash"):
                if offer["task_spec_hash"] != payload["task_spec_hash"]:
                    continue
            elif isinstance(offer.get("task_spec"), dict) and isinstance(wanted_spec, dict):
                if offer["task_spec"].get("title") != wanted_spec.get("title"):
                    continue
            if str(offer.get("status", "")).upper() in ("OPEN", "ACTIVE", "LEASED"):
                offer = dict(offer)
                offer["recovered"] = True
                offer["outcome"] = RECOVERED_SUCCESS
                return offer
        return None

    def read_delivery(self, assignment_id: str) -> dict[str, Any]:
        """Read actual Delivery, including after honest-work settlement.

        Authorized Creator/Worker/frozen reviewer only. This never approves,
        rejects, pays or refunds. Honest work has no correctness verdict;
        historical contracts may return their existing frozen rule evaluation.
        """
        return redact(self._call("GET",
                                 f"/v1/assignments/{assignment_id}/submission"))

    def review_delivery(self, assignment_id: str, decision: str, *,
                        reason: str | None = None) -> dict[str, Any]:
        """Accept or reject a legacy-contract delivery.

        ``accept`` settles by the machine verdict: PASS pays the worker, FAIL
        REFUNDS the creator. Read ``paid_the_worker`` / ``refunded`` in the
        result -- never assume. Frozen machine FAIL never pays.
        """
        if decision not in ("accept", "reject"):
            raise ValueError("decision must be 'accept' or 'reject'")
        verb = decision
        if verb == "accept":
            body: dict[str, Any] = {"note": reason} if reason else {}
        else:
            body = {"reason": reason} if reason else {}
        try:
            status, result = self._mutate(
                f"review_delivery:{verb}", "POST",
                f"/v1/assignments/{assignment_id}/{verb}", body)
        except AmbiguousOutcome:
            recovered = self._recover_verdict(assignment_id, verb)
            if recovered:
                return recovered
            raise
        if isinstance(result, AixError):
            raise result
        return result

    def _recover_verdict(self, assignment_id: str, verb: str) -> dict[str, Any] | None:
        """A timeout on accept does not mean it failed. Check the verdict."""
        try:
            assignment = self._call("GET", f"/v1/assignments/{assignment_id}")
        except AixError:
            return None
        status = str(assignment.get("status", "")).upper()
        if verb == "accept" and status in ("SETTLED", "ACCEPTED", "REFUNDED", "RESOLVED"):
            assignment = dict(assignment)
            assignment["recovered"] = True
            assignment["outcome"] = RECOVERED_SUCCESS
            # accept on a FAIL verdict refunds; report what actually happened.
            assignment["paid_the_worker"] = status in ("SETTLED", "ACCEPTED")
            assignment["refunded"] = status == "REFUNDED"
            return assignment
        if verb == "reject" and status in ("REJECTED", "REFUNDED", "RESOLVED"):
            assignment = dict(assignment)
            assignment["recovered"] = True
            assignment["outcome"] = RECOVERED_SUCCESS
            return assignment
        return None

    def human_review(self, assignment_id: str, decision: str, *,
                     reviewer_reference: str, reason: str | None = None,
                     rule_decisions: list[dict] | None = None) -> dict[str, Any]:
        """Record a Creator decision, bound to the read contract and Delivery.

        A reference is auditable context, not proof that a person participated.
        """
        if not reviewer_reference:
            raise ValueError("reviewer_reference is required for the decision audit")
        decision={'ACCEPT':'APPROVE'}.get(decision.upper(),decision.upper())
        body: dict[str, Any] = {"decision": decision,
                                "reviewer_type": "CREATOR_AUTHORIZED_HUMAN",
                                "reviewer_reference": reviewer_reference}
        if reason:
            body["reason"] = reason
        if rule_decisions:
            body["rule_decisions"] = rule_decisions
        submission = self.read_delivery(assignment_id)
        if submission.get('acceptance_policy'):
            if not submission.get('can_approve'):
                raise AixError(409, {'code':'REVIEW_NOT_ALLOWED',
                                    'message':'Published policy does not permit this review.'})
            body['contract_hash'] = submission['contract_hash']
            body['delivery_hash'] = submission['results'][-1]['delivery']['delivery_hash']
            body['reviewer_type'] = 'CREATOR_AUTHORIZED'
        return self._call("POST", f"/v1/assignments/{assignment_id}/human-review",
                          body, idempotency_key=_new_idempotency_key())

    def heartbeat(self, assignment_id: str) -> Any:
        return self._call("POST", f"/v1/assignments/{assignment_id}/heartbeat", {})

    # ------------------------------------------------ credential lifecycle
    # Reconciled read-only against frozen v0.8: both routes exist. An earlier
    # version of this Skill claimed they did not, which was wrong and would have
    # told a compromised Agent the key could never be invalidated.
    def rotate_credential(self) -> dict[str, Any]:
        """Issue a new credential. The old one stops working."""
        status, result = self._mutate("rotate_credential", "POST",
                                     "/v1/agents/me/rotate-credential", {})
        if isinstance(result, AixError):
            raise result
        new_key = (result.get("api_key") or result.get("new_api_key")) if isinstance(result, dict) else None
        if new_key:
            self._api_key = new_key
            self.store_credential()
        result = dict(result) if isinstance(result, dict) else {}
        result["reloaded_and_verified"] = bool(new_key)
        return redact(result)

    def revoke_credential(self) -> dict[str, Any]:
        """Invalidate the current credential on the network.

        After this the identity is unusable until a new credential is issued, so
        local state is cleared to avoid storing a key that cannot authenticate.
        """
        status, result = self._mutate("revoke_credential", "POST",
                                     "/v1/agents/me/revoke-credential", {})
        if isinstance(result, AixError):
            raise result
        try:
            for aid in list(self.store.agent_ids()):
                self.store.forget(aid)
        except Exception:  # noqa: BLE001
            pass
        self.agent_id = None
        self._api_key = None
        return {"revoked": True, "local_state_cleared": True,
                "result": redact(result) if isinstance(result, dict) else result}


def operations(spec: dict) -> set[str]:
    return {f"{m.upper()} {p}" for p, item in spec.get("paths", {}).items()
            for m in item if m in ("get", "post", "put", "patch", "delete")}


def contract_summary(contract: dict) -> dict[str, Any]:
    """A creator-readable view of the frozen contract.

    Never exposes a committed verifier's expected value: the public contract
    carries only the commitment, and this must not become a way to recover the
    answer from a summary.
    """
    rules = []
    for rule in contract.get("rules", []):
        check = rule.get("check") or {}
        committed = check.get("kind") == "json_path_equals_committed"
        # Every public parameter of the check (min, value, in, type, equals,
        # sha256 ...) -- a worker cannot satisfy a rule it cannot read. A
        # committed check's expected value and salt are never public.
        params = {k: v for k, v in check.items()
                  if k not in ("kind", "path", "expected", "salt")}
        rules.append({
            "id": rule.get("id"),
            "requirement": rule.get("requirement"),
            "required": rule.get("required", True),
            "verification_mode": rule.get("verification_mode", "MACHINE"),
            "check_kind": check.get("kind"),
            "path": check.get("path"),
            "params": params,
            "committed": committed,
        })
    return {"contract_id": contract.get("acceptance_contract_id"),
            "contract_hash": contract.get("contract_hash"),
            "dispute_policy": contract.get("dispute_policy"),
            "result_shape": contract.get("result_shape")
                            or local_result_shape(contract.get("rules", [])),
            "rules": rules,
            **({'acceptance_policy':contract['acceptance_policy']} if contract.get('acceptance_policy') else {})}


def local_result_shape(rules: list[dict]) -> str:
    """Mirror of the node's ``result_shape``: "text", "json", "any" or "conflict".

    A required text_* rule with no ``path`` judges the WHOLE result as one
    string; a json_* rule (or text_* with a path) reads a field of a JSON
    result. Both at once can never pass.
    """
    text = structured = False
    for rule in rules or []:
        if not isinstance(rule, dict) or rule.get("required", True) is False:
            continue
        check = rule.get("check") or {}
        kind = str(check.get("kind") or "")
        if kind.startswith("text_") and not check.get("path"):
            text = True
        elif kind.startswith("json_") or (kind.startswith("text_") and check.get("path")):
            structured = True
    if text and structured:
        return "conflict"
    return "text" if text else "json" if structured else "any"


def contract_check(contract: dict) -> dict[str, Any]:
    """Pre-claim check of a published contract: can a delivery satisfy it?

    Local and read-only. It reports problems; it never claims, submits or pays.
    """
    rules = contract.get("rules", []) or []
    shape = contract.get("result_shape") or local_result_shape(rules)
    problems: list[str] = []
    if shape == "conflict":
        problems.append("required whole-text rules and JSON rules conflict; no "
                        "delivery can pass this contract -- do not claim it")
    for rule in rules:
        check = (rule or {}).get("check") or {}
        kind = check.get("kind")
        if kind in UNSUPPORTED_RULE_KINDS and rule.get("required", True):
            problems.append(f"rule {rule.get('id')}: {kind} can never pass on this "
                            "protocol version")
    guidance = {
        "text": "submit the result as ONE plain string (structured_output = \"...\")",
        "json": "submit a JSON object in structured_output with the listed paths",
        "any": "no machine shape constraint",
        "conflict": "unsatisfiable",
    }[shape]
    return {"result_shape": shape, "satisfiable": not problems,
            "problems": problems, "delivery_guidance": guidance}
