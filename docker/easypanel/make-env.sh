#!/usr/bin/env bash
# Builds the complete .env for Easypanel: the official docker/.env.example with
# the domains, Easypanel-specific values and strong secrets replaced in place
# (one occurrence per key, no duplicates).
#
#   docker/easypanel/make-env.sh --domain ai.example.com [--api-domain api.ai.example.com] \
#       [--keep-from <.env em uso>] -o /root/dify-easypanel.env
#
# --keep-from reuses DB_PASSWORD, REDIS_PASSWORD and SECRET_KEY from an .env that
# already started: Postgres and Redis keep the password of their first start.
# The output file is never overwritten, so secrets cannot change by accident.
set -euo pipefail

die() { printf 'ERRO %s\n' "$*" >&2; exit 1; }

DOMAIN="" API_DOMAIN="" KEEP_FROM="" OUT=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --domain) DOMAIN="${2:-}"; shift 2 ;;
        --api-domain) API_DOMAIN="${2:-}"; shift 2 ;;
        --keep-from) KEEP_FROM="${2:-}"; shift 2 ;;
        -o) OUT="${2:-}"; shift 2 ;;
        -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
        *) die "argumento desconhecido: $1 (veja --help)" ;;
    esac
done

FQDN='^([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$'
[[ "$DOMAIN" =~ $FQDN ]] || die "--domain obrigatório (FQDN minúsculo, sem https://)"
[[ -z "$API_DOMAIN" || "$API_DOMAIN" =~ $FQDN ]] || die "--api-domain inválido: $API_DOMAIN"
[[ "$API_DOMAIN" != "$DOMAIN" ]] || die "--api-domain deve ser diferente de --domain"
[[ -n "$OUT" ]] || die "-o <arquivo> obrigatório"
[[ ! -e "$OUT" ]] || die "$OUT já existe; não sobrescrevo (as senhas mudariam). Apague-o só se ainda não houve deploy."
[[ -z "$KEEP_FROM" || -r "$KEEP_FROM" ]] || die "não consigo ler $KEEP_FROM"
command -v openssl >/dev/null || die "openssl não encontrado"

EXAMPLE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/.env.example"
[[ -r "$EXAMPLE" ]] || die "não achei $EXAMPLE"

(umask 077 && cp "$EXAMPLE" "$OUT")

# Replaces KEY=... in place (every key managed here appears once in .env.example);
# appends it when a future .env.example drops the key.
setkv() {
    local key="$1" value="$2" tmp
    tmp="$(mktemp "$OUT.XXXXXX")"
    awk -v k="$key" -v v="$value" '
        BEGIN { done = 0 }
        index($0, k "=") == 1 { print k "=" v; done = 1; next }
        { print }
        END { if (!done) print k "=" v }
    ' "$OUT" > "$tmp"
    chmod 600 "$tmp"
    mv "$tmp" "$OUT"
}

getkv() { grep "^$1=" "$2" | tail -1 | cut -d= -f2-; }

hex() { openssl rand -hex 32; }
# DIFY_AGENT_SERVER_SECRET_KEY must be base64url that decodes to exactly 32 bytes;
# hex is rejected by agent_backend.
b64url32() { openssl rand -base64 32 | tr '+/' '-_' | tr -d '=\n'; }

PUBLIC="https://$DOMAIN"
# URLs called by external systems go to the API domain; console, web apps and
# files stay on the main domain.
API="https://${API_DOMAIN:-$DOMAIN}"

setkv CONSOLE_API_URL "$PUBLIC"
setkv CONSOLE_WEB_URL "$PUBLIC"
setkv APP_API_URL "$PUBLIC"
setkv APP_WEB_URL "$PUBLIC"
setkv FILES_URL "$PUBLIC"
setkv SERVICE_API_URL "$API"
setkv TRIGGER_URL "$API"
setkv ENDPOINT_URL_TEMPLATE "$API/e/{hook_id}"
setkv NEXT_PUBLIC_SOCKET_URL "wss://$DOMAIN"
setkv SERVER_CONSOLE_API_URL "http://api:5001"
setkv INTERNAL_FILES_URL "http://api:5001"

# Must match the profiles baked into docker-compose.easypanel.yml.
setkv DB_TYPE postgresql
setkv VECTOR_STORE weaviate

# TLS terminates at Easypanel's Traefik; nginx only speaks HTTP inside.
setkv NGINX_SERVER_NAME _
setkv NGINX_HTTPS_ENABLED false
setkv NGINX_PORT 80
setkv NGINX_ENABLE_CERTBOT_CHALLENGE false

if [[ -n "$KEEP_FROM" ]]; then
    DB_PASSWORD="$(getkv DB_PASSWORD "$KEEP_FROM")"
    REDIS_PASSWORD="$(getkv REDIS_PASSWORD "$KEEP_FROM")"
    SECRET_KEY="$(getkv SECRET_KEY "$KEEP_FROM")"
    [[ -n "$DB_PASSWORD" && -n "$REDIS_PASSWORD" ]] || die "$KEEP_FROM sem DB_PASSWORD/REDIS_PASSWORD"
else
    DB_PASSWORD="$(hex)"
    REDIS_PASSWORD="$(hex)"
    # Empty on purpose: Dify generates and persists its own key in the storage volume.
    SECRET_KEY=""
fi
setkv DB_PASSWORD "$DB_PASSWORD"
setkv REDIS_PASSWORD "$REDIS_PASSWORD"
setkv SECRET_KEY "$SECRET_KEY"
# .env.example embeds the default Redis password in this URL.
setkv CELERY_BROKER_URL "redis://:$REDIS_PASSWORD@redis:6379/1"

setkv PLUGIN_DAEMON_KEY "$(hex)"
setkv PLUGIN_DIFY_INNER_API_KEY "$(hex)"
setkv DIFY_AGENT_API_TOKEN "$(hex)"
setkv DIFY_AGENT_LOCAL_SANDBOX_AUTH_TOKEN "$(hex)"
setkv DIFY_AGENT_SERVER_SECRET_KEY "$(b64url32)"
SANDBOX_KEY="$(hex)"
setkv SANDBOX_API_KEY "$SANDBOX_KEY"
setkv CODE_EXECUTION_API_KEY "$SANDBOX_KEY"
WEAVIATE_KEY="$(hex)"
setkv WEAVIATE_API_KEY "$WEAVIATE_KEY"
setkv WEAVIATE_AUTHENTICATION_APIKEY_ALLOWED_KEYS "$WEAVIATE_KEY"

# ------------------------------------------------------------------ checks
agent_key="$(getkv DIFY_AGENT_SERVER_SECRET_KEY "$OUT")"
padded="$agent_key$(printf '%*s' $(( (4 - ${#agent_key} % 4) % 4 )) '' | tr ' ' '=')"
[[ "$(printf '%s' "$padded" | tr '_-' '/+' | openssl base64 -d -A | wc -c)" -eq 32 ]] \
    || die "DIFY_AGENT_SERVER_SECRET_KEY não decodifica para 32 bytes"
[[ "$(getkv CELERY_BROKER_URL "$OUT")" == "redis://:$(getkv REDIS_PASSWORD "$OUT")@redis:6379/1" ]] \
    || die "CELERY_BROKER_URL não usa REDIS_PASSWORD"
LEFT="$(grep -nE '=(difyai123456|dify-sandbox|dify-agent-run-token-for-dev-only|WVF5YThaHlkYwhGUSmCRgsX3tD5ngdN8pkih|lYkiYYT6owG|QaHbTe77CtuX|MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY)' "$OUT" || true)"
[[ -z "$LEFT" ]] || die "ainda há segredos padrão do upstream em $OUT: $LEFT"
DUPS="$(grep -oE '^[A-Z_0-9]+=' "$OUT" | sort | uniq -d)"
[[ -z "$DUPS" ]] || die "chaves duplicadas em $OUT: $DUPS"

printf 'OK %s gerado (modo 600)%s\n' "$OUT" "${KEEP_FROM:+; DB_PASSWORD, REDIS_PASSWORD e SECRET_KEY mantidos de $KEEP_FROM}"
