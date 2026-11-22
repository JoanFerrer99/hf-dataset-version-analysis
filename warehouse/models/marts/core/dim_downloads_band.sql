-- Dimensió de l'interval de descàrregues (k-means, `int_dataset_bands`): `Few`, `Medium` o `Many`.

select
    {{ surrogate_key(['band']) }} as downloads_band_key,
    band as downloads_band,
    rank as band_rank
from (values ('Few', 1), ('Medium', 2), ('Many', 3)) as bands(band, rank)
