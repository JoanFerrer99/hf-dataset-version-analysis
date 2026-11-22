-- Conciliació 1: cada versió de fact_version té, a dim_differences, exactament
-- els codis de change_classification.csv per a la comparació que hi arriba, en
-- els dos sentits. Retorna els codis que són a un costat i no a l'altre.

with classification as (
    select dataset_id, version_to as commit_sha, code
    from {{ ref('stg_change_classification') }}
),

facts as (
    select versions.dataset_id, versions.commit_sha, unnest(string_split(differences.differences, '+')) as code
    from {{ ref('fact_version') }} as versions
    inner join {{ ref('dim_differences') }} as differences
        on differences.differences_key = versions.differences_key
    where differences.differences_status = 'changed'
),

only_in_classification as (
    select 'només a change_classification.csv' as side, * from classification
    except all
    select 'només a change_classification.csv', * from facts
),

only_in_facts as (
    select 'només a fact_version' as side, * from facts
    except all
    select 'només a fact_version', * from classification
)

select * from only_in_classification
union all
select * from only_in_facts
