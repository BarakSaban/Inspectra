"""Print a VAPID key pair for Web Push. Copy the two lines into `.env`.

    python -m tools.vapid
"""
import base64

from cryptography.hazmat.primitives import serialization
from py_vapid import Vapid


def main():
    vapid = Vapid()
    vapid.generate_keys()
    b64 = lambda raw: base64.urlsafe_b64encode(raw).rstrip(b"=").decode()  # noqa: E731
    public = vapid.public_key.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    private = vapid.private_key.private_numbers().private_value.to_bytes(32, "big")
    print(f"INSPECTRA_VAPID_PUBLIC_KEY={b64(public)}")
    print(f"INSPECTRA_VAPID_PRIVATE_KEY={b64(private)}")
    print("INSPECTRA_VAPID_SUBJECT=mailto:you@example.com")


if __name__ == "__main__":
    main()
