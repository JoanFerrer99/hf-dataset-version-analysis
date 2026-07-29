# HF Dataset Version Analysis

Mostreig aleatori de datasets de Hugging Face per estimar quants tenen 2 o mes versions.

## Configuració

1. Crea i activa l'entorn virtual, i instal·la les dependències:
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```

2. **Genera un token de Hugging Face** (necessari per fer les crides a l'API):
   1. Inicia sessió a [huggingface.co](https://huggingface.co) i ves a
      [Settings → Access Tokens](https://huggingface.co/settings/tokens).
   2. Fes clic a **"New token"**.
   3. Dona-li un nom (p.e. `tfg-dataset-analysis`) i tria el rol **"Read"**
      (n'hi ha prou: aquest pipeline només llegeix metadades públiques/gated
      de repositoris, mai n'escriu res).
   4. Copia el token generat (comença per `hf_...`). Només es mostra un cop.

3. **Desa el token en un fitxer `.env`** a l'arrel del repositori (al mateix
   nivell que `requirements.txt`):
   ```bash
   echo "HF_TOKEN=hf_el_teu_token_aqui" > .env
   ```
   El fitxer `.env` ja està exclòs a `.gitignore`: **no el pugis mai al
   repositori**. Si el token es filtra per error, revoca'l immediatament des
   de la mateixa pàgina de tokens i genera'n un de nou.

   El script falla ràpid amb un missatge clar (`Cap token HF detectat...`) si
   no troba `HF_TOKEN` a l'entorn, així que aquest pas és obligatori abans
   d'executar res.

## Quickstart

```bash
source venv/bin/activate
python notebooks/eligibility_scan.py --sample-size 50 --threads 4 --seed 42 --max-scanned 5000  # prova rapida
python notebooks/eligibility_scan.py --sample-size 2000 --threads 4 --seed 42                    # mostra principal
```

## Ús amb Docker

Alternativa a l'entorn virtual local: no cal instal·lar Python ni les
dependències, només Docker. Cal el mateix fitxer `.env` amb `HF_TOKEN`
descrit més amunt.

```bash
docker compose build

# 1. eligibility_scan.py (prova rapida) -- genera el CSV d'entrada
docker compose run --rm eligibility-scan --sample-size 50 --threads 4 --seed 42 --max-scanned 5000
ls data/eligibility_report_50_*.csv   # confirma el nom exacte (inclou el run_id)

# 2. validate_eligible.py -- usa el CSV generat al pas anterior
docker compose run --rm validate-eligible --input data/eligibility_report_50_<run_id>.csv
```

`data/` es munta com a volum (`./data:/app/data`), així que els CSV/JSON de
sortida apareixen directament al repositori de l'host, igual que executant
els scripts en local. **`validate-eligible` necessita que `eligibility-scan`
s'hagi executat abans**: llegeix un CSV que aquest genera, no en crea cap de
nou. Sense `docker compose`, l'equivalent amb `docker run`:

```bash
docker build -t hf-dataset-version-analysis .
docker run --rm --env-file .env -v "$(pwd)/data:/app/data" \
  hf-dataset-version-analysis --sample-size 50 --threads 4 --seed 42 --max-scanned 5000
```

A cada tag `vX.Y.Z` a `main` (vegeu `docs/GIT_FLOW.md`), la imatge es publica
automàticament a `ghcr.io/joanferrer99/hf-dataset-version-analysis:X.Y.Z`.

Per l'estimació principal, **no passis `--max-scanned`**: la mostra ha
d'escanejar tota la població per no esbiaixar-se (vegeu "Mida de la mostra"
més avall). `--max-scanned` només és per a proves ràpides de desenvolupament.

Classificar exhaustivament tots els datasets (en lloc d'una mostra) **no és
viable sense un pla de pagament de Hugging Face**: als límits de peticions
per segon d'un compte gratuït, classificar els ~950.000 datasets de la
població trigaria hores i xocaria constantment amb rate limiting. Per això
aquest pipeline només implementa el mode de mostreig (`--sample-size`).

## Mida de la mostra i interval de confiança

L'objectiu és estimar, amb un 95% de confiança, la proporció de datasets de
HF que són elegibles (≥2 versions reals). Una execució real i no esbiaixada
(`--sample-size 1000`, sense `--max-scanned`) va donar:

| Mètrica                | Valor          |
|-------------------------|----------------|
| Població escanejada (N) | 949.991        |
| Elegibles                | 13             |
| No elegibles             | 938            |
| Accés restringit (403)   | 49             |
| Errors                   | 0              |
| Proporció elegible (p)   | 0.0137 (1.37%) |

Aquesta p observada és molt més baixa que les proves ràpides amb
`--max-scanned` (~10-17%), perquè `list_datasets()` no retorna els datasets
en ordre aleatori: capar l'escaneig als primers N esbiaixa la mostra. Només
un escaneig complet (sense `--max-scanned`) dona una p fiable.

Amb aquesta p (en lloc de l'assumpció conservadora p=0.5, que sobredimensiona
molt la mostra necessària quan la proporció real és petita), la mida de
mostra necessària per a un marge d'error E amb 95% de confiança és
n = z²·p·(1-p)/E² (z=1.96):

| Marge d'error (E) | n necessària |
|---|---|
| ±1.0 punts percentuals | ~520 |
| ±0.5 punts percentuals | ~2.070 |
| ±0.3 punts percentuals | ~5.730 |

Per això el valor per defecte de `--sample-size` és **2000**: marge d'error
±0.51pp (interval aprox. [0.86%, 1.88%]), doblant la precisió respecte a
n=1000 (±0.72pp) per només el doble de cost de classificació (~2 minuts amb
4 threads). La correcció per població finita és negligible en aquest rang
(fracció de mostreig < 0.6%).

## Criteri d'elegibilitat

Un dataset és **elegible** si té **2 o més versions genuïnes**, detectades per:
- **Tags/refs versionades** (explícites): p.e., `v1.0`, `v2.0`, etc.
- **Commits substantius** (implícits): canvis reals al dataset, sense ser només actualizacions de README o metadata.

## Sortida

- `data/eligibility_report_N_version.csv`
- `data/funnel_summary_N_version.json`

## Variables utils

- `--sample-size`: mida de la mostra
- `--threads`: processament en paral·lel
- `--max-scanned`: limit opcional nomes per proves rapides
- `--seed`: mostra reproduible
