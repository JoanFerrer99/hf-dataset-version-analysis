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
python notebooks/eligibility_scan.py --sample-size 50 --threads 4 --seed 42
python notebooks/eligibility_scan.py --sample-size 1000 --threads 8 --seed 42
```

Per estimacio principal, no passis `--max-scanned` (escaneig complet de la poblacio disponible).

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
