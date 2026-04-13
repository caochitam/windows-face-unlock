"""Store the Windows password used by the Credential Provider.

Encrypted with DPAPI (user scope). Must be run as the same user that will log in.

Usage:
  python -m tools.set_password
  python -m tools.set_password --clear
"""
from __future__ import annotations
import argparse
import getpass
import os

from face_service.credentials import clear_password, load_password, save_password


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--clear", action="store_true")
    ap.add_argument("--user", default=os.environ.get("USERNAME", ""))
    ap.add_argument("--domain", default=os.environ.get("USERDOMAIN", "."))
    args = ap.parse_args()

    if args.clear:
        clear_password()
        print("Cleared stored credentials.")
        return

    print(f"User:   {args.user}")
    print(f"Domain: {args.domain}")
    pw = getpass.getpass("Windows password: ")
    pw2 = getpass.getpass("Confirm:          ")
    if pw != pw2:
        raise SystemExit("Passwords do not match.")
    save_password(args.user, pw, args.domain)

    # sanity check
    check = load_password()
    assert check and check["u"] == args.user
    print("Saved. DPAPI test: OK")


if __name__ == "__main__":
    main()
