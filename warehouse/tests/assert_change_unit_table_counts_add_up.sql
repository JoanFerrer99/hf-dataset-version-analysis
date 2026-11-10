-- A cada unitat de canvi, les taules de cada estat sumen el total, i els grups
-- (comparades, no comparades, afegides o eliminades) són la suma dels seus estats.
-- Retorna les unitats que no quadren.

select dataset_id, version_from, version_to
from {{ ref('mart_change_units') }}
where n_tables <> n_tables_ok + n_tables_identical_content + n_tables_absent_old + n_tables_absent_new
                  + n_tables_download_failed + n_tables_parse_failed + n_tables_too_large + n_tables_excluded
   or n_tables_compared <> n_tables_ok + n_tables_identical_content
   or n_tables_not_compared <> n_tables_download_failed + n_tables_parse_failed + n_tables_too_large
   or n_tables_added_or_removed <> n_tables_absent_old + n_tables_absent_new
