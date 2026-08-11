"""Deploy the API container to a DigitalOcean droplet.

Creates the droplet on the first run and reuses it on every run after that,
then syncs the repo to it and brings up the `api` service with docker compose.
The `cron` service is left down: starting it schedules jobs that write to the
real S3 warehouse, which is a separate decision.

    uv run python -m scripts.deploy_api

The droplet is x86_64, so the `linux/amd64` image runs natively there — unlike
on an Apple Silicon host, where polars segfaults under Rosetta emulation.
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path
from typing import Any

import httpx

from src.config import require


DO_API_URL = "https://api.digitalocean.com/v2"

DROPLET_NAME = "trading-data-warehouse"
REGION = "nyc3"

# 4 GB is the build, not the runtime: `uv sync` unpacking the arcticdb and
# polars wheels is the memory spike, and a 1 GB droplet dies partway through it.
SIZE = "s-2vcpu-4gb"
IMAGE = "ubuntu-24-04-x64"

# get.docker.com ships the compose plugin, so `docker compose` works without a
# second install step. Pinning a Docker marketplace image would go stale.
CLOUD_INIT = """#cloud-config
package_update: true
packages:
  - ca-certificates
  - curl
  - rsync
runcmd:
  - curl -fsSL https://get.docker.com | sh
  - systemctl enable --now docker
"""

DEPLOY_DIR = "/opt/warehouse"

# Everything the image build and `docker compose` need on the host. `.env` is
# excluded from the image on purpose (see .dockerignore) — compose reads it
# from disk at run time, so it has to be shipped separately.
SYNC_PATHS = (
    "Dockerfile",
    "docker-compose.yml",
    "pyproject.toml",
    "uv.lock",
    ".env",
    "src",
    "scripts",
    "docker",
)

# ssh tries these in order anyway; the first one that exists is uploaded to
# DigitalOcean so the droplet accepts a connection from this machine.
PUBLIC_KEY_NAMES = ("id_ed25519.pub", "id_ecdsa.pub", "id_rsa.pub")
PRIVATE_KEY_PATH = Path.home() / ".ssh" / "id_ed25519"

SSH_OPTIONS = (
    "-o",
    "StrictHostKeyChecking=accept-new",
    "-o",
    "ConnectTimeout=10",
)

CREATE_TIMEOUT_SECONDS = 300.0
BOOT_TIMEOUT_SECONDS = 600.0
POLL_SECONDS = 5.0

REPO_ROOT = Path(__file__).resolve().parent.parent


# ====================================
# --> Helper funcs
# ====================================


def _droplets(client: httpx.Client) -> list[dict[str, Any]]:
    """Every droplet on the account."""
    response = client.get("/droplets", params={"per_page": 200})
    response.raise_for_status()

    return response.json()["droplets"]


def _local_public_key() -> str:
    """This machine's SSH public key, generating one if it has none."""
    ssh_dir = Path.home() / ".ssh"

    for name in PUBLIC_KEY_NAMES:
        path = ssh_dir / name
        if path.exists():
            return path.read_text().strip()

    ssh_dir.mkdir(mode=0o700, exist_ok=True)
    print(f"no SSH key found — generating {PRIVATE_KEY_PATH}")

    subprocess.run(
        [
            "ssh-keygen",
            "-t",
            "ed25519",
            "-N",
            "",
            "-C",
            DROPLET_NAME,
            "-f",
            str(PRIVATE_KEY_PATH),
        ],
        check=True,
    )

    return PRIVATE_KEY_PATH.with_suffix(".pub").read_text().strip()


def _ssh_key_ids(client: httpx.Client) -> list[int]:
    """Ensure this machine's public key is on the account and return its id.

    Only this machine's key is attached: a droplet carrying somebody else's
    key would still refuse the ssh/rsync calls below, and without any key
    DigitalOcean emails a root password instead and every call hangs on a
    password prompt.
    """
    public_key = _local_public_key()
    # The trailing comment is free text and differs between machines; the
    # base64 body in the middle field is what identifies the key.
    body = public_key.split()[1]

    response = client.get("/account/keys")
    response.raise_for_status()

    for key in response.json()["ssh_keys"]:
        if key["public_key"].split()[1] == body:
            return [key["id"]]

    print(f"uploading this machine's public key to DigitalOcean as {DROPLET_NAME}")
    created = client.post(
        "/account/keys",
        json={"name": DROPLET_NAME, "public_key": public_key},
    )
    created.raise_for_status()

    return [created.json()["ssh_key"]["id"]]


def _public_ip(droplet: dict[str, Any]) -> str | None:
    """The droplet's public IPv4 address, or None while it is still booting."""
    for network in droplet["networks"]["v4"]:
        if network["type"] == "public":
            return network["ip_address"]

    return None


def _create_droplet(client: httpx.Client, name: str) -> dict[str, Any]:
    """Create the droplet and return it as soon as the API accepts the request."""
    response = client.post(
        "/droplets",
        json={
            "name": name,
            "region": REGION,
            "size": SIZE,
            "image": IMAGE,
            "ssh_keys": _ssh_key_ids(client),
            "user_data": CLOUD_INIT,
            "monitoring": True,
            "tags": ["warehouse"],
        },
    )
    response.raise_for_status()

    return response.json()["droplet"]


def _wait_for_ip(client: httpx.Client, droplet_id: int) -> str:
    """Poll the droplet until it is active and has a public address."""
    deadline = time.monotonic() + CREATE_TIMEOUT_SECONDS

    while time.monotonic() < deadline:
        response = client.get(f"/droplets/{droplet_id}")
        response.raise_for_status()

        droplet = response.json()["droplet"]
        address = _public_ip(droplet)

        if droplet["status"] == "active" and address:
            return address

        time.sleep(POLL_SECONDS)

    raise RuntimeError(f"Droplet {droplet_id} was not ready in time")


def _ssh(host: str, command: str, *, check: bool = True) -> int:
    """Run one command on the droplet as root."""
    result = subprocess.run(
        ["ssh", *SSH_OPTIONS, f"root@{host}", command],
        check=check,
    )

    return result.returncode


def _wait_for_boot(host: str) -> None:
    """Wait for SSH to answer, then for cloud-init to finish installing Docker."""
    deadline = time.monotonic() + BOOT_TIMEOUT_SECONDS

    while time.monotonic() < deadline:
        if _ssh(host, "true", check=False) == 0:
            break

        time.sleep(POLL_SECONDS)
    else:
        raise RuntimeError(f"{host} never accepted an SSH connection")

    # cloud-init is still installing Docker after sshd comes up; without this
    # wait the first `docker compose` call fails with "command not found".
    _ssh(host, "cloud-init status --wait")


def _sync(host: str) -> None:
    """Copy the deployable files to the droplet, deleting what no longer exists."""
    missing = [name for name in SYNC_PATHS if not (REPO_ROOT / name).exists()]
    if missing:
        raise RuntimeError(f"Missing locally: {', '.join(missing)}")

    _ssh(host, f"mkdir -p {DEPLOY_DIR}")

    subprocess.run(
        [
            "rsync",
            "--archive",
            "--compress",
            "--delete",
            "--exclude",
            "__pycache__",
            "-e",
            " ".join(["ssh", *SSH_OPTIONS]),
            *SYNC_PATHS,
            f"root@{host}:{DEPLOY_DIR}/",
        ],
        cwd=REPO_ROOT,
        check=True,
    )


# ====================================
# --> Deploy
# ====================================


def deploy(name: str = DROPLET_NAME) -> str:
    """Ensure the droplet exists, sync the repo to it, and start the API."""
    (token,) = require("DIGITALOCEAN_TOKEN")

    with httpx.Client(
        base_url=DO_API_URL,
        headers={"Authorization": f"Bearer {token}"},
        timeout=60.0,
    ) as client:
        existing = [d for d in _droplets(client) if d["name"] == name]

        if existing:
            droplet = existing[0]
            print(f"reusing droplet {name} ({droplet['id']})")
        else:
            droplet = _create_droplet(client, name)
            print(f"created droplet {name} ({droplet['id']}) — waiting for boot")

        host = _wait_for_ip(client, droplet["id"])

    print(f"droplet at {host}")
    _wait_for_boot(host)

    print(f"syncing {len(SYNC_PATHS)} paths to {DEPLOY_DIR}")
    _sync(host)

    print("building and starting the api container")
    _ssh(host, f"cd {DEPLOY_DIR} && docker compose up -d --build api")

    return host


def main() -> None:
    """Deploy and print where the API is now listening."""
    host = deploy()

    print(f"\napi:  http://{host}:8000")
    print(f"docs: http://{host}:8000/docs")
    print("\nThe API has no authentication and port 8000 is open to the internet.")
    print("Restrict it with a DigitalOcean firewall before leaving it running.")


if __name__ == "__main__":
    main()
