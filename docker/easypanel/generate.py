#!/usr/bin/env python3
"""Derive docker-compose.easypanel.yml from the official docker-compose.yaml.

The official file is never edited. Rerun this after every upstream update so
new services, variables and image tags flow in automatically:

    python3 docker/easypanel/generate.py            # write the file
    python3 docker/easypanel/generate.py --check    # fail if it is stale

Transformations (each one fixes something that breaks or is unsafe on Easypanel):
- profiles are resolved at generation time: services outside --profiles are
  dropped and `profiles:` is removed, so the deploy never depends on
  COMPOSE_PROFILES being read from Easypanel's .env;
- `ports` and `container_name` are removed (Easypanel routes HTTP through its
  own Traefik and flags both as conflicts with other projects);
- bind mounts of untracked paths (./volumes/db/data, ./volumes/app/storage...)
  become named volumes, so data never lives inside the Git checkout that
  Easypanel manages; bind mounts of tracked config files stay as they are;
- certbot mounts are dropped: TLS terminates at Easypanel's Traefik;
- depends_on entries pointing at dropped services are removed;
- nginx (and only nginx) joins the external `easypanel` network, so
  Easypanel's Traefik can reach it while the sandboxes stay isolated.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

DOCKER_DIR = Path(__file__).resolve().parent.parent
SOURCE = DOCKER_DIR / "docker-compose.yaml"
TARGET = DOCKER_DIR / "docker-compose.easypanel.yml"

# Matches the default COMPOSE_PROFILES of docker/.env.example (postgres + weaviate
# + the collaboration websocket that nginx proxies to).
DEFAULT_PROFILES = "postgresql,weaviate,collaboration"

# Certbot and its nginx mounts only matter when nginx terminates TLS itself.
DROPPED_MOUNT_PREFIXES = ("./volumes/certbot",)

# Easypanel's Traefik reaches containers over this external network. Its own
# override attaches only the service picked in Domains (and none while no service
# is picked); joining here keeps nginx reachable either way, while every other
# service stays off it (the sandboxes keep their internal networks).
EASYPANEL_NETWORK = "easypanel"
PUBLIC_SERVICE = "nginx"

PROFILES_HEADER = re.compile(r"^# oficial \(Dify [^,]+, profiles: ([a-z0-9_,-]+)\)\.$", re.MULTILINE)
DEFAULT_VALUE = re.compile(r"^\$\{[A-Za-z_][A-Za-z0-9_]*:?-(.+)\}$")


class LiteralDumper(yaml.SafeDumper):
    # The official file shares lists through YAML anchors; expand them instead
    # of emitting &id001 aliases.
    def ignore_aliases(self, data: Any) -> bool:
        return True


def _represent_str(dumper: yaml.SafeDumper, value: str) -> yaml.ScalarNode:
    # Keeps multi-line shell scripts readable instead of one escaped line.
    style = "|" if "\n" in value and not re.search(r"[ \t]\n", value) else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", value, style=style)


LiteralDumper.add_representer(str, _represent_str)


def git(*args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(DOCKER_DIR), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def is_tracked(rel_path: str) -> bool:
    """True when the path (file or directory) holds files tracked by Git."""
    return bool(git("ls-files", "--", rel_path))


def mount_source(source: str) -> str:
    """Resolves ${VAR:-./default} to the default path the official file uses."""
    match = DEFAULT_VALUE.match(source)
    return match.group(1) if match else source


def volume_name(rel_path: str) -> str:
    path = rel_path.removeprefix("./").removeprefix("volumes/")
    return re.sub(r"[^a-z0-9]+", "_", path.lower()).strip("_")


def convert_mounts(service: str, mounts: list[Any], named: dict[str, str]) -> list[Any]:
    result: list[Any] = []
    for mount in mounts:
        if isinstance(mount, dict):
            if mount.get("type") == "bind":
                raise SystemExit(f"{service}: bind mount na sintaxe longa não suportado: {mount}")
            result.append(mount)
            continue
        source, _, rest = str(mount).partition(":")
        source = mount_source(source)
        if not source.startswith("."):
            result.append(mount)  # already a named volume
            continue
        if source.startswith(DROPPED_MOUNT_PREFIXES):
            continue
        if is_tracked(source):
            result.append(mount)  # config shipped in the repository
            continue
        name = volume_name(source)
        if named.setdefault(name, source) != source:
            raise SystemExit(f"colisão de volume nomeado {name}: {named[name]} e {source}")
        result.append(f"{name}:{rest}")
    return result


def referenced_networks(services: dict[str, Any]) -> set[str]:
    names: set[str] = set()
    for spec in services.values():
        nets = spec.get("networks") or []
        names.update(nets if isinstance(nets, list) else nets.keys())
    return names


def build(profiles: set[str]) -> dict[str, Any]:
    source = yaml.safe_load(SOURCE.read_text())
    kept: dict[str, Any] = {}
    for name, spec in source["services"].items():
        service_profiles = set(spec.get("profiles") or [])
        if service_profiles and not service_profiles & profiles:
            continue
        kept[name] = spec

    named: dict[str, str] = {}
    for name, spec in kept.items():
        for key in ("profiles", "ports", "container_name"):
            spec.pop(key, None)
        deps = spec.get("depends_on")
        if isinstance(deps, dict):
            spec["depends_on"] = {d: c for d, c in deps.items() if d in kept}
        elif isinstance(deps, list):
            spec["depends_on"] = [d for d in deps if d in kept]
        if not spec.get("depends_on"):
            spec.pop("depends_on", None)
        if "volumes" in spec:
            spec["volumes"] = convert_mounts(name, spec["volumes"], named)
            if not spec["volumes"]:
                del spec["volumes"]

    used_volumes = {
        str(m).partition(":")[0]
        for spec in kept.values()
        for m in spec.get("volumes", [])
        if isinstance(m, str) and not str(m).startswith(".")
    }
    volumes: dict[str, Any] = {
        k: v for k, v in (source.get("volumes") or {}).items() if k in used_volumes
    }
    volumes.update({name: None for name in sorted(named)})

    if PUBLIC_SERVICE not in kept:
        raise SystemExit(f"serviço público {PUBLIC_SERVICE} não existe no compose oficial")
    public_nets = kept[PUBLIC_SERVICE].get("networks") or ["default"]
    if isinstance(public_nets, dict):
        public_nets = {**public_nets, EASYPANEL_NETWORK: None}
    else:
        public_nets = [*public_nets, EASYPANEL_NETWORK]
    kept[PUBLIC_SERVICE]["networks"] = public_nets

    used_networks = referenced_networks(kept)
    networks = {k: v for k, v in (source.get("networks") or {}).items() if k in used_networks}
    networks[EASYPANEL_NETWORK] = {"external": True}

    result: dict[str, Any] = {"services": kept}
    if networks:
        result["networks"] = networks
    if volumes:
        result["volumes"] = volumes
    return result


def render(profiles: set[str]) -> str:
    try:
        version = git("describe", "--tags", "--abbrev=0", "--exclude", "easypanel-*")
    except subprocess.CalledProcessError:
        version = "?"
    header = (
        "# ==================================================================\n"
        "# GERADO por docker/easypanel/generate.py a partir do docker-compose.yaml\n"
        f"# oficial (Dify {version}, profiles: {','.join(sorted(profiles))}).\n"
        "# Não edite à mão: altere o gerador e rode-o de novo.\n"
        "# ==================================================================\n"
    )
    body = yaml.dump(build(profiles), Dumper=LiteralDumper, sort_keys=False, width=4096)
    return header + body


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--profiles",
        help=f"profiles do compose oficial a incluir; padrão: os do arquivo atual, senão {DEFAULT_PROFILES}",
    )
    parser.add_argument("--check", action="store_true", help="falha se o arquivo estiver desatualizado")
    args = parser.parse_args()
    chosen = args.profiles
    if chosen is None and TARGET.exists():
        match = PROFILES_HEADER.search(TARGET.read_text())
        chosen = match.group(1) if match else None
    profiles = {p.strip() for p in (chosen or DEFAULT_PROFILES).split(",") if p.strip()}

    content = render(profiles)
    if args.check:
        if not TARGET.exists() or TARGET.read_text() != content:
            print(f"{TARGET.name} desatualizado; rode docker/easypanel/generate.py", file=sys.stderr)
            return 1
        print(f"{TARGET.name} em dia")
        return 0
    TARGET.write_text(content)
    print(f"{TARGET.relative_to(DOCKER_DIR.parent)} gerado")
    return 0


if __name__ == "__main__":
    sys.exit(main())
