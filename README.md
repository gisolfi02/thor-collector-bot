# Thor Collector Bot

Bot Discord multiserver da collezione, ispirato al flusso di Cat Bot. Pubblica periodicamente una foto nel canale configurato; il primo messaggio nuovo che contiene **esattamente** `thor` (ignorando maiuscole/minuscole e spazi esterni) assegna la foto all'autore.

Il progetto usa Python 3.12, `discord.py` 2.x, slash command, SQLite asincrono con `aiosqlite`, test automatici, Docker e Docker Compose.

> **Copyright:** il repository include soltanto immagini segnaposto create per il progetto. Aggiungi esclusivamente immagini che possiedi o per le quali disponi di una licenza adeguata.

## Caratteristiche

- configurazione separata per ogni server Discord;
- amministratore del gioco persistente e distinto dagli amministratori Discord;
- scheduler indipendente per server;
- una sola foto attiva per server;
- cattura atomica protetta da lock per server e transazione SQLite;
- collezioni con quantità di copie;
- classifica con spareggi deterministici;
- paginazione tramite pulsanti;
- conferma irreversibile per `/destroy`;
- ripristino dei task e degli spawn dopo riavvio;
- database persistente in volume Docker;
- logging JSON senza token o contenuti generici delle chat;
- healthcheck locale basato su heartbeat.

## Architettura

La logica è separata in quattro livelli:

1. **Cog Discord**: validazione dell'interazione, slash command, embed e pulsanti.
2. **Servizi applicativi**: cattura atomica, catalogo e scheduler.
3. **Repository**: query dedicate a configurazioni, spawn, collezioni e classifica.
4. **Database**: connessione `aiosqlite`, migrazioni incrementali e transazioni serializzate.

`GuildLockRegistry` fornisce lo stesso `asyncio.Lock` a cattura e scheduler. Dopo il lock, `CaptureService` rilegge lo spawn in database ed esegue:

```sql
UPDATE spawns
SET status = 'CAPTURED', ...
WHERE spawn_id = ? AND status = 'ACTIVE';
```

Solo l'operazione con `rowcount = 1` prosegue con inserimento della cattura, incremento della quantità e calcolo del punteggio. L'indice parziale SQLite impedisce inoltre più righe `ACTIVE` per lo stesso server.

## Comandi

| Comando | Accesso | Descrizione |
|---|---|---|
| `/start` | prima volta: tutti; dopo: amministratore del gioco | Avvia o sposta il gioco nel canale corrente. |
| `/leadersboard` | tutti | Classifica richiesta, con il nome volutamente non corretto. |
| `/leaderboard` | tutti | Alias corretto della stessa classifica. |
| `/changetime min_minutes max_minutes` | amministratore del gioco | Imposta intervallo casuale da 1 a 10.080 minuti. |
| `/collection [user]` | tutti | Mostra la propria collezione o quella di un altro membro. |
| `/destroy` | amministratore del gioco | Elimina, dopo conferma, tutti i dati del solo server corrente. |

### Messaggi validi per la cattura

Validi:

```text
thor
THOR
  ThOr  
```

Non validi:

```text
thor!
io catturo thor
thor thor
thorr
```

Sono ignorati anche messaggi di bot/webhook, risposte, messaggi modificati, messaggi precedenti allo spawn e messaggi in altri canali.

## Esempio dello spawn

```text
⚡ Un nuovo Thor è apparso!

Thor Segnaposto Classico
Immagine segnaposto: sostituiscila con un'immagine posseduta legittimamente.

Nome: Thor Segnaposto Classico
Rarità: Comune
Come catturarlo: Scrivi "thor" per catturarlo!
ID foto: thor_001
```

## Esempio della cattura

```text
⚡ @utente ha effettuato la cattura!

@utente ha catturato Thor Segnaposto Classico!
Rarità: Comune
Catture totali: 7
Copie di questa foto: 2
Tempo di cattura: 1.284 s
```

## Requisiti

Per sviluppo locale:

- Python 3.12 o compatibile;
- Git;
- un'applicazione Discord con bot;
- Message Content Intent abilitato.

Per Docker:

- Docker Engine;
- Docker Compose plugin (`docker compose`).

## Creazione del bot Discord

1. Apri il [Discord Developer Portal](https://discord.com/developers/applications).
2. Seleziona **New Application** e assegna un nome.
3. Apri la sezione **Bot** e crea il bot.
4. Genera o reimposta il token e salvalo soltanto nel file `.env`.
5. Nella sezione **Privileged Gateway Intents**, abilita **Message Content Intent**.
6. Apri **OAuth2 → URL Generator**.
7. Seleziona gli scope:
   - `bot`;
   - `applications.commands`.
8. Concedi al bot soltanto i permessi necessari:
   - View Channels;
   - Send Messages;
   - Embed Links;
   - Attach Files;
   - Read Message History.
9. Apri il link generato e invita il bot nel server.

Il progetto non richiede il permesso Discord `Administrator`.

Documentazione ufficiale:

- [Application Commands](https://discord.com/developers/docs/interactions/application-commands)
- [Gateway Intents](https://discord.com/developers/docs/events/gateway#gateway-intents)

## Configurazione

Copia il file di esempio:

### Linux/macOS

```bash
cp .env.example .env
```

### Windows PowerShell

```powershell
Copy-Item .env.example .env
```

Configura almeno:

```env
DISCORD_TOKEN=incolla_il_token_senza_virgolette
DATABASE_PATH=./data/thor_bot.sqlite3
LOG_LEVEL=INFO
DEFAULT_MIN_SPAWN_MINUTES=30
DEFAULT_MAX_SPAWN_MINUTES=90
ALLOW_GUILD_OWNER_RECOVERY=false
TEST_GUILD_ID=
COLLECTIBLES_JSON=./assets/collectibles.json
COLLECTIBLES_DIR=./assets/collectibles
HEALTH_FILE=./data/health
```

Quando usi Docker, puoi lasciare i percorsi presenti in `.env.example`:

```env
DATABASE_PATH=/data/thor_bot.sqlite3
COLLECTIBLES_JSON=/app/assets/collectibles.json
COLLECTIBLES_DIR=/app/assets/collectibles
HEALTH_FILE=/tmp/thor-bot-health
```

### `TEST_GUILD_ID`

Durante lo sviluppo inserisci l'ID del server di test. Il bot copierà e sincronizzerà subito i comandi globali in quel server.

Per ottenere un ID Discord, abilita **Modalità sviluppatore** nelle impostazioni Discord, fai clic destro sul server e seleziona **Copia ID server**.

In produzione lascia vuoto `TEST_GUILD_ID`. I comandi saranno sincronizzati globalmente; la propagazione globale può richiedere tempo.

### Recupero dell'amministratore del gioco

Per impostazione predefinita:

```env
ALLOW_GUILD_OWNER_RECOVERY=false
```

Se l'amministratore del gioco ha lasciato il server, il proprietario Discord può temporaneamente impostare:

```env
ALLOW_GUILD_OWNER_RECOVERY=true
```

Dopo il riavvio, il proprietario può eseguire `/start` e diventare amministratore del gioco **soltanto se il vecchio amministratore non è più presente nel server**. Riporta poi la variabile a `false` e riavvia il container.

## Configurazione delle immagini

Inserisci le immagini in:

```text
assets/collectibles/
```

Modifica:

```text
assets/collectibles.json
```

Formato:

```json
[
  {
    "id": "thor_001",
    "name": "Thor Classico",
    "filename": "thor_001.jpg",
    "caption": "Un nuovo Thor è apparso!",
    "rarity": "Comune",
    "description": "Descrizione facoltativa.",
    "enabled": true
  }
]
```

Regole:

- `id` deve essere univoco e stabile;
- `filename` deve contenere soltanto il nome del file, senza directory;
- il file deve esistere nella cartella delle immagini;
- `enabled` è opzionale e predefinito a `true`;
- gli elementi rimossi dal JSON vengono disabilitati nel catalogo SQLite, non eliminati dallo storico;
- uno stesso utente può catturare più copie dello stesso `id`.

### Rarità

Le rarità sono stringhe configurabili direttamente nel JSON. I valori suggeriti sono:

- Comune;
- Non comune;
- Raro;
- Epico;
- Leggendario.

Puoi aggiungere altre rarità senza migrare il database. L'ordinamento visivo predefinito assegna priorità alle cinque rarità suggerite e colloca le altre dopo di esse.

## Installazione locale

### Linux/macOS

```bash
git clone <URL_DEL_TUO_REPOSITORY>
cd thor-collector-bot
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.lock
cp .env.example .env
```

Modifica `.env`, poi avvia:

```bash
python -m app.main
```

### Windows PowerShell

```powershell
git clone <URL_DEL_TUO_REPOSITORY>
Set-Location thor-collector-bot
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.lock
Copy-Item .env.example .env
python -m app.main
```

## Test automatici

I test non aprono connessioni reali a Discord.

```bash
python -m pytest -q
```

I test coprono normalizzazione, canale errato, bot, assenza dello spawn, messaggi precedenti allo spawn, concorrenza, incremento singolo, copie, intervalli, autorizzazioni, eliminazione isolata, amministratore iniziale, vincolo di unicità dello spawn, task duplicati, spareggi, paginazione e immagini mancanti.

Il workflow `.github/workflows/tests.yml` esegue automaticamente compilazione e test su Python 3.12 per ogni push e pull request.

## Avvio con Docker

1. Crea `.env`:

```bash
cp .env.example .env
```

2. Inserisci il token.
3. Compila e avvia:

```bash
docker compose up -d --build
```

4. Controlla stato e log:

```bash
docker compose ps
docker compose logs -f --tail=200 thor-bot
```

5. Arresta senza cancellare il volume:

```bash
docker compose down
```

Non usare `docker compose down -v` se vuoi conservare il database.

## Persistenza e riavvio

Il volume nominato `thor-collector-data` conserva `/data/thor_bot.sqlite3` anche dopo ricreazione del container.

All'avvio il bot:

1. applica soltanto le migrazioni non ancora registrate;
2. sincronizza il catalogo JSON;
3. carica i server attivi;
4. verifica l'eventuale spawn `ACTIVE`;
5. tenta di recuperare canale e messaggio;
6. mantiene la cattura se il messaggio esiste;
7. invalida lo spawn se messaggio o canale non esistono;
8. crea un solo task di attesa per ogni server senza spawn attivo.

Se il bot viene rimosso da un server, quel gioco viene disattivato ma i dati restano disponibili in caso di reinvito. `/destroy`, invece, elimina i dati del server in modo irreversibile.

## Database e migrazioni

Tabelle principali:

- `guild_configs`: canale, amministratore, stato e intervallo per server;
- `collectibles`: catalogo sincronizzato dal JSON;
- `spawns`: storico e stato degli spawn;
- `captures`: una riga per cattura riuscita;
- `user_collections`: quantità aggregate per utente e foto;
- `schema_migrations`: versioni già applicate.

Le migrazioni sono file SQL numerati in `migrations/`. Per aggiungerne una:

1. crea, per esempio, `003_nome_modifica.sql`;
2. usa istruzioni compatibili con dati esistenti;
3. non modificare una migrazione già pubblicata;
4. riavvia il bot.

Il database non viene mai eliminato automaticamente per un cambio di schema.

## Backup e ripristino

### Backup coerente con container in esecuzione

SQLite in modalità WAL è robusto, ma il metodo più semplice e sicuro è fermare brevemente il container:

```bash
docker compose stop thor-bot
mkdir -p backups
docker run --rm \
  -v thor-collector-data:/data:ro \
  -v "$PWD/backups:/backup" \
  alpine sh -c 'cp /data/thor_bot.sqlite3 /backup/thor_bot-$(date +%Y%m%d-%H%M%S).sqlite3'
docker compose start thor-bot
```

### Ripristino

```bash
docker compose stop thor-bot
docker run --rm \
  -v thor-collector-data:/data \
  -v "$PWD/backups:/backup:ro" \
  alpine sh -c 'cp /backup/NOME_BACKUP.sqlite3 /data/thor_bot.sqlite3 && rm -f /data/thor_bot.sqlite3-wal /data/thor_bot.sqlite3-shm'
docker compose start thor-bot
```

Verifica sempre il nome del backup prima di eseguire il ripristino.

## Deployment su Oracle Cloud Infrastructure Always Free

> Le risorse gratuite, la capacità disponibile e le condizioni commerciali possono cambiare. Nessun hosting gratuito garantisce disponibilità assoluta o permanente. Oracle documenta inoltre la possibile riacquisizione di istanze Always Free considerate inattive. Controlla sempre la documentazione aggiornata.

### 1. Crea la VM

1. Crea o accedi a un account OCI.
2. Scegli la **home region** con attenzione: molte risorse Always Free devono risiedere lì.
3. Apri **Compute → Instances → Create instance**.
4. Usa Ubuntu 24.04 LTS o una versione Ubuntu supportata.
5. Scegli una shape contrassegnata **Always Free eligible**, quando disponibile:
   - AMD `VM.Standard.E2.1.Micro`;
   - ARM `VM.Standard.A1.Flex`.
6. Assegna una chiave SSH pubblica.
7. Crea la VM e annota l'indirizzo IP pubblico.

Il progetto usa soltanto pacchetti Python puri o multipiattaforma e l'immagine `python:3.12-slim`, quindi funziona sia su `amd64` sia su `arm64`.

Documentazione OCI: [Always Free Resources](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm)

### 2. Collegati via SSH

```bash
ssh -i ~/.ssh/chiave_privata ubuntu@IP_PUBBLICO
```

Su Windows puoi usare PowerShell/OpenSSH con il percorso corretto della chiave.

### 3. Aggiorna il sistema

```bash
sudo apt update
sudo apt upgrade -y
sudo apt install -y git ca-certificates curl
```

### 4. Installa Docker dal repository ufficiale

```bash
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc

sudo tee /etc/apt/sources.list.d/docker.sources > /dev/null <<EOF_DOCKER
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: $(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}")
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/docker.asc
EOF_DOCKER

sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo systemctl enable --now docker
sudo usermod -aG docker "$USER"
```

Esci e rientra via SSH, poi verifica:

```bash
docker version
docker compose version
```

Documentazione ufficiale: [Install Docker Engine on Ubuntu](https://docs.docker.com/engine/install/ubuntu/)

### 5. Clona e configura

```bash
git clone <URL_DEL_TUO_REPOSITORY>
cd thor-collector-bot
cp .env.example .env
nano .env
```

Inserisci il token e lascia i percorsi Docker `/data` e `/app/assets`.

Proteggi il file:

```bash
chmod 600 .env
```

### 6. Avvia

```bash
docker compose up -d --build
docker compose ps
docker compose logs --tail=200 thor-bot
```

Con `restart: unless-stopped` e Docker abilitato tramite systemd, il container riparte dopo il riavvio della VM.

Verifica:

```bash
sudo reboot
```

Dopo la riconnessione:

```bash
docker compose ps
docker inspect --format='{{.State.Health.Status}}' thor-collector-bot
docker compose logs --tail=100 thor-bot
```

### 7. Aggiornamento

```bash
cd ~/thor-collector-bot
git pull --ff-only
docker compose up -d --build
docker image prune -f
```

Il volume del database non viene ricreato.

### 8. Prevenzione della perdita dati

- non usare `docker compose down -v`;
- non eliminare il volume `thor-collector-data`;
- esegui backup periodici fuori dalla VM;
- conserva una copia cifrata del database in una destinazione distinta;
- effettua il backup prima di aggiornamenti importanti;
- controlla spazio disco con `df -h`;
- la rotazione dei log Docker è già limitata a tre file da 10 MB.

## Sicurezza

- il token è letto esclusivamente da `DISCORD_TOKEN`;
- `.env` è escluso da Git e dal build context Docker;
- il Dockerfile usa un utente non root;
- le query usano parametri SQLite;
- il bot non registra il contenuto generale dei messaggi;
- non usa `@everyone` o `@here`;
- i nomi vengono sottoposti a escaping Markdown dove mostrati;
- i pulsanti sono vincolati all'utente richiedente;
- il recupero del proprietario è disabilitato di default.

Se un token viene pubblicato accidentalmente, rigeneralo immediatamente nel Developer Portal e aggiorna `.env`.

## Troubleshooting

### Il bot è offline

```bash
docker compose ps
docker compose logs --tail=200 thor-bot
```

Controlla token, accesso Internet, stato della VM e healthcheck. Un token assente o non valido arresta il processo con un messaggio esplicito.

### Gli slash command non sono visibili

- verifica lo scope OAuth2 `applications.commands`;
- reinvita il bot se lo scope mancava;
- durante lo sviluppo usa `TEST_GUILD_ID`;
- i comandi globali possono richiedere tempo per propagarsi;
- controlla nei log la voce di sincronizzazione.

### Il bot non riconosce `thor`

- il testo deve essere esattamente `thor`, salvo maiuscole e spazi esterni;
- il messaggio deve essere nel canale configurato;
- deve esistere uno spawn attivo;
- risposte e messaggi modificati sono ignorati;
- controlla Message Content Intent nel portale e nel codice.

### Message Content Intent non abilitato

Apri **Developer Portal → Application → Bot → Privileged Gateway Intents**, abilita **Message Content Intent**, salva e riavvia il bot.

### Token non valido

Rigenera il token nel portale, sostituiscilo in `.env` e riavvia:

```bash
docker compose up -d --force-recreate
```

Non inserire spazi, virgolette o prefissi nel valore.

### Permessi insufficienti

Esegui `/start` nel canale interessato. Il comando elenca precisamente i permessi mancanti. Controlla anche eventuali negazioni specifiche del canale o della categoria.

### Database in sola lettura

Verifica il volume e i permessi:

```bash
docker compose exec thor-bot sh -c 'id && ls -ld /data && ls -l /data'
```

Il container usa UID/GID `10001`. Con il volume nominato Docker, i permessi sono predisposti dal Dockerfile. Un bind mount host può richiedere `chown` appropriato.

### Immagini non trovate

- verifica `filename` nel JSON;
- controlla maiuscole/minuscole su Linux;
- verifica il mount `./assets:/app/assets:ro`;
- controlla i log per `missing_image_count`;
- almeno una voce abilitata deve avere un file esistente.

Il bot salta le immagini mancanti senza arrestare l'intero processo.

### Comandi globali non ancora sincronizzati

Imposta temporaneamente `TEST_GUILD_ID` durante lo sviluppo. Per la produzione rimuovilo e lascia che la sincronizzazione globale completi la propagazione.

### Task di spawn apparentemente fermo

- controlla che il server sia attivo con `/start`;
- verifica se esiste già una foto attiva: finché non viene catturata non ne appare un'altra;
- controlla l'intervallo configurato;
- cerca nei log `Next spawn scheduled`, `Collectible spawned`, `Configured spawn channel is unavailable` e `Bot lost required channel permissions`;
- verifica che l'immagine esista;
- dopo la perdita permanente del canale, riesegui `/start` in un nuovo canale.

### Database temporaneamente bloccato

Il database usa WAL, timeout e brevi retry. Se il problema persiste, verifica che nessun processo esterno mantenga il file aperto e che il filesystem supporti correttamente SQLite.

## Struttura del repository

```text
thor-collector-bot/
├── .github/
│   └── workflows/
│       └── tests.yml
├── app/
│   ├── __init__.py
│   ├── main.py
│   ├── bot.py
│   ├── config.py
│   ├── database.py
│   ├── models.py
│   ├── cogs/
│   │   ├── __init__.py
│   │   ├── game_commands.py
│   │   └── collection_commands.py
│   ├── repositories/
│   │   ├── __init__.py
│   │   ├── guild_repository.py
│   │   ├── spawn_repository.py
│   │   └── collection_repository.py
│   ├── services/
│   │   ├── __init__.py
│   │   ├── lock_registry.py
│   │   ├── spawn_manager.py
│   │   ├── capture_service.py
│   │   └── collectible_service.py
│   └── views/
│       ├── __init__.py
│       ├── destroy_confirmation.py
│       └── collection_pagination.py
├── assets/
│   ├── collectibles/
│   │   ├── .gitkeep
│   │   ├── thor_001_placeholder.png
│   │   └── thor_002_placeholder.png
│   └── collectibles.json
├── data/
│   └── .gitkeep
├── migrations/
│   ├── 001_initial.sql
│   └── 002_message_id_index.sql
├── tests/
│   ├── __init__.py
│   ├── conftest.py
│   ├── test_admin_commands.py
│   ├── test_capture_service.py
│   ├── test_collectible_service.py
│   ├── test_collection_pagination.py
│   ├── test_destroy.py
│   ├── test_leaderboard.py
│   ├── test_message_normalization.py
│   ├── test_permissions.py
│   └── test_spawn_manager.py
├── .dockerignore
├── .env.example
├── .gitignore
├── Dockerfile
├── docker-compose.yml
├── pyproject.toml
├── requirements.lock
├── requirements-dev.lock
├── README.md
└── LICENSE
```

## Licenza

MIT. Le immagini che aggiungi restano soggette alle rispettive licenze e non sono automaticamente coperte dalla licenza del codice.
