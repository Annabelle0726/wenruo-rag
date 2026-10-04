"""Prepare local credentials for a NEW deployment. Never overwrite an existing .env."""
import argparse
from pathlib import Path
import secrets
import subprocess

ROOT = Path(__file__).resolve().parents[2]


def initialize(root):
    target = root / "docker/.env"
    if target.exists():
        raise FileExistsError("Existing docker/.env preserved. Password rotation requires updating the services too.")
    values = {}
    lines = []
    for line in (root / "docker/.env.example").read_text(encoding="utf-8").splitlines():
        if not line.lstrip().startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            if key.endswith(("_PASSWORD", "_SECRET", "_TOKEN", "_API_KEY")):
                # SMTP/provider credentials must be supplied by their administrator.
                if key in ("SMTP_PASSWORD", "SANDBOX_EXECUTOR_MANAGER_API_TOKEN"):
                    value = ""
                else:
                    value = "Wenruo-" + secrets.token_hex(16)
            values[key] = value
            line = key + "=" + value
        lines.append(line)
    private = root / "delivery-private"
    private.mkdir(exist_ok=True)
    password_file = private / "admin-password.txt"
    with password_file.open("x", encoding="utf-8") as handle:
        handle.write("Wenruo-" + secrets.token_urlsafe(16) + "\n")
    with target.open("x", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")
    return password_file


def run_seed(password_file, container, workspace_id):
    password = password_file.read_text(encoding="utf-8").strip()
    command = ["docker", "exec", "-i", "-e", "PYTHONPATH=/ragflow",
               container, "python", "/ragflow/tools/scripts/seed_admin.py"]
    if workspace_id:
        command += ["--workspace-id", workspace_id]
    subprocess.run(command, input=password, text=True, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", action="store_true", help="Seed an already-started deployment.")
    parser.add_argument("--container", default="wenruo-rag-cpu")
    parser.add_argument("--workspace-id", help="Optional existing workspace on which to grant ADMIN.")
    args = parser.parse_args()
    if args.seed:
        run_seed(ROOT / "delivery-private/admin-password.txt", args.container, args.workspace_id)
    else:
        password_file = initialize(ROOT)
        print("Local docker/.env created. Administrator: admin@wenruo.local")
        print("Password file:", password_file)
        print("Build/start the application, then run this script again with --seed.")


if __name__ == "__main__":
    main()
