#!/usr/bin/env bash
# Aplica a GitHub les regles de protecció de branca descrites a
# docs/GIT_FLOW.md per a `main` i `develop`:
#   - Require PR abans de mergear (no push directe)
#   - Require que el check de CI ("Lint & tests") passi en verd
#   - Prohibir force-push i esborrat de la branca
#
# Requereix `gh` (GitHub CLI) autenticat amb permisos d'admin sobre el repo:
#   gh auth login
#
# Ús:
#   ./scripts/setup_branch_protection.sh           # 1 review requerida (per defecte)
#   REQUIRED_APPROVALS=0 ./scripts/setup_branch_protection.sh   # repo mantingut en solitari

set -euo pipefail

if ! command -v gh &>/dev/null; then
    echo "Error: 'gh' (GitHub CLI) no està instal·lat. Vegeu https://cli.github.com/" >&2
    exit 1
fi

REPO=$(gh repo view --json nameWithOwner -q .nameWithOwner)
CI_CHECK_NAME="${CI_CHECK_NAME:-Lint & tests}"

protect_branch() {
    local branch="$1"
    echo "Configurant protecció per a '${branch}' a ${REPO}..."
    gh api \
        --method PUT \
        -H "Accept: application/vnd.github+json" \
        "repos/${REPO}/branches/${branch}/protection" \
        -f "required_status_checks[strict]=true" \
        -f "required_status_checks[contexts][]=${CI_CHECK_NAME}" \
        -F "enforce_admins=false" \
        -F "required_pull_request_reviews[required_approving_review_count]=${REQUIRED_APPROVALS}" \
        -F "required_pull_request_reviews[dismiss_stale_reviews]=true" \
        -F "restrictions=null" \
        -F "allow_force_pushes=false" \
        -F "allow_deletions=false" \
        -F "required_linear_history=false"
}

protect_branch "main"
protect_branch "develop"

echo "Fet. Revisa a https://github.com/${REPO}/settings/branches"
