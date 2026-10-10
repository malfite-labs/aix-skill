"""Credential storage for the AIX Skill.

A registration returns an API credential **once**. After that moment the only
copy is wherever the Agent keeps it, so where it lives is a security decision,
not a convenience one.

Three tiers, in descending order of preference:

1. **OS keyring** -- the credential goes to the platform credential store
   (Keychain, Credential Manager, Secret Service). Nothing touches disk in a form
   this process can read back.
2. **Isolated file store** -- when no keyring exists, a single file outside the
   repository, created with owner-only permissions where the platform allows it.
   This is a documented downgrade, not an equivalent.
3. **In-memory only** -- the credential is used for the session and never
   persisted. Annoying but honest: a Skill that cannot store a secret safely
   should say so rather than write it somewhere convenient.

What this module will never do: return a credential for display, place one in a
log line, an exception message, a Delivery, Evidence, or a task spec. The
redaction helpers exist because the alternative is one careless f-string.
"""
from __future__ import annotations

import json
import os
import pathlib
import stat
import tempfile
import uuid
import copy
from typing import Any

SERVICE = "aix-skill"
REDACTED = "***redacted***"

#: Substrings that mean a value is a credential and must never be rendered.
_SECRET_MARKERS = ("api_key", "apikey", "authorization", "bearer", "credential",
                   "secret", "password", "private_key")


def is_secret_field(name: str) -> bool:
    lowered = name.lower()
    return any(marker in lowered for marker in _SECRET_MARKERS)


def redact(value: Any, _depth: int = 0) -> Any:
    """Return a copy with every credential-looking value replaced.

    Applied to anything about to be printed, logged or shipped in a Delivery.
    """
    if _depth > 12:
        return value
    if isinstance(value, dict):
        return {k: (REDACTED if is_secret_field(str(k)) else redact(v, _depth + 1))
                for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v, _depth + 1) for v in value]
    if isinstance(value, str) and value.lower().startswith("bearer "):
        return f"Bearer {REDACTED}"
    return value


def summarize(agent: dict) -> dict:
    """A safe identity view. Deliberately omits the credential entirely."""
    out = {k: v for k, v in agent.items() if not is_secret_field(str(k))}
    if "api_key" in agent:
        out["api_key"] = REDACTED
    return out


def probe_store(store: "CredentialStore") -> tuple[bool, str]:
    """Prove the store actually works before an identity depends on it.

    Importing `keyring` is not evidence: the package can be present with no
    usable backend behind it -- no D-Bus on Linux, no Keychain on a headless
    box, a locked keychain, a Windows session without a profile. A credential
    written to such a store is lost silently, and because registration returns
    the credential exactly once, that loss is permanent: the Agent has an
    identity it can never authenticate as.

    So this does a real round trip -- write, read back, delete -- and returns
    False if any step fails. The caller must not register until this passes.
    """
    marker = "_aix_probe_" + uuid.uuid4().hex
    value = "non-production-probe-" + uuid.uuid4().hex
    original_path = store._path
    original_profile = store.profile
    created = []
    temporary = None
    started = False
    cleanup_failed = False
    def roundtrip():
        nonlocal temporary, started
        # Validate real destinations without writing them. A temporary round
        # trip cannot prove that a directory occupying the final path is usable.
        store._local_hints()
        if store.backend == "isolated_file":
            store._read_file()
            parent = store._path.parent
            if parent.exists() and hasattr(os, "geteuid") and parent.stat().st_uid != os.geteuid():
                return False, "isolated_file: parent is not owned by this runtime"
            while not parent.exists():
                created.append(parent)
                parent = parent.parent
            store._path.parent.mkdir(parents=True, exist_ok=True)
            temporary = tempfile.TemporaryDirectory(prefix=".aix-probe-", dir=store._path.parent)
            store._path = pathlib.Path(temporary.name) / "probe.json"
        elif store.backend == "os_keyring":
            anchor = store.file_store()
            anchor._path = store._local_hint_path().with_name(".aix-anchor-capability.json")
            ok, _ = probe_store(anchor)
            if not ok:
                return False, "os_keyring: local identity metadata unavailable"
        store.profile = original_profile + ":" + marker
        started = True
        store.save(marker, value)
        got = store.load(marker)
        store.forget(marker)
        if store.load(marker) is not None:
            return False, f"{store.backend}: delete did not take effect"
        if got != value:
            return False, f"{store.backend}: read-back mismatch"
        return True, store.backend
    try:
        result = roundtrip()
    except Exception as exc:  # noqa: BLE001 - any failure means unusable
        result = False, f"{store.backend}: {type(exc).__name__}"
    finally:
        # Retry cleanup even after write/read failure; never touch real identities.
        try:
            if started:
                store.forget(marker)
        except Exception:
            pass
        store._path = original_path
        store.profile = original_profile
        if temporary:
            try:
                temporary.cleanup()
            except OSError:
                cleanup_failed = True
        for path in created:
            try:
                path.rmdir()
            except OSError:
                cleanup_failed = True
    if cleanup_failed:
        return False, f"{store.backend}: probe cleanup failed"
    return result


class CredentialStore:
    """Capability-selected storage; durability is unknown unless established."""

    def __init__(self, profile: str = "default") -> None:
        self.profile = profile
        self._backend = "memory"
        self._memory: dict[str, str] = {}
        self._keyring = None
        self._path: pathlib.Path | None = None
        self._load_backend()

    # -- backend selection ---------------------------------------------------
    def _load_backend(self) -> None:
        self._path = self._default_path()
        self.probe_result = "NOT_RUN"
        keyring_identity = False
        try:
            import keyring  # type: ignore
            self._keyring = keyring
            self._backend = "os_keyring"
            # Legacy builds kept their index only in keyring. A readable index
            # (including corrupt evidence) must survive a failed write probe.
            try:
                keyring_identity = self._keyring.get_password(self._account(), "__aix_identity_index__") is not None
            except Exception:
                pass
            ok, self.probe_result = probe_store(self)
            # Preserve a keyring identity during an outage, even when its secret
            # and backend index cannot currently be read.
            if ok or keyring_identity or self._local_hint_path().exists():
                return
        except Exception:
            pass
        self._backend = "os_keyring"
        if keyring_identity or self._local_hint_path().exists():
            return
        self._backend = "isolated_file"

    def _default_path(self) -> pathlib.Path:
        env = os.environ.get("AIX_SKILL_CREDENTIAL_FILE")
        if env:
            return pathlib.Path(env).expanduser()
        else:
            base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
            return pathlib.Path(base) / "aix-skill" / "credentials.json"

    @property
    def durability(self) -> str:
        # A runtime may attest persistence; the store never infers it from an
        # import, path, operating system or successful read-back.
        status = os.environ.get("AIX_SKILL_STORAGE_DURABILITY", "UNKNOWN")
        return status if status in ("DURABLE", "EPHEMERAL", "UNKNOWN") else "UNKNOWN"

    def _local_hint_path(self) -> pathlib.Path:
        path = self._path or self._default_path()
        suffix = ".keyring.identity.json" if self.backend == "os_keyring" else ".identity.json"
        return path.with_name(path.name + suffix)

    def file_store(self) -> "CredentialStore":
        """A store guaranteed to use the isolated-file backend.

        Used as the prevalidated fallback so that a keyring failure discovered
        after registration has somewhere already-proven to write.
        """
        env = os.environ.get("AIX_SKILL_CREDENTIAL_FILE")
        if env:
            path = pathlib.Path(env).expanduser()
        else:
            base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
            path = pathlib.Path(base) / "aix-skill" / f"{self.profile}.fallback.json"
        clone = CredentialStore.__new__(CredentialStore)
        clone.profile = self.profile
        clone._backend = "isolated_file"
        clone._memory = {}
        clone._keyring = None
        clone._path = path
        clone.probe_result = "NOT_RUN"
        return clone

    def file_candidates(self) -> list["CredentialStore"]:
        fallback = self.file_store()
        legacy = copy.copy(fallback)
        legacy._path = self._default_path()
        return [fallback] if fallback._path == legacy._path else [legacy, fallback]

    @property
    def backend(self) -> str:
        return self._backend

    @property
    def isolated_file(self) -> pathlib.Path | None:
        return self._path

    # -- operations ----------------------------------------------------------
    def _account(self) -> str:
        return f"{SERVICE}:{self.profile}"

    def save(self, agent_id: str, api_key: str) -> None:
        if self._backend == "os_keyring":
            self._remember_identity(agent_id)
            self._keyring.set_password(self._account(), agent_id, api_key)
            return
        if self._backend == "isolated_file":
            data = self._read_file()
            data[agent_id] = api_key
            self._remember_identity(agent_id)
            self._atomic_json(self._path, data)
            return
        self._memory[agent_id] = api_key

    def load(self, agent_id: str) -> str | None:
        if self._backend == "os_keyring":
            return self._keyring.get_password(self._account(), agent_id)
        if self._backend == "isolated_file":
            return self._read_file().get(agent_id)
        return self._memory.get(agent_id)

    def agent_ids(self) -> list[str]:
        """Known identities, including hints whose credential is now missing.

        A hint is not authentication. It only prevents lost storage from being
        mistaken for permission to register a replacement identity.
        """
        hints = self._identity_hints()
        if self._backend == "os_keyring":
            return hints
        if self._backend == "isolated_file":
            return sorted(set(self._read_file()) | set(hints))
        return sorted(self._memory)

    def _identity_hints(self) -> list[str]:
        try:
            if self._backend == "os_keyring":
                local = self._local_hints()
                try:
                    raw = self._keyring.get_password(self._account(), "__aix_identity_index__")
                except Exception:
                    return local
            elif self._backend == "isolated_file":
                path = self._path.with_name(self._path.name + ".identity.json")
                raw = path.read_text(encoding="utf-8") if path.exists() else None
            else:
                return []
            value = json.loads(raw) if raw is not None else []
            if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
                raise ValueError("invalid identity hints")
            return sorted(set(value) | set(local if self.backend == "os_keyring" else []))
        except Exception:
            return []

    def identity_hint_unavailable(self) -> bool:
        """Fail closed for unreadable existing local identity metadata."""
        return self.identity_state() in ("BACKEND_UNAVAILABLE", "IDENTITY_STATE_CORRUPT")

    def _local_hints(self) -> list[str]:
        path = self._local_hint_path()
        value = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
        if not isinstance(value, list) or not all(isinstance(x, str) and x for x in value):
            raise ValueError("invalid identity metadata")
        return value

    def identity_state(self) -> str:
        try:
            local = self._local_hints()
        except (OSError, ValueError):
            return "IDENTITY_STATE_CORRUPT"
        if self._backend == "os_keyring":
            try:
                raw = self._keyring.get_password(self._account(), "__aix_identity_index__")
                data = json.loads(raw) if raw is not None else []
                if not isinstance(data, list) or not all(isinstance(x, str) and x for x in data):
                    return "IDENTITY_STATE_CORRUPT"
                return "IDENTITY_PRESENT" if data or local else "NO_IDENTITY"
            except ValueError:
                return "IDENTITY_STATE_CORRUPT"
            except Exception:
                return "BACKEND_UNAVAILABLE"
        if self._backend != "isolated_file":
            return "IDENTITY_PRESENT" if self._memory else "NO_IDENTITY"
        hint = self._path.with_name(self._path.name + ".identity.json")
        if hint.exists():
            try:
                data = json.loads(hint.read_text(encoding="utf-8"))
                if not isinstance(data, list) or not all(isinstance(x, str) for x in data):
                    return "IDENTITY_STATE_CORRUPT"
            except (OSError, ValueError):
                return "IDENTITY_STATE_CORRUPT"
        if self._path.exists():
            try:
                raw = self._path.read_text(encoding="utf-8")
                self._read_file()
            except (OSError, ValueError):
                return "IDENTITY_STATE_CORRUPT"
        return "IDENTITY_PRESENT" if local or self._read_file() else "NO_IDENTITY"

    def _write_identity_hints(self, ids: list[str]) -> None:
        raw = json.dumps(sorted(set(ids)))
        if self._backend == "os_keyring":
            self._atomic_json(self._local_hint_path(), sorted(set(ids)))
            self._keyring.set_password(self._account(), "__aix_identity_index__", raw)
        elif self._backend == "isolated_file":
            # Same runtime-selected directory; contains agent ids, never keys.
            path = self._path.with_name(self._path.name + ".identity.json")
            self._atomic_json(path, sorted(set(ids)))

    def _remember_identity(self, agent_id: str) -> None:
        if not agent_id.startswith("_aix_probe_") and agent_id != "_aix_preflight_probe":
            if self.identity_state() == "IDENTITY_STATE_CORRUPT":
                raise ValueError("identity metadata corrupt")
            self._write_identity_hints(self._identity_hints() + [agent_id])

    def forget(self, agent_id: str) -> None:
        if self._backend == "os_keyring":
            self._keyring.delete_password(self._account(), agent_id)
        elif self._backend == "isolated_file":
            data = self._read_file()
            data.pop(agent_id, None)
            self._atomic_json(self._path, data)
        else:
            self._memory.pop(agent_id, None)
        hints = self._identity_hints()
        if agent_id in hints:
            self._write_identity_hints([x for x in hints if x != agent_id])

    def prepare_file_path(self) -> None:
        """Create the parent, tighten permissions, prove writability.

        Called before registration so the fallback is known-good in advance.
        """
        if not self._path:
            raise RuntimeError("no credential file path configured")
        self._path.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self._path.parent, stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
        except OSError:
            pass
        ok, _ = probe_store(self)
        if not ok:
            raise OSError("isolated storage probe failed")

    @staticmethod
    def _atomic_json(path: pathlib.Path, data: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        if hasattr(os, "geteuid") and path.parent.stat().st_uid != os.geteuid():
            raise PermissionError("storage directory is not owned by this runtime")
        os.chmod(path.parent, 0o700)
        fd, name = tempfile.mkstemp(prefix=".aix-write-", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                os.chmod(name, 0o600)
                json.dump(data, fh)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(name, path)
        finally:
            if os.path.exists(name):
                os.unlink(name)

    def _read_file(self) -> dict[str, str]:
        if not self._path or not self._path.exists():
            return {}
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or not all(isinstance(k, str) and k and isinstance(v, str) and v for k, v in data.items()):
                raise ValueError("invalid credential file")
            return data
        except (OSError, ValueError):
            raise ValueError("credential storage unreadable or corrupt") from None
