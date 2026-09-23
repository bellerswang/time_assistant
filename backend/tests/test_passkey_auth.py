"""Security boundaries around passkey enrollment and persistent sessions."""

import json
import sys
import unittest
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException, Request
from fastapi import FastAPI
from fastapi.responses import JSONResponse
import httpx
from webauthn import base64url_to_bytes

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import passkey_auth as auth_module  # noqa: E402


class MemorySnapshot:
    def __init__(self, id_, data):
        self.id = id_
        self._data = data
        self.exists = data is not None
        self.update_time = object()

    def to_dict(self):
        return self._data


class MemoryDoc:
    def __init__(self, records, id_):
        self.records = records
        self.id = id_

    def get(self):
        return MemorySnapshot(self.id, self.records.get(self.id))

    def create(self, data):
        if self.id in self.records:
            raise ValueError("already exists")
        self.records[self.id] = dict(data)

    def set(self, data):
        self.records[self.id] = dict(data)

    def update(self, data):
        self.records[self.id].update(data)

    def delete(self, option=None):
        self.records.pop(self.id, None)


class MemoryCollection:
    def __init__(self, records):
        self.records = records

    def document(self, id_):
        return MemoryDoc(self.records, id_)

    def stream(self):
        return [MemorySnapshot(id_, data) for id_, data in self.records.items()]


class MemoryDb:
    def __init__(self):
        self.records = {}

    def collection(self, name):
        return MemoryCollection(self.records.setdefault(name, {}))


class FirebaseStub:
    def verify_id_token(self, token, check_revoked=False):
        if check_revoked:
            raise PermissionError("Revocation lookup is not available cross-project")
        if token != "owner":
            raise ValueError("bad token")
        return {"uid": "owner-uid"}


def request(path="/", method="POST", origin="https://loomi.example", token="", cookie=""):
    headers = [(b"origin", origin.encode())]
    if token:
        headers.append((b"authorization", f"Bearer {token}".encode()))
    if cookie:
        headers.append((b"cookie", cookie.encode()))
    return Request({"type": "http", "method": method, "path": path, "headers": headers})


def credential_for(challenge, credential_id="credential-id"):
    client = json.dumps({"challenge": challenge}).encode()
    return {
        "id": credential_id,
        "response": {"clientDataJSON": auth_module._b64(client)},
    }


class PasskeyBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.db = MemoryDb()
        self.auth = auth_module.PasskeyAuth(
            db=self.db, firebase_auth=FirebaseStub(), uid="owner-uid",
            origin="https://loomi.example", setup_google_enabled=True,
        )

    def test_only_existing_owner_can_enroll_and_origin_must_match(self):
        with self.assertRaises(HTTPException) as error:
            self.auth.register_options(request())
        self.assertEqual(error.exception.status_code, 401)
        with self.assertRaises(HTTPException) as error:
            self.auth.register_options(request(token="wrong"))
        self.assertEqual(error.exception.status_code, 401)
        with self.assertRaises(HTTPException) as error:
            self.auth.register_options(request(token="owner", origin="https://evil.example"))
        self.assertEqual(error.exception.status_code, 403)
        options = json.loads(self.auth.register_options(request(token="owner")).body)
        self.assertEqual(options["rp"]["id"], "loomi.example")
        self.assertEqual(options["authenticatorSelection"]["userVerification"], "required")

    def test_challenge_is_single_use_and_bound_to_purpose(self):
        challenge = auth_module._b64(self.auth._make_challenge("register"))
        credential = credential_for(challenge)
        with self.assertRaises(HTTPException):
            self.auth._consume_challenge(credential, "login")
        self.auth._consume_challenge(credential, "register")
        with self.assertRaises(HTTPException):
            self.auth._consume_challenge(credential, "register")

    def test_verified_passkey_grants_revocable_session_only(self):
        owner = request(token="owner")
        registration = json.loads(self.auth.register_options(owner).body)
        credential_id = auth_module._b64(b"credential-id")
        register_credential = credential_for(registration["challenge"], credential_id)
        registered = SimpleNamespace(
            credential_id=b"credential-id", credential_public_key=b"public-key", sign_count=0,
        )
        with patch.object(auth_module, "verify_registration_response", return_value=registered) as verify:
            self.auth.register_complete(owner, auth_module.CredentialPayload(credential=register_credential))
        self.assertEqual(verify.call_args.kwargs["expected_origin"], "https://loomi.example")
        self.assertEqual(verify.call_args.kwargs["expected_rp_id"], "loomi.example")
        self.assertTrue(verify.call_args.kwargs["require_user_verification"])

        login_options = json.loads(self.auth.login_options(request()).body)
        login_credential = credential_for(login_options["challenge"], credential_id)
        with patch.object(auth_module, "verify_authentication_response", return_value=SimpleNamespace(new_sign_count=1)) as verify:
            response = self.auth.login_complete(
                request(), auth_module.CredentialPayload(credential=login_credential),
            )
        self.assertTrue(verify.call_args.kwargs["require_user_verification"])
        self.assertEqual(verify.call_args.kwargs["credential_public_key"], b"public-key")
        cookie = response.headers["set-cookie"].split(";", 1)[0]
        self.assertIn("httponly", response.headers["set-cookie"].lower())
        self.assertIn("secure", response.headers["set-cookie"].lower())
        signed_in = request(cookie=cookie)
        self.assertEqual(self.auth.session_uid(signed_in), "owner-uid")
        with self.assertRaises(HTTPException):
            self.auth.check_origin(request(cookie=cookie, origin="https://evil.example"))
        self.auth.logout(signed_in)
        self.assertIsNone(self.auth.session_uid(signed_in))

    def test_bad_assertion_never_creates_session(self):
        credential_id = auth_module._b64(b"credential-id")
        self.db.collection("loomi_passkeys").document(credential_id).set({
            "uid": "owner-uid", "public_key": auth_module._b64(b"key"), "sign_count": 0,
        })
        challenge = json.loads(self.auth.login_options(request()).body)["challenge"]
        with self.assertRaises(HTTPException) as error:
            self.auth.login_complete(
                request(), auth_module.CredentialPayload(credential=credential_for(challenge, credential_id)),
            )
        self.assertEqual(error.exception.status_code, 401)
        self.assertFalse(self.db.records.get("loomi_auth_sessions"))

    def test_remembered_session_renews_on_app_open(self):
        response = self.auth.issue_session(JSONResponse({"ok": True}))
        cookie = response.headers["set-cookie"].split(";", 1)[0]
        session_id = next(iter(self.db.records["loomi_auth_sessions"]))
        self.db.records["loomi_auth_sessions"][session_id]["expires_at"] = auth_module._now() + timedelta(days=20)
        with patch.object(auth_module, "PUBLIC_DIR", Path(__file__).resolve().parents[2]):
            app_response = self.auth.app_page(request(path="/", method="GET", cookie=cookie))
        self.assertEqual(app_response.status_code, 200)
        self.assertIn(b'<html lang="zh-CN" class="private-host">', app_response.body)
        self.assertIn(b'auth-gate-private', app_response.body)
        self.assertIn(b"LOOMI_PRIVATE_HOST = true", app_response.body)
        self.assertNotIn(b"accounts.google.com/gsi/client", app_response.body)
        self.assertNotIn(b"firebase-app-compat.js", app_response.body)
        self.assertIn(auth_module.COOKIE_NAME, app_response.headers["set-cookie"])
        self.assertGreater(
            self.db.records["loomi_auth_sessions"][session_id]["expires_at"],
            auth_module._now() + timedelta(days=89),
        )

    def test_adding_passkey_requires_recent_device_verification(self):
        self.auth.setup_google_enabled = False
        response = self.auth.issue_session(JSONResponse({"ok": True}))
        cookie = response.headers["set-cookie"].split(";", 1)[0]
        signed_in = request(path="/auth/add-passkey", method="GET", cookie=cookie)
        session_id = next(iter(self.db.records["loomi_auth_sessions"]))
        self.db.records["loomi_auth_sessions"][session_id]["created_at"] -= timedelta(days=1)
        self.assertEqual(self.auth.add_page(signed_in).headers["location"], "/auth/reauth")
        with self.assertRaises(HTTPException) as error:
            self.auth.register_options(request(cookie=cookie))
        self.assertEqual(error.exception.status_code, 403)


class PrivatePageTests(unittest.IsolatedAsyncioTestCase):
    async def test_public_login_cannot_fetch_app_or_assets(self):
        app = FastAPI()
        auth = auth_module.PasskeyAuth(
            db=MemoryDb(), firebase_auth=FirebaseStub(), uid="owner-uid",
            origin="https://loomi.example", setup_google_enabled=True,
        )
        auth_module.mount_passkey_routes(app, auth)
        with patch.object(auth_module, "PUBLIC_DIR", Path(__file__).resolve().parents[2]):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="https://loomi.example",
                follow_redirects=False,
            ) as client:
                root = await client.get("/")
                self.assertEqual(root.status_code, 303)
                self.assertEqual(root.headers["location"], "/auth/login")
                self.assertEqual((await client.get("/index.html")).status_code, 303)
                self.assertEqual((await client.get("/loomi_icon.png")).status_code, 401)
                self.assertEqual((await client.post("/auth/login/options", headers={"Origin": "https://evil.example"})).status_code, 403)
                self.assertEqual((await client.get("/auth/login")).status_code, 200)
                self.assertEqual((await client.get("/auth/setup")).status_code, 200)


if __name__ == "__main__":
    unittest.main()
