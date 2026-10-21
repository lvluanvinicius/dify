#!/usr/bin/env python3
"""Print the .env block to append in Easypanel's Environment editor.

Easypanel fills the editor with docker/.env.example (official defaults, weak
secrets). Paste this block at the END of it: Docker Compose keeps the last
value of a repeated key, so these override the defaults without touching the
official file.

    python3 docker/easypanel/env.py --domain ai.example.com [--api-domain api.ai.example.com]

Run it once per installation. Secrets change on every run: never paste a new
block over an installation that already started (Postgres and Redis keep the
first password).
"""

from __future__ import annotations

import argparse
import re
import secrets
import sys

FQDN = re.compile(r"^([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")


def gen_hex() -> str:
    # Hex only: safe inside URLs such as redis://:<password>@redis:6379.
    return secrets.token_hex(32)


def gen_urlsafe() -> str:
    return secrets.token_urlsafe(32)


# Keys in one group must hold the same value. SECRET_KEY stays empty on purpose:
# Dify generates and persists its own key in the storage volume. Derived keys
# (DIFY_AGENT_INNER_API_KEY, DIFY_AGENT_PLUGIN_DAEMON_API_KEY, DIFY_AGENT_REDIS_URL)
# stay unset so the compose file derives them from these.
SECRETS = (
    (("DB_PASSWORD",), gen_hex),
    (("REDIS_PASSWORD",), gen_hex),
    (("PLUGIN_DAEMON_KEY",), gen_urlsafe),
    (("PLUGIN_DIFY_INNER_API_KEY",), gen_urlsafe),
    (("SANDBOX_API_KEY", "CODE_EXECUTION_API_KEY"), gen_urlsafe),
    (("WEAVIATE_API_KEY", "WEAVIATE_AUTHENTICATION_APIKEY_ALLOWED_KEYS"), gen_hex),
    (("DIFY_AGENT_SERVER_SECRET_KEY",), gen_urlsafe),
    (("DIFY_AGENT_API_TOKEN",), gen_urlsafe),
    (("DIFY_AGENT_LOCAL_SANDBOX_AUTH_TOKEN",), gen_urlsafe),
)


def domain(value: str) -> str:
    if not FQDN.match(value):
        raise argparse.ArgumentTypeError(f"use FQDN minúsculo, sem esquema: {value}")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--domain", type=domain, required=True, help="console e web apps")
    parser.add_argument("--api-domain", type=domain, help="Service API, triggers e endpoints de plugin")
    args = parser.parse_args()
    if args.api_domain == args.domain:
        parser.error("--api-domain deve ser diferente de --domain")

    public = f"https://{args.domain}"
    # URLs called by external systems move to the API domain; console, web apps
    # and files stay on the main domain.
    api = f"https://{args.api_domain or args.domain}"
    lines = [
        "",
        "# ---- easypanel (docker/easypanel/env.py): sobrescreve os padrões acima ----",
        "DB_TYPE=postgresql",
        "VECTOR_STORE=weaviate",
        f"CONSOLE_API_URL={public}",
        f"CONSOLE_WEB_URL={public}",
        f"APP_API_URL={public}",
        f"APP_WEB_URL={public}",
        f"FILES_URL={public}",
        f"SERVICE_API_URL={api}",
        f"TRIGGER_URL={api}",
        f"ENDPOINT_URL_TEMPLATE={api}/e/{{hook_id}}",
        f"NEXT_PUBLIC_SOCKET_URL=wss://{args.domain}",
        "SERVER_CONSOLE_API_URL=http://api:5001",
        "INTERNAL_FILES_URL=http://api:5001",
        # TLS terminates at Easypanel's Traefik; nginx only speaks HTTP inside.
        "NGINX_SERVER_NAME=_",
        "NGINX_HTTPS_ENABLED=false",
        "NGINX_PORT=80",
        "NGINX_ENABLE_CERTBOT_CHALLENGE=false",
        "SECRET_KEY=",
    ]
    values: dict[str, str] = {}
    for keys, generator in SECRETS:
        value = generator()
        values.update(dict.fromkeys(keys, value))
        lines += [f"{key}={value}" for key in keys]
    # .env.example embeds the default Redis password in this URL; without this
    # line Celery keeps authenticating with "difyai123456" and fails.
    lines.append(f"CELERY_BROKER_URL=redis://:{values['REDIS_PASSWORD']}@redis:6379/1")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
