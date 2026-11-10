// Capçalera de cada pàgina: la secció, el títol i una frase que diu què s'hi veu.
export default function (component) {
  const { data, parentElement } = component
  const root = parentElement.querySelector("[data-root]")
  if (!root) return

  const header = document.createElement("header")
  header.className = "font-sans pt-2 pb-1"
  const eyebrow = document.createElement("p")
  eyebrow.className = "text-xs font-semibold uppercase tracking-widest text-accent"
  eyebrow.textContent = data?.eyebrow ?? ""
  const title = document.createElement("h1")
  title.className = "mt-1 text-3xl font-semibold tracking-tight text-heading"
  title.textContent = data?.title ?? ""
  const subtitle = document.createElement("p")
  subtitle.className = "mt-2 max-w-3xl text-base text-muted"
  subtitle.textContent = data?.subtitle ?? ""
  header.append(eyebrow, title, subtitle)
  root.replaceChildren(header)
}
