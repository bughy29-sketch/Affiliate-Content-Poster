# Pinterest Pin Scheduler

Schelet pentru publicarea programată de pinuri organice prin **Pinterest API v5**, cu suport pentru linkuri de afiliere eMAG/Profitshare și Amazon.

Scopul este automatizare *conservatoare*: puține pinuri pe rulare, conținut unic, disclosure de afiliere și backoff la rate limit. Nu înlocuiește review-ul de conformitate — vezi secțiunea [Conformitate](#conformitate).

## Ce include

| Componentă | Rol |
|---|---|
| `.github/workflows/pins.yml` | Rulează zilnic + manual (dry-run implicit) |
| `.github/workflows/ci.yml` | Teste + validare coadă, fără secrete |
| `src/config.py` | Config din variabile de mediu |
| `src/pinterest.py` | Client API v5: refresh token, retry, backoff, 429 |
| `src/queue.py` | Încărcare coadă + stare (dedup) |
| `src/validate.py` | Reguli de conformitate pe fiecare pin |
| `src/main.py` | Orchestrare |
| `scripts/get_refresh_token.py` | Flux OAuth2 local pentru refresh token |
| `data/queue.json` | Coada de conținut |
| `data/state.json` | Ce s-a publicat deja (comis automat de workflow) |

## Pornire rapidă

### 0. Publică repo-ul pe GitHub

```bash
git init
git add .
git commit -m "chore: initial scaffold"
git branch -M main
git remote add origin git@github.com:<user>/<repo>.git
git push -u origin main
```

În Settings → Actions → General → Workflow permissions, bifează **Read and write permissions** — workflow-ul commit-ează `data/state.json` ca să evite repostările.

### 1. App Pinterest

În [Pinterest Developers](https://developers.pinterest.com/):

- creează o aplicație;
- adaugă redirect URI `http://localhost:8080/callback`;
- cere scope-urile `pins:write` și `boards:read`;
- notează `client_id` și `client_secret`.

> Accesul standard la API necesită de obicei review. Trial access e limitat la conturi proprii și volume mici.

### 2. Obține refresh token-ul (local)

```bash
pip install -r requirements.txt
python scripts/get_refresh_token.py \
  --client-id "$PINTEREST_CLIENT_ID" \
  --client-secret "$PINTEREST_CLIENT_SECRET"
```

Scriptul deschide browserul, prinde callback-ul pe `localhost:8080` și afișează token-urile. **Nu le commita.**

### 3. Setează secretele în GitHub

Settings → Secrets and variables → Actions:

| Nume | Tip | Obligatoriu |
|---|---|---|
| `PINTEREST_CLIENT_ID` | secret | da |
| `PINTEREST_CLIENT_SECRET` | secret | da |
| `PINTEREST_REFRESH_TOKEN` | secret | da |
| `PINTEREST_BOARD_ID` | variable | nu (poate veni din coadă) |
| `AFFILIATE_DISCLOSURE` | variable | nu |

### 4. Editează coada și testează

Modifică `data/queue.json`, apoi rulează manual workflow-ul **Pinterest Pins** cu `dry_run = true`. Verifică logurile: fiecare pin apare cu descrierea finală și eventualele avertismente.

Când totul e curat, rulează cu `dry_run = false` sau lasă cron-ul să publice.

> Ritmul implicit este conservator: o rulare pe zi, maximum 3 pinuri. Crește `MAX_PINS_PER_RUN` sau frecvența din cron doar după ce contul tolerează volumul.

## Formatul cozii

```json
{
  "pins": [
    {
      "id": "emag-001",
      "board_id": "123456789012345678",
      "title": "Titlu max 100 caractere",
      "description": "Descriere proprie, fără prețuri statice.",
      "link": "https://profitshare.ro/l/...",
      "image_url": "https://cdn.example.com/poza.jpg",
      "alt_text": "Descriere scurtă a imaginii",
      "scheduled_at": "2026-11-07T09:00:00Z",
      "affiliate": "emag",
      "enabled": true
    }
  ]
}
```

| Câmp | Semnificație |
|---|---|
| `id` | Unic; folosit pentru dedup și stare |
| `board_id` | Numeric; fallback la `PINTEREST_BOARD_ID` |
| `scheduled_at` | ISO 8601 UTC; lipsă = eligibil imediat |
| `affiliate` | `emag`, `amazon` sau gol; declanșează disclosure + validări |
| `disclosure` | Opțional; suprascrie textul global |
| `enabled` | `false` = ignorat |

## Import din feed-ul Profitshare

Feed-ul se configurează doar local, în `.env` (cale locală sau URL, inclusiv `file://`):

```env
PROFITSHARE_FEED_URL=file:///C:/Users/Receptie/Downloads/profitshare-feed.xml
```

Comenzi utile:

```bash
# ce categorii există în feed
python scripts/import_profitshare_feed.py --list-categories

# 5 produse, maximum 1 per categorie, doar din categoriile tech
python scripts/import_profitshare_feed.py --limit 5 --max-per-category 1 \
  --include telefoane laptopuri casti monitoare routere mouse

# produse exacte, după codul din feed (ordinea este păstrată)
python scripts/import_profitshare_feed.py --pick X1504MA-BQ212 910-007617

# previzualizare fără a atinge coada reală
python scripts/import_profitshare_feed.py --limit 5 --output data/queue.preview.json
```

Implicit pinurile importate au `enabled: false` și descrierea extrasă din feed
(propoziții întregi, fără prețuri statice). Verifică-le înainte de publicare:
descrierile de magazin sunt uneori repetitive sau vând prea agresiv.

> Feed-ul folosit aici conține produse vândute de **ITGalaxy.ro**, distribuite prin
> Profitshare. Nu scrie „eMAG" în descrieri dacă magazinul real este altul.

## Pinuri Amazon (SUA / EN)

Amazon nu permite scraping și nici folosirea pozelor de produs pe Pinterest, deci
fluxul este semi-manual:

1. Completează `data/amazon.local.txt` (ignorat de git), câte o linie per produs:
   ```
   001 | Logitech MX Master 4 | https://www.amazon.com/dp/...?tag=...
   ```
2. Pune imaginile proprii/licențiate în `images/amazon-001.jpg` … `amazon-005.jpg`
   (JPG/PNG, vertical 2:3, fără prețuri și fără logo-uri de magazin).
3. Verifică: `python scripts/check_amazon_draft.py`.
4. Eu transform sloturile în pinuri cu `enabled: false`, disclosure în engleză și
   `affiliate: amazon`.

Linkurile trebuie să conțină `tag=`; fără scurtătoare terțe (`bit.ly` etc.).

## Variabile de mediu

| Variabilă | Default | Semnificație |
|---|---|---|
| `DRY_RUN` | `true` | Nu publică, doar validează |
| `MAX_PINS_PER_RUN` | `3` | Plafon per rulare |
| `MIN_DELAY_SECONDS` | `30` | Pauză minimă între pinuri |
| `MAX_DELAY_SECONDS` | `90` | Pauză maximă (jitter) |
| `AFFILIATE_DISCLOSURE` | text RO | Adăugat automat la pinurile cu afiliere |
| `QUEUE_PATH` | `data/queue.json` | |
| `STATE_PATH` | `data/state.json` | |

`DRY_RUN=true` nu cere credențiale Pinterest, deci poate rula în CI.

## Reguli de validare

**Blochează publicarea (error):**

- `title` > 100 caractere sau descriere finală > 500;
- link care nu folosește `https://`;
- scurtătoare cunoscute (`bit.ly`, `tinyurl.com`, `cutt.ly`, ...) — risc de cloaking;
- link Amazon fără parametrul `tag`;
- `id` duplicat sau `board_id` lipsă/numeric invalid.

**Avertizează (warning):**

- link eMAG care nu e pe `profitshare.ro`;
- `amzn.to` (link oficial scurt — verifică tag-ul în consola Amazon);
- afiliere fără disclosure.

## Conformitate

### Pinterest

- Doar API v5. Automatizarea interfeței sau scraping-ul încalcă ToS și duce la suspendare.
- Accesul standard la API necesită review; trial access e limitat.
- Fără volume mari, fără același link împins repetat, fără template-uri identice.
- Disclosure vizibil pentru linkuri de afiliere.

### Amazon Associates

- Declară Pinterest ca canal în contul de asociat.
- Tag obligatoriu; fără scurtare/cloaking (`amzn.to` e generat de Amazon, dar verifică tag-ul).
- Nu afișa prețuri statice.
- Statement standard: „As an Amazon Associate I earn from qualifying purchases." Ajustează `disclosure` per pin dacă ai nevoie de formularea exactă.

### eMAG / Profitshare

- Linkuri generate exclusiv în Profitshare, fără modificarea parametrilor de tracking.
- Fără incentivized clicks, cookie stuffing sau spam.
- Disclosure conform regulilor Profitshare și legislației UE.

### GitHub Actions

- Secretele stau doar în GitHub Secrets.
- IP-urile runnerelor sunt partajate și pot fi flagate; la volum mare folosește un VPS cu IP stabil.
- Cron-ul GitHub poate întârzia cu zeci de minute — nu promite ore exacte.

> Politicile și limitele se schimbă. Confirmă în documentația oficială înainte de producție.

## Limitări cunoscute

- Pinterest poate returna un `refresh_token` nou. Logul te avertizează; actualizează secretul manual.
- `data/state.json` e commit-uit de workflow ca să evităm repostări. Dacă branch-ul e protejat, ajustează permisiunile.
- Pinurile invalide rămân în coadă și fac rularea să iasă cu cod 1 până sunt corectate.
- Nu există retry pe erori de validare — doar pe rețea, 429 și 5xx.

## Dezvoltare locală

```bash
pip install -r requirements.txt
cp .env.example .env        # completează valorile local
python -m unittest discover -s tests -v
DRY_RUN=true python -m src.main
```

`.env` este încărcat automat dacă există (prin `python-dotenv`) și nu suprascrie variabilele deja setate. Fișierul e ignorat de git.
