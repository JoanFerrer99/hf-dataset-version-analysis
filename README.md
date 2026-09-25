# HF Dataset Version Analysis

Aquest treball té com a objectiu analitzar com canvien els datasets allotjats al repositori de codi obert Hugging Face entre les seves versions successives. Per assolir aquest objectiu, es dissenyarà i implementarà un pipeline automatitzat que, mitjançant l'API pública de HF, permeti identificar els datasets amb múltiples versions, extreure'n les diferències rellevants entre versions consecutives i classificar el tipus de canvi produït.

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

## Executar sense Docker

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
echo "HF_TOKEN=hf_el_teu_token_aqui" > .env
python notebooks/run_pipeline.py --sample-size 2000 --threads 4 --seed 42 # execucio principal
# Resultats a data/eligibility_report_*.csv, data/versions_*.csv, data/change_classification_*.csv
```

## Quickstart

```bash
source venv/bin/activate
python notebooks/run_pipeline.py --sample-size 50 --threads 4 --seed 42 --max-scanned 5000  # prova rapida
python notebooks/run_pipeline.py --sample-size 2000 --threads 4 --seed 42                    # execucio principal
```

`run_pipeline.py` és l'orquestrador: encadena mostreig+elegibilitat
(`eligibility_scan.py`, Fase 0-1), extracció de versions
(`version_extractor.py`, Fase 1b) i classificació de canvis dels elegibles
(Fase 2) en un sol comandament, reutilitzant el mateix CSV entre fases --
sense pas manual d'un run a l'altre. `--skip-version-extraction`/
`--skip-classification` ometen una fase concreta; `--input-csv <csv>` salta
el mostreig i reutilitza un CSV d'un run previ.

### Scripts individuals

Per a proves o depuració d'una sola fase, cada script també s'invoca per
separat:

```bash
python notebooks/eligibility_scan.py --sample-size 50 --threads 4 --seed 42  # només Fase 0-1
python notebooks/version_extractor.py --input data/eligibility_report_<sample_size>_<run_id>.csv  # només Fase 1b
python notebooks/eligibility_scan.py --classify-eligible data/eligibility_report_<sample_size>_<run_id>.csv  # només Fase 2
```

## Ús amb Docker

Alternativa a l'entorn virtual local: no cal instal·lar Python ni les
dependències, només Docker. Cal el mateix fitxer `.env` amb `HF_TOKEN`
descrit més amunt. Si el teu usuari no és al grup `docker` del sistema,
anteposa `sudo` a totes les comandes següents (`sudo docker compose ...`).

```bash
docker compose build

# Pipeline complet en un sol comandament (Fase 0-1 + 1b + 2, mateix CSV
# encadenat entre fases -- vegeu Quickstart més amunt):
docker compose run --rm --remove-orphans run-pipeline --sample-size 50 --threads 4 --seed 42 --max-scanned 5000
ls data/eligibility_report_50_*.csv         # CSV d'elegibilitat (nom exacte inclou el run_id)
ls data/versions_*.csv                      # CSV de versions
ls data/change_classification_*.csv         # CSV de canvis classificats (nomes si hi ha elegibles)
```

`--remove-orphans` neteja contenidors aturats d'execucions anteriors amb
`docker compose run` (cadascuna en crea un de nou, amb un nom únic tipus
`..._run_<hash>`, que no s'esborra sol) -- evita l'avís "Found orphan
containers" a cada crida, no és obligatori per al funcionament.

**Important -- torna a fer `docker compose build` sempre que canviï el
codi a `notebooks/`** (per exemple, en afegir `version_extractor.py`):
`docker compose run` NO reconstrueix la imatge automàticament, així que
reutilitza la que ja tenia en caché. Si veus un error tipus `python: can't
open file '/app/notebooks/<script>.py': No such file or directory`, és
exactament això -- la imatge és anterior a aquell fitxer; `docker compose
build` (o `docker compose run --build ...`) ho arregla.

`data/` es munta com a volum (`./data:/app/data`), així que els CSV/JSON de
sortida apareixen directament al repositori de l'host, igual que executant
els scripts en local. Els scripts individuals **necessiten que la Fase 0-1
s'hagi executat abans**: llegeixen el CSV que aquesta genera, no en creen
cap de nou. Sense `docker compose`, l'equivalent amb `docker run` (l'imatge
usa `run_pipeline.py` com a entrypoint per defecte; sobreescriu-lo per a un
script individual):

## Variables utils

- `--sample-size`: mida de la mostra
- `--threads`: processament en paral·lel
- `--max-scanned`: limit opcional nomes per proves rapides
- `--seed`: mostra reproduible
- `--skip-version-extraction` / `--skip-classification` (`run_pipeline.py`): ometen una fase concreta
- `--input-csv` (`run_pipeline.py`): salta el mostreig, reutilitza un CSV d'un run previ