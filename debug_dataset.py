#!/usr/bin/env python
"""Verifica manualmente un dataset per debugar commits/tags"""
import os
from dotenv import load_dotenv
from huggingface_hub import list_repo_refs, list_repo_commits

# Carrega token
load_dotenv()
token = os.getenv("HF_TOKEN")

dataset_id = "allenai/c4"
print(f"📋 Analitzant: {dataset_id}\n")

# Refs
try:
    refs = list_repo_refs(repo_id=dataset_id, repo_type="dataset", token=token)
    print(f"🏷️  Tags: {len(refs.tags) if refs.tags else 0}")
    if refs.tags:
        for tag in list(refs.tags)[:5]:
            print(f"   - {tag.ref}")
except Exception as e:
    print(f"❌ Error refs: {e}")

# Commits (NOTA: list_repo_commits retorna un generador, no es parámetro max_items)
try:
    commits = []
    for commit in list_repo_commits(
        repo_id=dataset_id, 
        repo_type="dataset", 
        token=token
    ):
        commits.append(commit)
        if len(commits) >= 50:  # Limit manual
            break
    
    print(f"\n📝 Commits (totals fetched: {len(commits)}):")
    print(f"   Commit object type: {type(commits[0])}")
    print(f"   Commit object fields: {dir(commits[0])}\n")
    
    for i, c in enumerate(commits[:10], 1):
        # Probar diferentes atributos
        title = getattr(c, "title", None) or getattr(c, "message", None) or "(no title)"
        commit_id = getattr(c, "commit_id", "?")[:12]
        created = getattr(c, "created_at", "?")
        print(f"   {i}. {str(title)[:60]:<60}")
        print(f"      {commit_id} - {created}")
except Exception as e:
    print(f"❌ Error commits: {e}")
