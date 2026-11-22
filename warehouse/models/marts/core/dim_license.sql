-- Dimensió de la llicència (tipus, p.e. `mit`) dels datasets de la mostra que en declaren.

select distinct
    {{ surrogate_key(['license']) }} as license_key,
    license
from {{ ref('int_dataset_measures') }}
where license is not null
