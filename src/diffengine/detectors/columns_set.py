"""
C2xx, canvis en el conjunt de columnes: ordre (C210), columna afegida (C221),
eliminada (C222) o reanomenada (C223).

No cal calcular gaire: l'aparellament de columnes (`columns.py`) ja ha decidit
quines són la mateixa, quines són noves i quines han desaparegut. Aquí
només es converteix en codis.
"""

from diffengine.columns import order_changed
from diffengine.detectors.common import Context, change
from diffengine.output import Change


def detect_column_set(ctx: Context) -> list[Change]:
    """
    Canvis en el conjunt de columnes: ordre (C210), columnes afegides (C221),
    eliminades (C222) i reanomenades (C223), i una categòrica convertida en
    diverses columnes 0/1 (C311 `one_hot`).

    :param ctx: context de la comparació: les dues taules, els aparellaments i els llindars.
    :return: els canvis trobats.
    """
    out = []
    if order_changed(ctx.old, ctx.new, ctx.cols):
        out.append(change("C210", evidence={"old_order": list(ctx.old.values.columns),
                                            "new_order": list(ctx.new.values.columns)}))
    for n in ctx.cols.added:
        origin = ctx.cols.derived.get(n)
        out.append(change("C221", column=n, subtype="derived" if origin else "unexplained",
                          evidence={"origin": origin, "kind": ctx.new.columns[n].kind}))
    for o in ctx.cols.removed:
        out.append(change("C222", old_column=o, subtype=ctx.cols.removed_subtypes.get(o, "unexplained"),
                          evidence={"kind": ctx.old.columns[o].kind,
                                    "null_share": float(ctx.old.values[o].isna().mean())}))
    for m in ctx.cols.matches:
        if m.old != m.new:
            out.append(change("C223", m, confidence=m.validity, evidence={"method": m.method, **m.detail}))
    for oh in ctx.cols.one_hot:
        out.append(change("C311", old_column=oh["old"], subtype="one_hot", evidence=oh))
    return out
