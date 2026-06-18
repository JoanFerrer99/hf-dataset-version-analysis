from huggingface_hub import HfApi, get_repo_discussions, list_repo_refs
from dotenv import load_dotenv
import os
import json

load_dotenv()
api = HfApi(token=os.getenv("HF_TOKEN"))

# 1. QUINS CAMPS RETORNA list_datasets()?
print("=" * 80)
print("1. CAMPS RETORNATS PER list_datasets():")
print("=" * 80)
datasets = list(api.list_datasets(limit=1))
dataset = datasets[0]
print(f"\nTipus: {type(dataset)}")
print(f"\nCamps disponibles:")
for field in dir(dataset):
    if not field.startswith('_'):
        try:
            value = getattr(dataset, field)
            if not callable(value):
                print(f"  - {field}: {type(value).__name__}")
        except:
            pass

print(f"\nValors del primer dataset:")
print(f"  id: {dataset.id}")
print(f"  author: {dataset.author}")
print(f"  created_at: {dataset.created_at}")
print(f"  last_modified: {dataset.last_modified}")
print(f"  downloads: {dataset.downloads}")
print(f"  likes: {dataset.likes}")
print(f"  tags: {dataset.tags}")
print(f"  sha: {dataset.sha}")
print(f"  gated: {dataset.gated}")
print(f"  private: {dataset.private}")

# 2. HI HA VERSIONING EXPLÍCIT O CAL INFERIR-LO DELS TAGS DE GIT?
print("\n" + "=" * 80)
print("2. VERSIONING - TAGS DE GIT I REFS:")
print("=" * 80)
try:
    # Accedir als refs (branques, tags) del dataset
    dataset_id = dataset.id
    refs = list_repo_refs(repo_id=dataset_id, repo_type="dataset", token=os.getenv("HF_TOKEN"))
    print(f"\nRefs del dataset '{dataset_id}':")
    print(f"  Branches: {refs.branches}")
    print(f"  Tags: {refs.tags}")
    print(f"  Pull requests: {refs.pull_requests}")
except Exception as e:
    print(f"  Error obtenint refs: {e}")

# 3. HISTORIAL DE COMMITS
print("\n" + "=" * 80)
print("3. HISTORIAL DE COMMITS:")
print("=" * 80)
try:
    from huggingface_hub import list_repo_commits
    commit_history = list_repo_commits(
        repo_id=dataset_id,
        repo_type="dataset",
        token=os.getenv("HF_TOKEN")
    )
    print(f"\n  Últims commits:")
    for i, commit in enumerate(commit_history):
        if i < 3:  # Mostrar els 3 primers
            print(f"    [{i+1}] Commit: {commit.commit_id}")
            print(f"        Data: {commit.created_at}")
            print(f"        Autors: {commit.authors}")
            print(f"        Títol: {commit.title if commit.title else '(sense títol)'}")
            print()
        else:
            print(f"    ... (total: {sum(1 for _ in list_repo_commits(repo_id=dataset_id, repo_type='dataset', token=os.getenv('HF_TOKEN')))} commits)")
            break
    print(f"\n  Com accedir a l'historial:")
    print(f"    - API: list_repo_commits(repo_id, repo_type='dataset')")
    print(f"    - Cada commit: commit_id (SHA), created_at, authors, title, message")
    print(f"    - No hi ha versioning semàntic, s'usa el commit SHA com a versió")
    
except Exception as e:
    print(f"  Error: {type(e).__name__}: {e}")

# 4. DIFERÈNCIA ENTRE CARD I FITXERS REALS
print("\n" + "=" * 80)
print("4. DIFERÈNCIA ENTRE CARD DEL DATASET I FITXERS REALS:")
print("=" * 80)
try:
    # Informació de la card
    print(f"\nInformació de la CARD (dataset metadata):")
    print(f"  description (primera 100 chars): {str(dataset.description)[:100] if dataset.description else 'None'}...")
    print(f"  card_data: {dataset.card_data}")
    print(f"  citation: {dataset.citation}")
    print(f"  tags: {dataset.tags}")
    
    # Fitxers reals
    print(f"\nFitxers REALS del repositori:")
    tree = api.list_repo_tree(
        repo_id=dataset_id,
        repo_type="dataset",
        token=os.getenv("HF_TOKEN"),
        recursive=False
    )
    file_count = 0
    folder_count = 0
    for item in tree:
        if hasattr(item, 'path'):
            if '.' in item.path:  # És un fitxer
                print(f"  - [FITXER] {item.path}")
                file_count += 1
            else:  # Probablement carpeta
                print(f"  - [CARPETA] {item.path}")
                folder_count += 1
            if file_count + folder_count >= 15:
                print(f"  ... i més elements")
                break
    
    print(f"\n  Diferències clau:")
    print(f"    ✓ CARD: Metadades, descripció, cites, llicència")
    print(f"    ✓ FITXERS REALS: Parquet, CSV, JSON, arxius binaris")
    print(f"    ✓ main_size = {dataset.main_size} (None = cal calcular-ho)")
    print(f"    ✓ used_storage = {dataset.used_storage} (None = no disponible)")
    print(f"    ✓ SHA del commit: {dataset.sha} (versió actual)")
    
except Exception as e:
    print(f"  Error: {type(e).__name__}: {e}")