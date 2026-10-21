#!/usr/bin/env bash
# Brings the easypanel branch to a new official Dify tag and regenerates
# docker-compose.easypanel.yml.
#
#   docker/easypanel/update.sh <nova-tag> [--push]
#
# The tag is MERGED into the branch (history is never rewritten, so Easypanel
# only ever sees fast-forwards). Our commits only add files upstream does not
# have (docker/docker-compose.easypanel.yml and docker/easypanel/), so the merge
# never conflicts.
set -euo pipefail

die() { printf 'ERRO %s\n' "$*" >&2; exit 1; }
step() { printf '\n==> %s\n' "$*"; }

NEW_TAG="${1:-}"
PUSH="${2:-}"
[[ -n "$NEW_TAG" && ( -z "$PUSH" || "$PUSH" == --push ) ]] || die "uso: $0 <nova-tag> [--push]"
OUR_PATHS='^docker/(docker-compose\.easypanel\.yml|easypanel/.*)$'

cd "$(git rev-parse --show-toplevel)"
[[ "$(git symbolic-ref --short -q HEAD)" == easypanel ]] || die "rode na branch easypanel"
git diff --quiet HEAD && git diff --cached --quiet || die "há alterações não commitadas"
[[ "$(git remote get-url upstream 2>/dev/null)" =~ github\.com[:/]langgenius/dify(\.git)?$ ]] \
    || die "remote 'upstream' deve apontar para langgenius/dify"

step "Buscando releases do upstream e o estado do origin"
git fetch upstream --tags --quiet
git fetch origin --quiet
[[ "$(git rev-parse HEAD)" == "$(git rev-parse origin/easypanel)" ]] \
    || die "branch local difere de origin/easypanel; rode 'git pull --ff-only' antes"
git rev-parse -q --verify "refs/tags/$NEW_TAG^{commit}" >/dev/null || die "tag $NEW_TAG não existe no upstream"
OLD_TAG="$(git describe --tags --abbrev=0 --exclude 'easypanel-*')"
[[ "$OLD_TAG" != "$NEW_TAG" ]] || die "a branch já está em $NEW_TAG"
! git merge-base --is-ancestor "refs/tags/$NEW_TAG" HEAD || die "$NEW_TAG já está contida na branch"
! git rev-parse -q --verify "refs/tags/easypanel-$NEW_TAG" >/dev/null || die "tag easypanel-$NEW_TAG já existe"
echo "    $OLD_TAG -> $NEW_TAG"

step "Variáveis novas ou removidas no .env.example ($OLD_TAG -> $NEW_TAG)"
CHANGED="$(git diff "refs/tags/$OLD_TAG" "refs/tags/$NEW_TAG" -- docker/.env.example \
    | grep -E '^[+-][A-Z_0-9]+=' | sed 's/=.*//' | sort -u || true)"
if [[ -n "$CHANGED" ]]; then printf '    %s\n' $CHANGED; else echo "    nenhuma"; fi

step "Mesclando $NEW_TAG"
git merge --quiet --no-ff --no-edit -m "easypanel: merge Dify $NEW_TAG" "refs/tags/$NEW_TAG"
FOREIGN="$(git diff --name-only "refs/tags/$NEW_TAG" HEAD | grep -vE "$OUR_PATHS" || true)"
[[ -z "$FOREIGN" ]] || die "a branch altera arquivos do upstream (não deveria): $FOREIGN"

step "Regenerando docker-compose.easypanel.yml"
python3 docker/easypanel/generate.py

step "Validando com docker compose config"
if command -v docker >/dev/null 2>&1; then
    if [[ ! -e docker/.env ]]; then
        trap 'rm -f docker/.env' EXIT
        docker/easypanel/make-env.sh --domain dify.example.com -o docker/.env >/dev/null
    fi
    (cd docker && docker compose -p easypanel-check -f docker-compose.easypanel.yml config --quiet)
    echo "    OK"
else
    echo "    docker indisponível: validação pulada"
fi

if ! git diff --quiet -- docker/docker-compose.easypanel.yml; then
    git add docker/docker-compose.easypanel.yml
    git commit --quiet -m "easypanel: regenerate compose for Dify $NEW_TAG"
fi
git tag "easypanel-$NEW_TAG"

step "Pronto: easypanel = $NEW_TAG + nossos arquivos (tag easypanel-$NEW_TAG)"
git log --oneline -3
if [[ "$PUSH" == --push ]]; then
    git push origin easypanel "easypanel-$NEW_TAG"
else
    echo
    echo "Leia as release notes de $OLD_TAG até $NEW_TAG antes de publicar. Depois:"
    echo "    git push origin easypanel easypanel-$NEW_TAG"
fi
