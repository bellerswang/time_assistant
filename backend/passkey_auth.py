"""Single-owner WebAuthn access to Loomi's private Cloud Run frontend."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from google.api_core.exceptions import AlreadyExists
from google.cloud.firestore_v1 import LastUpdateOption
from pydantic import BaseModel
from webauthn import (
    base64url_to_bytes,
    generate_authentication_options,
    generate_registration_options,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers import options_to_json
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)


CHALLENGE_LIFETIME = timedelta(minutes=5)
SESSION_LIFETIME = timedelta(days=90)
COOKIE_NAME = "__Host-loomi-session"
PUBLIC_DIR = Path(__file__).resolve().parent / "public"
if not PUBLIC_DIR.is_dir():
    PUBLIC_DIR = Path(__file__).resolve().parent.parent
ASSETS = {"firebase-config.js", "manifest.json", "sw.js", "loomi_icon.png"}


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("ascii")).hexdigest()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _no_store(response):
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


class CredentialPayload(BaseModel):
    credential: dict


class PasskeyAuth:
    def __init__(self, *, db, firebase_auth, uid: str, origin: str, setup_google_enabled: bool):
        parsed = urlsplit(origin)
        if not db or not uid or not parsed.hostname or parsed.scheme not in {"https", "http"} or parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
            raise ValueError("Passkey auth needs Firestore, ALLOWED_FIREBASE_UID, and LOOMI_PUBLIC_ORIGIN")
        if parsed.scheme == "http" and parsed.hostname not in {"localhost", "127.0.0.1"}:
            raise ValueError("Passkey origin must use HTTPS")
        self.db = db
        self.firebase_auth = firebase_auth
        self.uid = uid
        self.origin = origin.rstrip("/")
        self.rp_id = parsed.hostname
        self.setup_google_enabled = setup_google_enabled
        self.credentials = db.collection("loomi_passkeys")
        self.challenges = db.collection("loomi_auth_challenges")
        self.sessions = db.collection("loomi_auth_sessions")

    def check_origin(self, request: Request):
        # All state-changing browser calls are same-origin. This also protects
        # the HttpOnly session cookie from cross-site request forgery.
        if request.headers.get("origin") != self.origin:
            raise HTTPException(403, "Invalid origin")

    def _session_ref(self, request: Request):
        token = request.cookies.get(COOKIE_NAME, "")
        if len(token) != 43 or any(c not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_" for c in token):
            return None
        return self.sessions.document(_digest(token))

    def session_uid(self, request: Request) -> str | None:
        data = self._session_data(request)
        return data.get("uid") if data else None

    def _session_data(self, request: Request) -> dict | None:
        ref = self._session_ref(request)
        if ref is None:
            return None
        snap = ref.get()
        if not snap.exists:
            return None
        data = snap.to_dict()
        if data.get("uid") != self.uid or data.get("expires_at", _now()) <= _now():
            return None
        return data

    def require_session(self, request: Request):
        if self.session_uid(request) != self.uid:
            raise HTTPException(401, "Passkey session required")

    def issue_session(self, response):
        token = _b64(secrets.token_bytes(32))
        self.sessions.document(_digest(token)).set({
            "uid": self.uid,
            "created_at": _now(),
            "expires_at": _now() + SESSION_LIFETIME,
        })
        response.set_cookie(
            COOKIE_NAME, token, max_age=int(SESSION_LIFETIME.total_seconds()),
            secure=True, httponly=True, samesite="lax", path="/",
        )
        return response

    def renew_session(self, request: Request, response):
        ref = self._session_ref(request)
        if ref is None:
            return response
        snap = ref.get()
        if not snap.exists or snap.to_dict().get("uid") != self.uid:
            return response
        if snap.to_dict().get("expires_at", _now()) - _now() < timedelta(days=30):
            ref.update({"expires_at": _now() + SESSION_LIFETIME})
            response.set_cookie(
                COOKIE_NAME, request.cookies[COOKIE_NAME],
                max_age=int(SESSION_LIFETIME.total_seconds()),
                secure=True, httponly=True, samesite="lax", path="/",
            )
        return response

    def _make_challenge(self, purpose: str) -> bytes:
        challenge = secrets.token_bytes(32)
        self.challenges.document(_digest(_b64(challenge))).create({
            "purpose": purpose,
            "uid": self.uid,
            "expires_at": _now() + CHALLENGE_LIFETIME,
        })
        return challenge

    def _consume_challenge(self, credential: dict, purpose: str) -> bytes:
        try:
            raw = base64url_to_bytes(credential["response"]["clientDataJSON"])
            challenge_text = json.loads(raw)["challenge"]
            challenge = base64url_to_bytes(challenge_text)
            if len(challenge) != 32:
                raise ValueError("Invalid challenge length")
            ref = self.challenges.document(_digest(_b64(challenge)))
            snap = ref.get()
            if not snap.exists:
                raise ValueError("Challenge not found")
            data = snap.to_dict()
            if data.get("purpose") != purpose or data.get("uid") != self.uid or data.get("expires_at", _now()) <= _now():
                raise ValueError("Challenge expired")
            # The update-time precondition makes the challenge single-use even
            # when two Cloud Run instances receive the same response together.
            ref.delete(option=LastUpdateOption(snap.update_time))
            return challenge
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            raise HTTPException(400, "Invalid or expired passkey challenge") from None
        except Exception:
            raise HTTPException(400, "Passkey challenge was already used") from None

    def _registration_allowed(self, request: Request):
        session = self._session_data(request)
        if session and session.get("created_at", _now() - SESSION_LIFETIME) >= _now() - CHALLENGE_LIFETIME:
            return
        if not self.setup_google_enabled:
            raise HTTPException(403, "Google setup is disabled")
        header = request.headers.get("authorization", "")
        if not header.lower().startswith("bearer "):
            raise HTTPException(401, "Existing owner sign-in required")
        try:
            decoded = self.firebase_auth.verify_id_token(header[7:].strip(), check_revoked=True)
        except Exception:
            raise HTTPException(401, "Existing owner sign-in required") from None
        if decoded.get("uid") != self.uid:
            raise HTTPException(403, "Account is not authorized")

    def register_options(self, request: Request):
        self.check_origin(request)
        self._registration_allowed(request)
        existing = [
            PublicKeyCredentialDescriptor(id=base64url_to_bytes(snap.id))
            for snap in self.credentials.stream() if snap.to_dict().get("uid") == self.uid
        ]
        options = generate_registration_options(
            rp_id=self.rp_id, rp_name="Loomi", user_id=self.uid.encode("utf-8"),
            user_name="Loomi owner", challenge=self._make_challenge("register"),
            exclude_credentials=existing,
            authenticator_selection=AuthenticatorSelectionCriteria(
                resident_key=ResidentKeyRequirement.REQUIRED,
                user_verification=UserVerificationRequirement.REQUIRED,
            ),
        )
        return _no_store(JSONResponse(json.loads(options_to_json(options))))

    def register_complete(self, request: Request, payload: CredentialPayload):
        self.check_origin(request)
        self._registration_allowed(request)
        challenge = self._consume_challenge(payload.credential, "register")
        try:
            verified = verify_registration_response(
                credential=payload.credential, expected_challenge=challenge,
                expected_rp_id=self.rp_id, expected_origin=self.origin,
                require_user_verification=True,
            )
        except Exception:
            raise HTTPException(400, "Passkey registration failed") from None
        credential_id = _b64(verified.credential_id)
        try:
            self.credentials.document(credential_id).create({
                "uid": self.uid,
                "public_key": _b64(verified.credential_public_key),
                "sign_count": verified.sign_count,
                "created_at": _now(),
            })
        except AlreadyExists:
            raise HTTPException(409, "This passkey is already registered") from None
        return _no_store(JSONResponse({"registered": True}))

    def login_options(self, request: Request):
        self.check_origin(request)
        if not any(snap.to_dict().get("uid") == self.uid for snap in self.credentials.stream()):
            raise HTTPException(503, "Register a passkey first")
        options = generate_authentication_options(
            rp_id=self.rp_id, challenge=self._make_challenge("login"),
            user_verification=UserVerificationRequirement.REQUIRED,
        )
        return _no_store(JSONResponse(json.loads(options_to_json(options))))

    def login_complete(self, request: Request, payload: CredentialPayload):
        self.check_origin(request)
        challenge = self._consume_challenge(payload.credential, "login")
        try:
            credential_id = payload.credential["id"]
            snap = self.credentials.document(credential_id).get()
            if not snap.exists or snap.to_dict().get("uid") != self.uid:
                raise ValueError("Unknown credential")
            saved = snap.to_dict()
            verified = verify_authentication_response(
                credential=payload.credential, expected_challenge=challenge,
                expected_rp_id=self.rp_id, expected_origin=self.origin,
                credential_public_key=base64url_to_bytes(saved["public_key"]),
                credential_current_sign_count=saved["sign_count"],
                require_user_verification=True,
            )
        except Exception:
            raise HTTPException(401, "Passkey was not verified") from None
        self.credentials.document(credential_id).update({"sign_count": verified.new_sign_count})
        old_session = self._session_ref(request)
        if old_session:
            old_session.delete()
        return _no_store(self.issue_session(JSONResponse({"signed_in": True})))

    def logout(self, request: Request):
        self.check_origin(request)
        ref = self._session_ref(request)
        if ref:
            ref.delete()
        response = _no_store(JSONResponse({"signed_out": True}))
        response.delete_cookie(COOKIE_NAME, path="/")
        return response

    def app_page(self, request: Request):
        if self.session_uid(request) != self.uid:
            return _no_store(RedirectResponse("/auth/login", status_code=303))
        html = (PUBLIC_DIR / "index.html").read_text(encoding="utf-8")
        html = html.replace('<script src="https://accounts.google.com/gsi/client" async defer></script>', '')
        html = html.replace('<script src="https://www.gstatic.com/firebasejs/11.10.0/firebase-app-compat.js" defer></script>', '')
        html = html.replace('<script src="https://www.gstatic.com/firebasejs/11.10.0/firebase-auth-compat.js" defer></script>', '')
        html = html.replace('<script src="./firebase-config.js?v=20260725.2"></script>', '')
        html = html.replace("<!-- LOOMI_PRIVATE_BOOTSTRAP -->", "<script>window.LOOMI_PRIVATE_HOST = true;</script>")
        return _no_store(self.renew_session(request, HTMLResponse(html)))

    def asset(self, request: Request, name: str):
        if name != "firebase-config.js":
            self.require_session(request)
        if name not in ASSETS:
            raise HTTPException(404)
        return _no_store(FileResponse(PUBLIC_DIR / name))

    def login_page(self, request: Request):
        if self.session_uid(request) == self.uid:
            return _no_store(RedirectResponse("/", status_code=303))
        return _no_store(FileResponse(PUBLIC_DIR / "passkey-login.html"))

    def setup_page(self, request: Request):
        if not self.setup_google_enabled:
            raise HTTPException(404)
        return _no_store(FileResponse(PUBLIC_DIR / "passkey-login.html"))

    def reauth_page(self, request: Request):
        self.require_session(request)
        return _no_store(FileResponse(PUBLIC_DIR / "passkey-login.html"))

    def add_page(self, request: Request):
        self.require_session(request)
        session = self._session_data(request)
        if session.get("created_at", _now() - SESSION_LIFETIME) < _now() - CHALLENGE_LIFETIME:
            return _no_store(RedirectResponse("/auth/reauth", status_code=303))
        return _no_store(FileResponse(PUBLIC_DIR / "passkey-login.html"))


def mount_passkey_routes(app, auth: PasskeyAuth):
    app.add_api_route("/", auth.app_page, methods=["GET"])
    app.add_api_route("/index.html", auth.app_page, methods=["GET"])
    app.add_api_route("/auth/login", auth.login_page, methods=["GET"])
    app.add_api_route("/auth/setup", auth.setup_page, methods=["GET"])
    app.add_api_route("/auth/reauth", auth.reauth_page, methods=["GET"])
    app.add_api_route("/auth/add-passkey", auth.add_page, methods=["GET"])
    app.add_api_route("/auth/register/options", auth.register_options, methods=["POST"])
    app.add_api_route("/auth/register/complete", auth.register_complete, methods=["POST"])
    app.add_api_route("/auth/login/options", auth.login_options, methods=["POST"])
    app.add_api_route("/auth/login/complete", auth.login_complete, methods=["POST"])
    app.add_api_route("/auth/logout", auth.logout, methods=["POST"])
    def asset_handler(name):
        def serve(request: Request):
            return auth.asset(request, name)
        return serve

    for name in ASSETS:
        app.add_api_route(f"/{name}", asset_handler(name), methods=["GET"])
