# 🔀 Git Flow: Branching Strategy

## Overview

Seguim **Git Flow** (Agile branching model) per a gestió de versió i desenvolupament continu.

```
main (v1.0, v1.1...)      ← PRODUCCIÓ (estable)
  ↑
  ├─ release/v1.0-rc1     ← Preparació de releases
  │
  └─ develop              ← INTEGRACIÓ (principal development)
      ├─ feature/xyz      ← Noves funcionalitats
      └─ hotfix/bug-123   ← Correccions crítiques
```

---

## Branques Permanents

### **main**
- **Source**: Merge de `release/` o `hotfix/`
- **Protecció**: ✅ Require PR + approvals
- **Tags**: Versionat (v1.0.0, v1.1.0...)
- **Política**: `git merge --no-ff` per mantenir històric de merge

Exemple:
```bash
git checkout main
git merge --no-ff release/v1.0.0
git tag -a v1.0.0
```

### **develop**
- **Source**: Merge de `feature/` branches
- **Protecció**: Require PR + approvals
- **Deployment**: Auto-deploy a entorn de staging
- **Política**: `git merge --no-ff` per claritat

Exemple:
```bash
git checkout develop
git merge --no-ff feature/random-sampling-unbiased
```

---

## Branques Temporals

### **feature/\***
- **Origen**: Branch des de `develop`
- **Naming**: `feature/descriptive-name` o `feature/TASK-123-description`
- **Merger**: PR a `develop`, revisat per otro developer
- **Cleanup**: Eliminar després de merge

Flux complet:
```bash
git checkout develop
git pull origin develop
git checkout -b feature/random-sampling-unbiased

# ... desenvolupar ...

git add .
git commit -m "feat(sampling): implement unbiased algorithm"
git push origin feature/random-sampling-unbiased

# Fer PR a GitHub → Review → Merge a develop
# Eliminar branca:
git branch -d feature/random-sampling-unbiased
git push origin --delete feature/random-sampling-unbiased
```

### **release/\***
- **Origen**: Branch des de `develop`
- **Naming**: `release/v1.0.0` o `release/vX.Y.Z`
- **Merger**: PR a `main` + merge back a `develop`
- **Activitats**: Bump version, fix release-critical bugs, actualitzar CHANGELOG

Flux:
```bash
git checkout develop
git pull origin develop
git checkout -b release/v1.0.0

# Correccions i actualitzacions de versió
echo "version=1.0.0" > setup.cfg
git commit -am "chore(release): bump to v1.0.0"
git push origin release/v1.0.0

# PR a main (per producció) + PR a develop (per sincronitzar)
# Després de merge a main:
git checkout main
git tag -a v1.0.0 -m "Release v1.0.0"
git push origin main --tags
```

### **hotfix/\***
- **Propòsit**: Corregir bugs crítics en producció
- **Origen**: Branch des de `main`
- **Naming**: `hotfix/critical-bug-name` o `hotfix/HOTFIX-123`
- **Merger**: PR a `main` + merge back a `develop`
- **Deployment**: Deploy immediat a producció

Flux:
```bash
git checkout main
git pull origin main
git checkout -b hotfix/critical-memory-leak

# Fix el bug
git commit -am "fix(memory): resolve critical memory leak in sampling"
git push origin hotfix/critical-memory-leak

# Fer 2 PR:
# 1. hotfix → main (producció)
# 2. hotfix → develop (mantenir develop sincronitzat)
```

---

## Versioning & Tags

Usem **Semantic Versioning**: `vMAJOR.MINOR.PATCH`

```
v1.0.0      - Release estable (main)
v1.0.1      - Hotfix (main)
v1.1.0      - Minor feature release (main)
v2.0.0      - Major breaking changes (main)

develop     - Sens versió (pre-release versions es 1.X.0-rc1)
```

Crear tag:
```bash
git tag -a v1.0.0 -m "Release version 1.0.0"
git push origin v1.0.0
```

## Commit Style

Format curt i clar:
```bash
git commit -m "feat: add random sampling"
git commit -m "fix: handle token missing"
git commit -m "docs: update quickstart"
git commit -m "chore: clean ignored outputs"
```

Tipus bàsics:
- `feat`
- `fix`
- `docs`
- `refactor`
- `test`
- `chore`

---

## Workflow

### Acabar nova funcionalitat i mergejar a develop:
```bash
# 1. Create feature
git checkout develop
git pull origin develop
git checkout -b feature/new-awesome-feature

# 2. Develop & test
# ... fer canvis ...

# 3. Commit amb mensatge apropiat
git add .
git commit -m "feat: implement awesome feature"

# 4. Push
git push origin feature/new-awesome-feature

# 5. Crear PR a GitHub (desde web)
#    - Revisar diff
#    - Fer code review
#    - Merge a develop

# 6. Cleanup local
git checkout develop
git pull origin develop
git branch -d feature/new-awesome-feature
```

### Preparar release:
```bash
# 1. Create release
git checkout develop
git pull origin develop
git checkout -b release/v1.2.0

# 2. Actualitzar versió
# ... bump version files ...
git commit -am "chore(release): bump to v1.2.0"

# 3. Push & create PR
git push origin release/v1.2.0

# 4. Merge a main + tag
git checkout main
git merge --no-ff release/v1.2.0
git tag -a v1.2.0 -m "Release v1.2.0"
git push origin main --tags

# 5. Merge back a develop
git checkout develop
git merge --no-ff release/v1.2.0
git push origin develop

# 6. Cleanup
git branch -d release/v1.2.0
git push origin --delete release/v1.2.0
```

### Fix crític en producció:
```bash
# 1. Create hotfix
git checkout main
git checkout -b hotfix/critical-bug-fix

# 2. Fix & test
# ... fix ...
git commit -am "fix(critical): patch memory leak"

# 3. Push & PR
git push origin hotfix/critical-bug-fix

# 4. Merge a main + tag (immediate)
git checkout main
git merge --no-ff hotfix/critical-bug-fix
git tag -a v1.0.1 -m "Hotfix v1.0.1"
git push origin main --tags

# 5. Merge back a develop
git checkout develop
git merge --no-ff hotfix/critical-bug-fix
git push origin develop

# 6. Cleanup
git branch -d hotfix/critical-bug-fix
git push origin --delete hotfix/critical-bug-fix
```
