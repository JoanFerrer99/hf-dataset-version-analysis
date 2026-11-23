-- Dimensió de la posició de la versió en la història del dataset: la primera,
-- una d'intermèdia o l'última. Un dataset amb una sola versió la té com a primera.

select
    {{ surrogate_key(['position']) }} as version_order_key,
    position as version_position,
    rank as position_rank
from (values ('First', 1), ('Intermediate', 2), ('Last', 3)) as positions(position, rank)
