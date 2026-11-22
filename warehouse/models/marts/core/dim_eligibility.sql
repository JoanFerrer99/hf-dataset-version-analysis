-- Dimensió de l'elegibilitat d'un dataset de la mostra: `Si`, `Restringit`
-- (l'API va respondre 403) o `NoElegible` (també els que van fallar).

select
    {{ surrogate_key(['eligibility']) }} as eligibility_key,
    eligibility
from (values ('Si'), ('Restringit'), ('NoElegible')) as values_(eligibility)
