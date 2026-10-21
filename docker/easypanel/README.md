# Dify no Easypanel

Guia completo para instalar, operar e atualizar o Dify no Easypanel a partir da
branch `easypanel` do repositório `lvluanvinicius/dify`.

- [1. Como funciona](#1-como-funciona)
- [2. Pré-requisitos](#2-pré-requisitos)
- [3. Instalação passo a passo](#3-instalação-passo-a-passo)
- [4. Validação depois do deploy](#4-validação-depois-do-deploy)
- [5. Problemas conhecidos e soluções](#5-problemas-conhecidos-e-soluções)
- [6. Atualizar para uma nova versão do Dify](#6-atualizar-para-uma-nova-versão-do-dify)
- [7. Rollback](#7-rollback)
- [8. Backup e restauração](#8-backup-e-restauração)
- [9. Senhas: o que pode e o que não pode mudar](#9-senhas-o-que-pode-e-o-que-não-pode-mudar)
- [10. Regras do repositório](#10-regras-do-repositório)

---

## 1. Como funciona

### Repositório

| Remote | Aponta para | Uso |
|---|---|---|
| `upstream` | `https://github.com/langgenius/dify.git` | só leitura: de onde vêm as versões novas (push desativado) |
| `origin` | `https://github.com/lvluanvinicius/dify.git` | nosso repositório; o Easypanel lê daqui |

A branch **`easypanel`** é sempre **uma tag oficial do Dify + os nossos arquivos**.
Nenhum arquivo oficial é editado; nós só **adicionamos**:

```
docker/docker-compose.easypanel.yml   GERADO. É o arquivo que o Easypanel usa
docker/easypanel/generate.py          gera o arquivo acima a partir do docker-compose.yaml oficial
docker/easypanel/make-env.sh          gera o .env completo (domínios + senhas fortes)
docker/easypanel/update.sh            leva a branch para uma nova tag oficial
docker/easypanel/README.md            este documento
```

Como as versões novas do Dify nunca mexem nesses arquivos, a atualização (merge da
tag nova) **nunca dá conflito**.

### O que o `docker-compose.easypanel.yml` muda em relação ao oficial

Ele é gerado pelo `generate.py` a partir do `docker/docker-compose.yaml` da tag. Imagens,
variáveis, comandos, healthchecks e redes internas ficam **idênticos** ao oficial.
Só isto muda:

| Problema do compose oficial no Easypanel | O que o gerador faz |
|---|---|
| `ports` 80/443 (nginx) e 5003 (plugin_daemon) colidem com o Traefik do Easypanel | remove; o acesso entra pelos **Domains** do Easypanel |
| `container_name` colide entre projetos | remove |
| banco, uploads, Redis, plugins e Weaviate gravados em `./volumes/...`, dentro do checkout Git que o Easypanel controla | viram **volumes nomeados** (`db_data`, `app_storage`, `redis_data`, `plugin_daemon`, `weaviate`, `sandbox_dependencies`) |
| serviços dependem do `COMPOSE_PROFILES` do `.env` | os profiles são resolvidos na geração (`postgresql,weaviate,collaboration`); os demais serviços saem do arquivo |
| montagens do certbot | removidas; o HTTPS é do Traefik do Easypanel |
| o Traefik do Easypanel só alcança containers na rede externa `easypanel` | o `nginx`, e **só ele**, entra nessa rede; `sandbox` e `local_sandbox` continuam isolados nas redes internas |

Os arquivos de configuração versionados (nginx, squid, `volumes/sandbox/conf`)
continuam como bind mounts do repositório.

### Como o Easypanel executa

Em cada **Deploy**, o Easypanel:

1. atualiza o clone em `/etc/easypanel/projects/<projeto>/<serviço>/code/`;
2. **regrava** `code/docker/.env` com o conteúdo do editor **Environment** do serviço;
3. gera `code/docker/docker-compose.override.yml`, que liga o serviço escolhido em
   **Domains** à rede `easypanel` com o alias `<projeto>_<serviço>_<serviço do compose>`;
4. roda:
   ```
   docker compose -f docker-compose.easypanel.yml -f docker-compose.override.yml -p <projeto>_<serviço> up --build -d
   ```

Consequências práticas:
- **editar o `.env` direto no servidor não adianta**, porque o próximo deploy sobrescreve;
  o `.env` vale o que estiver no painel;
- **salvar Source ou Environment não faz deploy**; é preciso clicar em **Deploy**.

---

## 2. Pré-requisitos

- Easypanel instalado no servidor, com acesso SSH como `root`.
- DNS dos dois domínios apontando para o IP do servidor do Easypanel:
  - console e web apps: ex. `ai-cednet.grupocednet.com.br`;
  - API pública (opcional): ex. `api.ai-cednet.grupocednet.com.br`.
- Se o repositório for **privado**: a deploy key do Easypanel cadastrada no GitHub
  (somente leitura). Se for público, não precisa.
- `openssl` no servidor, que já vem nas distribuições comuns.

Confira o DNS antes de começar:

```bash
getent hosts ai-cednet.grupocednet.com.br
getent hosts api.ai-cednet.grupocednet.com.br
```

---

## 3. Instalação passo a passo

Nos exemplos: projeto `grupo_cednet`, serviço `dify`. Troque pelos seus nomes. O nome
do projeto Compose fica `grupo_cednet_dify`.

> Recomendado: um **projeto do Easypanel só para o Dify**. Nomes como `api`, `web` e
> `redis` são genéricos e podem confundir outros serviços do mesmo projeto.

### 3.1 Criar o serviço

**New Service → Compose → Git**, com estes campos **exatamente**:

| Campo | Valor |
|---|---|
| Repository URL | `https://github.com/lvluanvinicius/dify.git` (ou `git@github.com:lvluanvinicius/dify.git` se privado) |
| Branch | `easypanel` |
| Build Path | `/docker` |
| Docker Compose File | `docker-compose.easypanel.yml` |

Salve **sem fazer deploy ainda**. Se o Build Path ficar `/` ou o arquivo ficar
`docker-compose.yaml`, o Easypanel usa o compose oficial, com portas 80/443, e falha.

### 3.2 Gerar o `.env`

O Easypanel precisa ter clonado o repositório. Se a pasta abaixo ainda não existir,
faça um primeiro **Deploy** (ele pode falhar, não tem problema) e volte aqui.

```bash
ls /etc/easypanel/projects/grupo_cednet/dify/code/docker/easypanel/make-env.sh
```

Gere o `.env` completo, rodando como `root` no servidor:

```bash
D=/etc/easypanel/projects/grupo_cednet/dify/code/docker

$D/easypanel/make-env.sh \
  --domain ai-cednet.grupocednet.com.br \
  --api-domain api.ai-cednet.grupocednet.com.br \
  -o /root/dify-easypanel.env
```

- `--api-domain` é opcional. Sem ele, a API pública fica no domínio principal.
- O script parte do `.env.example` oficial da versão. Ele **substitui no lugar**:
  - as URLs;
  - os valores do Easypanel: `DB_TYPE=postgresql`, `VECTOR_STORE=weaviate`, nginx em
    HTTP na porta 80;
  - todas as senhas, geradas com `openssl rand`.
- Ele valida o resultado sozinho:
  - a chave do agent decodifica para 32 bytes;
  - o `CELERY_BROKER_URL` usa a senha do Redis;
  - nenhuma senha padrão do upstream sobrou;
  - nenhuma chave aparece duplicada.
- **Ele nunca sobrescreve** o arquivo de saída. Assim, as senhas não mudam por acidente.
- O arquivo fica com permissão `600`. **Guarde uma cópia fora do servidor**: é o
  backup das senhas.

Se já existe uma instalação rodando e você só quer trocar as outras chaves, preservando
banco, Redis e `SECRET_KEY`, use `--keep-from` com o `.env` atual:

```bash
D=/etc/easypanel/projects/grupo_cednet/dify/code/docker
$D/easypanel/make-env.sh \
  --domain ai-cednet.grupocednet.com.br \
  --api-domain api.ai-cednet.grupocednet.com.br \
  --keep-from $D/.env \
  -o /root/dify-easypanel.env
```

Conferência rápida (mascarada):

```bash
F=/root/dify-easypanel.env
for k in CONSOLE_API_URL SERVICE_API_URL DB_PASSWORD REDIS_PASSWORD SANDBOX_API_KEY \
         CODE_EXECUTION_API_KEY DIFY_AGENT_SERVER_SECRET_KEY CELERY_BROKER_URL; do
  v=$(grep "^$k=" "$F" | cut -d= -f2-)
  case $k in *_URL) echo "$k=$v" | sed -E 's#://:[^@]+@#://:****@#';; *) echo "$k=${v:0:6}…";; esac
done
```

### 3.3 Colar no painel

1. Serviço `dify` → aba **Environment**. É a aba do **serviço**, não a do projeto.
2. Selecione tudo, apague e cole a saída de:
   ```bash
   cat /root/dify-easypanel.env
   ```
3. Deixe **Create .env file** ligado.
4. **Save**. Reabra a aba e confira se `SANDBOX_API_KEY` mostra o valor novo, e não
   `dify-sandbox`.

### 3.4 Domains

Serviço `dify` → aba **Domains** → adicione os dois domínios:

| Host | Serviço do compose | Porta | Protocolo |
|---|---|---|---|
| `ai-cednet.grupocednet.com.br` | **`nginx`** | `80` | HTTP |
| `api.ai-cednet.grupocednet.com.br` | **`nginx`** | `80` | HTTP |

> **Escolha o serviço `nginx` em cada domínio.** Se o campo ficar vazio, o Easypanel
> grava o destino `http://grupo_cednet_dify_undefined:80/` e o site responde 502.

Os dois domínios apontam para o mesmo nginx; o Dify separa console, API e web apps
pelo caminho da URL (`/console/api`, `/v1`, `/api`...). O certificado de cada domínio é
emitido automaticamente pelo Easypanel.

### 3.5 Deploy

Clique em **Deploy** e espere terminar, sem cancelar. No primeiro deploy:
- as imagens (vários GB) são baixadas;
- o `api` roda as migrations do banco, o que leva 1 a 2 minutos.

### 3.6 Criar o administrador

Assim que a validação da seção 4 passar, acesse
`https://ai-cednet.grupocednet.com.br/install` e crie a conta de administrador.
**Faça isso logo**: até lá, qualquer pessoa que abrir essa página pode criar o admin.

---

## 4. Validação depois do deploy

```bash
P=grupo_cednet_dify
D=/etc/easypanel/projects/grupo_cednet/dify/code/docker
DOMAIN=ai-cednet.grupocednet.com.br
API_DOMAIN=api.ai-cednet.grupocednet.com.br

echo "== commit em uso";            git -C $D log --oneline -1
echo "== .env aplicado";            diff <(grep -v '^\s*$' /root/dify-easypanel.env) <(grep -v '^\s*$' $D/.env) >/dev/null && echo IGUAL || echo DIFERENTE
echo "== containers";               docker ps -a --filter label=com.docker.compose.project=$P --format '{{.Names}}\t{{.Status}}'
echo "== destino dos domínios";     grep -n -A6 "\"${P}-[0-9]*\": {" /etc/easypanel/traefik/config/main.yaml | grep url
echo "== redes do nginx";           docker inspect $P-nginx-1 --format '{{range $k,$v := .NetworkSettings.Networks}}{{$k}} {{end}}'
echo "== redes dos sandboxes";      docker inspect $P-sandbox-1 $P-local_sandbox-1 --format '{{.Name}}: {{range $k,$v := .NetworkSettings.Networks}}{{$k}} {{end}}'
echo "== worker -> redis";          docker exec $P-worker-1 sh -c 'python -c "import os,redis;print(redis.Redis.from_url(os.environ[\"CELERY_BROKER_URL\"]).ping())"'
echo "== agent_backend";            docker logs --tail 3 $P-agent_backend-1 2>&1
echo "== console";                  curl -sI https://$DOMAIN/console/api/setup | head -1
echo "== API pública";              curl -s -o /dev/null -w '%{http_code}\n' https://$API_DOMAIN/v1/info
```

Resultado esperado:

| Item | Esperado |
|---|---|
| commit em uso | o último da branch `easypanel` no GitHub |
| `.env` aplicado | `IGUAL` |
| containers | todos `Up` (os com healthcheck, `healthy`); `init_permissions` = `Exited (0)` |
| destino dos domínios | `http://grupo_cednet_dify_nginx:80/` (nunca `_undefined`) |
| redes do nginx | `easypanel` e `grupo_cednet_dify_default` |
| redes dos sandboxes | `sandbox`: só `..._ssrf_proxy_network`; `local_sandbox`: só `..._agent_sandbox_network` e `..._local_sandbox_proxy_network`. **Nunca `easypanel`** |
| worker -> redis | `True` |
| agent_backend | `Application startup complete` / `Uvicorn running on http://0.0.0.0:5050` |
| console | `HTTP/2 200` |
| API pública | `401` (esperado sem chave de API: prova que o domínio chega na API) |

---

## 5. Problemas conhecidos e soluções

| Sintoma | Causa | Solução |
|---|---|---|
| nenhum container criado; sem `docker-compose.override.yml` | o deploy não foi disparado (salvar não faz deploy) | clique em **Deploy** |
| log do Easypanel com `docker compose -f .../docker-compose.yaml` ou caminho estranho (`code/dify/code/`) | Source errado | Build Path `/docker`, arquivo `docker-compose.easypanel.yml` |
| `Command was canceled` / `AbortError` no log do Easypanel | o deploy estourou o tempo (download de imagens) ou foi cancelado | deploy de novo; as imagens já baixadas ficam em cache |
| `.env` do servidor diferente do gerado | conteúdo não salvo no painel, ou colado no Environment do **projeto** | cole no Environment do **serviço**, salve, reabra para conferir, deploy |
| HTTP **503** no domínio | o Traefik não alcança nenhum container | confira se há serviço escolhido em Domains e se o nginx está na rede `easypanel` |
| HTTP **502** e destino `..._undefined:80` | Domain sem serviço do compose escolhido | em Domains, escolha `nginx`, porta 80, HTTP; deploy |
| HTTP 502 logo após o deploy, destino correto | o `api` ainda está iniciando ou rodando migrations | espere o `api` ficar `healthy` |
| `curl` retorna `000` | DNS ainda não propagou ou domínio não cadastrado em Domains | `getent hosts <domínio>`; cadastre o domínio |
| `agent_backend` reiniciando: `DIFY_AGENT_SERVER_SECRET_KEY must decode to exactly 32 decoded bytes` | a chave foi gerada em hex | gere em base64url de 32 bytes (o `make-env.sh` já faz): `openssl rand -base64 32 \| tr '+/' '-_' \| tr -d '='` |
| worker sem conectar no Redis (erro de autenticação) | `CELERY_BROKER_URL` ainda com `difyai123456` | o `make-env.sh` já corrige; à mão: `CELERY_BROKER_URL=redis://:<REDIS_PASSWORD>@redis:6379/1` |
| `api`/`plugin_daemon` sem acesso ao banco depois de trocar `DB_PASSWORD` | o Postgres guarda a senha do **primeiro** start | volte a senha antiga, ou faça o reset de volumes (abaixo) se a instalação for nova |
| `volume is in use` ao apagar volumes | ainda há containers, mesmo parados, usando o volume | use o `down -v` abaixo |
| `docker compose up` rodado à mão criou containers `docker-*` | projeto errado (nome da pasta) e fora do Easypanel | `docker compose -f docker-compose.easypanel.yml down -v` na pasta; nunca rode `up` à mão |

Mensagens de log que **não** são erro:
- `sandbox`: `tar: /opt/node-...tar.xz: Cannot open` e `ln: ... File exists`, a cada
  restart. O Node já foi extraído antes.
- `ssrf_proxy` / `agent_ssrf_proxy`: `WARNING: (B) '0.0.0.0/8' is a subnetwork of (A) ...`.
  Vem da config oficial.
- `redis`: `WARNING Memory overcommit must be enabled!`. É recomendação do sistema
  operacional. Para eliminar: `sysctl -w vm.overcommit_memory=1` e
  `echo 'vm.overcommit_memory = 1' >> /etc/sysctl.conf`.

### Reset completo de uma instalação nova (apaga TODOS os dados)

Use só se ninguém usou a instância, por exemplo quando ela subiu com senhas erradas:

```bash
cd /etc/easypanel/projects/grupo_cednet/dify/code/docker
docker compose -f docker-compose.easypanel.yml -f docker-compose.override.yml -p grupo_cednet_dify down -v
docker volume ls --format '{{.Name}}' | grep '^grupo_cednet_dify_' || echo "volumes removidos"
```

Depois: gere um `.env` novo (seção 3.2, apagando antes o `/root/dify-easypanel.env`
antigo), cole no painel e faça o deploy.

### Coletar diagnóstico

```bash
{
echo "== log do Easypanel"; docker service logs -t easypanel --since 1h 2>&1 | cut -c1-300 | tail -40
D=/etc/easypanel/projects/grupo_cednet/dify/code/docker
echo "== commit"; git -C $D log --oneline -1
echo "== override"; cat $D/docker-compose.override.yml
echo "== containers"; docker ps -a --filter label=com.docker.compose.project=grupo_cednet_dify --format '{{.Names}}\t{{.Status}}'
echo "== chaves do .env (sem valores)"; tail -5 $D/.env | cut -d= -f1
} 2>&1 | tee /tmp/dify-easypanel-diag.txt
```

---

## 6. Atualizar para uma nova versão do Dify

A atualização é feita **num clone do repositório**, fora do Easypanel; depois você
publica no GitHub e faz o deploy no painel. Faça em janela de manutenção e
**com backup** (seção 8).

### 6.1 Preparar o clone (só na primeira vez)

Em qualquer máquina com `git`, `python3` (com PyYAML), `openssl` e, de preferência,
`docker`:

```bash
git clone https://github.com/lvluanvinicius/dify.git dify-easypanel
cd dify-easypanel
git switch easypanel
git remote add upstream https://github.com/langgenius/dify.git
git remote set-url --push upstream DISABLED      # nunca enviar nada ao oficial
git fetch upstream --tags
python3 -c 'import yaml' || pip install pyyaml
```

> No servidor onde este repositório foi montado, o clone já existe:
> `/data/dify-easypanel` (worktree de `/data/dify`), com os remotes prontos.

### 6.2 Ver quais versões existem

```bash
git fetch upstream --tags
git tag --sort=-v:refname | grep -vE '^easypanel-|rc|beta|alpha' | head -5   # versões estáveis
git describe --tags --abbrev=0 --exclude 'easypanel-*'                       # versão atual da branch
```

**Leia as release notes de TODAS as versões entre a atual e a nova:**
https://github.com/langgenius/dify/releases. Nem toda versão sobe só com pull + up;
algumas pedem passos manuais.

### 6.3 Rodar a atualização

```bash
git switch easypanel
git pull --ff-only
docker/easypanel/update.sh 1.18.0        # troque pela versão desejada
```

O script:
1. confere se a árvore está limpa, se a branch está igual ao `origin` e se a tag existe;
2. **lista as variáveis novas ou removidas** no `.env.example` entre as duas versões;
3. faz o **merge** da tag na branch, sem reescrever o histórico;
4. confere que a branch não altera nenhum arquivo do upstream;
5. regenera o `docker-compose.easypanel.yml` e valida com `docker compose config`;
6. faz o commit e cria a tag `easypanel-<versão>`, que serve de ponto de rollback.

Revise o que mudou no compose gerado:

```bash
git diff easypanel-<versão-anterior> -- docker/docker-compose.easypanel.yml
```

Publique:

```bash
git push origin easypanel easypanel-1.18.0
```

### 6.4 Variáveis novas

Se o passo 2 listou variáveis novas:
- **com valor padrão funcional:** não precisa fazer nada; o compose já usa o padrão;
- **segredos novos ou valores que você quer definir:** acrescente a linha no editor
  **Environment** do painel e atualize o `/root/dify-easypanel.env`, para o backup ficar
  igual;
- **segredos novos que o `make-env.sh` deveria gerar:** acrescente no script, commite e
  publique antes do deploy.

Para comparar em detalhe:

```bash
git diff <versão-anterior> <versão-nova> -- docker/.env.example
```

### 6.5 Backup e deploy no servidor

```bash
# no servidor do Easypanel: backup do banco antes (seção 8)
```

No painel: serviço `dify` → **Deploy**. As migrations rodam sozinhas no start do `api`.
Depois, rode a validação da seção 4. O commit em uso deve ser o novo.

---

## 7. Rollback

### Voltar a branch para a versão anterior

O push abaixo **reescreve a branch**, por isso ele precisa de `--force-with-lease`. É a
única operação deste guia que faz isso.

```bash
git push --force-with-lease origin refs/tags/easypanel-1.17.1:refs/heads/easypanel
git fetch origin && git switch easypanel && git reset --hard origin/easypanel
```

Depois, faça o **Deploy** no painel. Se o Easypanel não aceitar a branch reescrita,
remova a pasta `code/` do serviço e faça o deploy de novo; os volumes não ficam nessa pasta.

### Banco

As migrations do Dify **não são revertidas** automaticamente. Se a versão nova já rodou
migrations, a versão anterior pode não funcionar com o schema novo: restaure o dump
feito antes da atualização (seção 8).

---

## 8. Backup e restauração

Os dados ficam em volumes Docker do projeto `grupo_cednet_dify`:

```bash
docker volume ls --format '{{.Name}}' | grep '^grupo_cednet_dify_'
```

### Backup

```bash
P=grupo_cednet_dify
B=/root/backup-dify/$(date +%Y%m%d-%H%M%S); mkdir -p $B && chmod 700 $B

# 1. banco (cópia consistente, com o sistema rodando)
docker exec $P-db_postgres-1 pg_dumpall -U postgres | gzip > $B/pg_dumpall.sql.gz

# 2. arquivos enviados, plugins e vector store (cópia a quente)
for v in app_storage plugin_daemon weaviate; do
  docker run --rm -v ${P}_$v:/data:ro -v $B:/backup busybox tar czf /backup/$v.tar.gz -C /data .
done

# 3. senhas
cp -p /root/dify-easypanel.env $B/

ls -la $B
```

Copie a pasta para **fora do servidor**. Ela contém senhas.

### Restaurar o banco

```bash
P=grupo_cednet_dify; B=/root/backup-dify/<data>
# no painel: Stop no serviço; depois suba só o banco:
cd /etc/easypanel/projects/grupo_cednet/dify/code/docker
docker compose -f docker-compose.easypanel.yml -f docker-compose.override.yml -p $P up -d db_postgres
docker exec $P-db_postgres-1 psql -U postgres -c 'DROP DATABASE IF EXISTS dify' -c 'DROP DATABASE IF EXISTS dify_plugin'
zcat $B/pg_dumpall.sql.gz | docker exec -i $P-db_postgres-1 psql -U postgres -d postgres
# no painel: Deploy
```

---

## 9. Senhas: o que pode e o que não pode mudar

| Chave | Pode trocar depois do 1º deploy? |
|---|---|
| `DB_PASSWORD` | **não** sem `ALTER ROLE` no Postgres, porque ele guarda a senha do primeiro start |
| `REDIS_PASSWORD` | sim, mas troque o `CELERY_BROKER_URL` junto |
| `SECRET_KEY` | **não**: vazio, o Dify gera e guarda a própria chave no volume; trocar derruba as sessões |
| `PLUGIN_DAEMON_KEY`, `PLUGIN_DIFY_INNER_API_KEY` | sim (deploy recria tudo junto) |
| `SANDBOX_API_KEY` = `CODE_EXECUTION_API_KEY` | sim, **sempre iguais** |
| `WEAVIATE_API_KEY` = `WEAVIATE_AUTHENTICATION_APIKEY_ALLOWED_KEYS` | sim, **sempre iguais** |
| `DIFY_AGENT_API_TOKEN`, `DIFY_AGENT_LOCAL_SANDBOX_AUTH_TOKEN` | sim |
| `DIFY_AGENT_SERVER_SECRET_KEY` | sim; precisa ser base64url de 32 bytes |

Para trocar só as chaves "sim", preservando banco, Redis e `SECRET_KEY`, use o
`make-env.sh --keep-from` (seção 3.2) e cole o resultado no painel.

---

## 10. Regras do repositório

- **Não edite arquivos do upstream** na branch `easypanel`. Ajustes vão no `generate.py`
  ou no `make-env.sh`; o `docker-compose.easypanel.yml` é sempre regenerado.
- **Não commite `.env`** (já está no `.gitignore` oficial). As senhas ficam só no painel
  do Easypanel e no backup `/root/dify-easypanel.env`.
- **Não rode `docker compose up` à mão** na pasta do Easypanel: cria um projeto paralelo,
  fora do controle dele.
- O push para `upstream` fica desativado (`pushurl = DISABLED`).
- O Dependabot do GitHub abre PRs automáticos, porque a configuração dele vem do
  upstream. Feche-os, ou desative em *Settings → Code security → Dependabot*. Atualização
  é sempre via `update.sh`.
