-- Fet dels datasets (Star_Dataset). Gra: un dataset de la mostra. Les mesures
-- de les versions (versions, mida, fitxers, files i columnes, inicials i
-- finals) només es tenen per als elegibles.

select
    {{ surrogate_key(['measures.dataset_id']) }} as dataset_key,
    {{ surrogate_key(['measures.owner']) }} as owner_key,
    cast(strftime(measures.created_at, '%Y%m%d%H') as integer) as creation_time_key,
    {{ surrogate_key(['measures.eligibility']) }} as eligibility_key,
    case when measures.license is not null then {{ surrogate_key(['measures.license']) }} end as license_key,
    case when bands.downloads_band is not null then {{ surrogate_key(['bands.downloads_band']) }} end
        as downloads_band_key,
    measures.dataset_id,
    measures.num_tags,
    measures.num_branches,
    measures.num_tabular_commits,
    measures.n_versions,
    measures.initial_size_bytes,
    measures.final_size_bytes,
    measures.initial_n_files,
    measures.final_n_files,
    measures.initial_n_columns,
    measures.initial_n_rows
from {{ ref('int_dataset_measures') }} as measures
inner join {{ ref('int_dataset_bands') }} as bands
    on bands.dataset_id = measures.dataset_id
