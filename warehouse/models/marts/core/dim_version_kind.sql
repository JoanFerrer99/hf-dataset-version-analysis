-- Dimensió del tipus de versió: un tag (Criteri A) o un commit, el més recent
-- d'una sessió de commits (Criteri B).

select
    {{ surrogate_key(['kind']) }} as version_kind_key,
    kind as version_kind
from (values ('tag'), ('commit')) as kinds(kind)
