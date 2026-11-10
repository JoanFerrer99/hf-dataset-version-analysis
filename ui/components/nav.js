// Barra de navegació: la marca, una pestanya per pàgina i l'execució. Un clic a una
// pestanya envia la pàgina a Python (setTriggerValue("page", id)), que hi canvia.
export default function (component) {
  const { data, parentElement, setTriggerValue } = component
  const root = parentElement.querySelector("[data-root]")
  if (!root) return

  const bar = document.createElement("nav")
  bar.setAttribute("aria-label", "Pàgines")
  bar.className =
    "flex flex-wrap items-center justify-between gap-3 rounded-card border border-line bg-panel px-4 py-3 font-sans"

  const brand = document.createElement("div")
  brand.className = "flex items-center gap-3"
  const mark = document.createElement("span")
  mark.className = "flex h-8 w-8 items-center justify-center rounded-lg bg-accent text-xs font-bold text-page"
  mark.setAttribute("aria-hidden", "true")
  mark.textContent = "HF"
  const names = document.createElement("div")
  const title = document.createElement("p")
  title.className = "text-sm font-semibold text-heading"
  title.textContent = data?.brand ?? ""
  const badge = document.createElement("p")
  badge.className = "text-xs text-muted"
  badge.textContent = data?.badge ?? ""
  names.append(title, badge)
  brand.append(mark, names)

  const tabs = document.createElement("div")
  tabs.className = "flex flex-wrap gap-1"
  for (const page of data?.pages ?? []) {
    const active = page.id === data.active
    const tab = document.createElement("button")
    tab.type = "button"
    tab.dataset.page = page.id
    tab.textContent = page.title
    tab.setAttribute("aria-current", active ? "page" : "false")
    tab.className = active
      ? "cursor-default rounded-full bg-accent px-3 py-1.5 text-sm font-medium text-page"
      : "cursor-pointer rounded-full px-3 py-1.5 text-sm font-medium text-muted transition-colors hover:bg-accent-soft hover:text-ink focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
    if (!active) tab.onclick = () => setTriggerValue("page", page.id)
    tabs.appendChild(tab)
  }

  bar.append(brand, tabs)
  root.replaceChildren(bar)
}
