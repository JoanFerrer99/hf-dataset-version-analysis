// Targetes de xifres clau. Cada una pot portar a una pàgina: el botó envia la pàgina
// a Python (setTriggerValue("open", id)).
export default function (component) {
  const { data, parentElement, setTriggerValue } = component
  const root = parentElement.querySelector("[data-root]")
  if (!root) return

  const grid = document.createElement("div")
  grid.className = "grid grid-cols-1 gap-4 font-sans sm:grid-cols-2 lg:grid-cols-4"
  for (const card of data?.cards ?? []) {
    const item = document.createElement("section")
    item.className = "flex flex-col justify-between gap-3 rounded-card border border-line bg-panel p-5"
    const label = document.createElement("p")
    label.className = "text-sm text-muted"
    label.textContent = card.label
    const value = document.createElement("p")
    value.className = "text-3xl font-semibold tracking-tight text-heading"
    value.textContent = card.value
    const hint = document.createElement("p")
    hint.className = "text-xs text-muted"
    hint.textContent = card.hint ?? ""
    const body = document.createElement("div")
    body.append(label, value, hint)
    item.appendChild(body)
    if (card.target) {
      const open = document.createElement("button")
      open.type = "button"
      open.dataset.target = card.target
      open.className =
        "self-start cursor-pointer rounded-md text-sm font-medium text-accent hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
      open.textContent = `${card.action ?? "Veure detalls"} →`
      open.onclick = () => setTriggerValue("open", card.target)
      item.appendChild(open)
    }
    grid.appendChild(item)
  }
  root.replaceChildren(grid)
}
