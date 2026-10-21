# Dify no Easypanel

A branch `easypanel` deste repositório é sempre **uma tag oficial do Dify mais os
nossos commits**. Esses commits só **adicionam** arquivos que o upstream não tem:

```
docker/docker-compose.easypanel.yml   gerado; é o arquivo que o Easypanel usa
docker/easypanel/generate.py          gera o arquivo acima a partir do docker-compose.yaml oficial
docker/easypanel/env.py               gera o bloco de .env (domínios + secrets)
docker/easypanel/update.sh            leva a branch para uma nova tag oficial
docker/easypanel/README.md            este arquivo
```

Nenhum arquivo oficial é editado. Por isso uma versão nova do Dify nunca entra em
conflito com as nossas mudanças.

## O que muda em relação ao compose oficial

O `generate.py` lê o `docker/docker-compose.yaml` da tag e aplica só estas mudanças:

| Problema no Easypanel | Tratamento |
|---|---|
| `ports` (nginx 80/443, plugin_daemon 5003) colidem com o Traefik do Easypanel e com outros projetos | removidos; o acesso público é feito pelos Domains do Easypanel |
| `container_name` colide entre projetos | removido |
| bind mounts em `./volumes/...` guardam banco, uploads e plugins dentro do checkout Git que o Easypanel gerencia | viram volumes nomeados (`db_data`, `app_storage`, `redis_data`, `plugin_daemon`, `weaviate`, `sandbox_dependencies`) |
| `profiles` dependem do `COMPOSE_PROFILES` do `.env` | resolvidos na geração (`postgresql,weaviate,collaboration`); os serviços de outros profiles saem do arquivo |
| montagens do certbot | removidas; o TLS termina no Traefik do Easypanel |
| o override que o Easypanel gera só declara a rede `easypanel`, sem ligar serviço nenhum a ela, e o Traefik responde 503 | o `nginx`, e só ele, entra na rede externa `easypanel`; os sandboxes continuam só nas redes internas |

O resto fica idêntico ao oficial: imagens, variáveis, comandos, healthchecks e as
redes `internal` que isolam o sandbox. Os arquivos de config versionados (nginx,
squid, `volumes/sandbox/conf`) continuam como bind mounts do repositório.

Outro banco ou vector store: `python3 docker/easypanel/generate.py --profiles mysql,qdrant`.
Depois ajuste `DB_TYPE` e `VECTOR_STORE` no `.env`.

## Configuração no Easypanel

Crie um **projeto só para o Dify**. Os nomes dos serviços (`api`, `redis`, `web`...)
são genéricos e podem colidir com outros serviços do mesmo projeto.

1. **New Service → Compose → Git**
   - Repository URL: `git@github.com:lvluanvinicius/dify.git` (repositório privado:
     cadastre a deploy key que o Easypanel mostrar, somente leitura, no GitHub)
   - Branch: `easypanel`
   - Build Path: `/docker`
   - Docker Compose File: `docker-compose.easypanel.yml`
2. **Environment**
   - O Easypanel preenche o editor com o `docker/.env.example` oficial. Mantenha esse
     conteúdo e cole **no final** a saída de:
     ```bash
     python3 docker/easypanel/env.py --domain ai.cliente.com.br --api-domain api.ai.cliente.com.br
     ```
     (`--api-domain` é opcional; sem ele, a API fica no domínio principal.) O Compose
     usa o último valor de uma chave repetida, então o bloco sobrescreve os padrões.
   - Ative **Create .env file**. Vários serviços leem `./.env` via `env_file`, e o
     deploy falha sem ele.
   - Gere o bloco **uma vez por instalação**. Postgres e Redis guardam a senha do
     primeiro start; um bloco novo sobre uma instalação existente quebra o acesso.
3. **Domains** (os dois apontam para o mesmo nginx; o Dify roteia pelo caminho)
   - `ai.cliente.com.br` → serviço `nginx`, porta `80`, HTTP
   - `api.ai.cliente.com.br` → serviço `nginx`, porta `80`, HTTP
4. **Deploy**. Na primeira subida o `api` aplica as migrations. Depois, acesse
   `https://ai.cliente.com.br/install` e crie o administrador.

### Conferir depois do primeiro deploy

- **Isolamento:** `sandbox` e `local_sandbox` devem estar só nas redes internas, sem a
  rede do Easypanel. Se o Easypanel conectar todos os serviços à rede do projeto, o
  código executado pelo sandbox ganha saída direta, sem passar pelo `ssrf_proxy`:
  ```bash
  docker inspect $(docker ps -qf name=sandbox) --format '{{.Name}} {{range $k,$v := .NetworkSettings.Networks}}{{$k}} {{end}}'
  ```
- **Volumes:** confira com `docker volume ls | grep <projeto>`. Inclua os volumes
  nomeados no backup do servidor; o dump do Postgres é a cópia consistente do banco.

## Atualizar para uma nova versão do Dify

Faça num clone com `origin` = este repositório e `upstream` = `langgenius/dify`:

```bash
git switch easypanel
docker/easypanel/update.sh 1.18.0          # rebase sobre a tag + regenera + valida
# leia as release notes de todas as versões intermediárias
git push --force-with-lease origin easypanel && git push origin easypanel-1.18.0
```

Depois clique em **Deploy** no Easypanel. O `update.sh` aborta se:
- a árvore tiver mudanças;
- a tag não existir;
- a branch alterar algum arquivo do upstream.

A cada versão publicada fica uma tag `easypanel-<versão>`.

**Rollback:** aponte a branch para a tag anterior e faça o deploy de novo:

```bash
git push --force-with-lease origin refs/tags/easypanel-1.17.1:refs/heads/easypanel
```

Se a versão nova já rodou migrations, restaure também o dump do banco. As migrations
do Dify não se revertem sozinhas.

## Regras

- Não edite arquivos do upstream nesta branch. Ajustes vão no `generate.py`.
- Não commite `.env`. Ele já está no `.gitignore` oficial; os secrets ficam só no
  Easypanel.
- O push para `upstream` está desativado neste clone (`pushurl = DISABLED`).
