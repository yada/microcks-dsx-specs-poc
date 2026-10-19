#!/usr/bin/env python3
"""Generate a throw-away RSA key pair, a JWKS file and an RS256 bearer token for a local
rest-api configured with a custom JWT issuer (stage 2). Needs: pip install pyjwt cryptography.
Usage: make_token.py <outdir>   -> <outdir>/jwks.json and <outdir>/token.txt
"""
import base64
import sys
import time
from pathlib import Path

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

out = Path(sys.argv[1])
out.mkdir(parents=True, exist_ok=True)
key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
nums = key.public_key().public_numbers()


def b64(n):
    return base64.urlsafe_b64encode(n.to_bytes((n.bit_length() + 7) // 8, "big")).rstrip(b"=").decode()


(out / "jwks.json").write_text(
    '{"keys":[{"kty":"RSA","use":"sig","alg":"RS256","kid":"s2","n":"%s","e":"%s"}]}' % (b64(nums.n), b64(nums.e)))
pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
now = int(time.time())
claims = {"iss": "http://poc-issuer", "aud": "nico-api", "sub": "poc-user", "iat": now, "exp": now + 86400,
          "email": "poc.user@example.com", "given_name": "Poc", "family_name": "User"}
(out / "token.txt").write_text(jwt.encode(claims, pem, algorithm="RS256", headers={"kid": "s2"}))
