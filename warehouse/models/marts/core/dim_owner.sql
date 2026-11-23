-- Dimensió de l'autor (propietari) dels datasets de la mostra: la primera part de l'id.

select distinct
    {{ surrogate_key(['owner']) }} as owner_key,
    owner
from {{ ref('int_dataset_measures') }}
