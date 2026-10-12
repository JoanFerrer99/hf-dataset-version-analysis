# Decisions obertes del motor de detecció

Decisions que el motor pren amb un valor per defecte però que cal
confirmar amb el director. Per a cadascuna: què fa el motor ara,
l'alternativa, i on és al codi. Les que tenen una opció a
`src/diffengine/config.py` es poden canviar sense tocar codi.

- Les decisions ja tancades són a `docs/decisions_tfg.txt` (T-17 i T-20).
- Les preguntes sobre els desacords amb la Taula 1 del paper, comprovades
  amb les dades, són a `docs/validacio_census_income.md`.

---

## Quines taules es comparen

### Fitxers tabulars que no són dades

**Ara:** no es comparen. Són, per exemple, els manifests de checksums
(`MANIFEST_SHA256.csv`) o el `metadata.csv` d'un repositori d'imatges o
d'àudio. Les regles de la llibreria `datasets` ja en deixen fora la major
part; si un d'aquests fitxers canvia, queda registrat amb l'estat
`excluded` i sense codis.

**On:** `units.resolve_units` decideix què és una taula, i
`pairs.pair_units` registra els exclosos.

### Taules massa grans

**Ara:** una taula LeRobot pot tenir centenars d'episodis. Si la versió
antiga i la nova sumen més de 500 MB, no es descarreguen: la parella queda
amb l'estat `too_large` i **cap codi**. Les taules amb el mateix contingut a
les dues revisions (mateix hash a git) mai es descarreguen. Aquest límit
només s'aplica al pipeline: la validació de Census Income compara sempre els
fitxers sencers (el més gran fa 4,1 MB).

**Alternativa:** comparar-ne només un resum (un perfil per columna) en lloc
de no comparar-les. Encara no està fet.

**On:** `max_unit_bytes` a `config.py`; es comprova a `pairs.compare_pair`.

---

## Com s'etiqueten els canvis

### Una cel·la que passa a estar buida, o al revés

**Ara:** si en una fila aparellada una cel·la passa de tenir valor a estar
buida (o al revés), és un canvi de valors absents (**C510**).

**Alternativa:** tractar-ho com un canvi de valor (C312 o C322).

**On:** `null_transition_is_c510` a `config.py`; s'aplica a
`detectors/data.detect_missing`.

### Quan dues files són la mateixa fila editada

**Ara:** dues files que no són idèntiques són la mateixa fila amb alguna
cel·la editada si coincideixen en almenys la **meitat** de les columnes que
serveixen per aparellar. Si no, la fila antiga s'ha eliminat (C422) i la
nova s'ha afegit (C421). Si hi ha una columna clau (un identificador), la
fila és la mateixa si té la mateixa clau.

**Alternativa:** un altre llindar.

**On:** `edited_row_min_agreement` a `config.py`; s'aplica a
`rows._HashMatcher._plausible_edits`.

### Un canvi de tipus es codifica pel tipus antic

**Ara:** quan una columna passa de categòrica a numèrica, o al revés
(també amb one-hot), el codi depèn del tipus que tenia a la versió antiga:
**C311** si era categòrica, **C321** si era numèrica.

**Alternativa:** triar el codi pel tipus nou.

**On:** `kind_change_by_old_kind` a `config.py`; s'aplica a
`detectors/column_kind.detect_kinds`.

### Codificar categories com a nombres

**Ara:** si un canvi de tipus és una correspondència u a u entre valors
(codificar `Private` com a 2, `Male` com a 1…), han canviat el tipus i els
valors del domini: **C311 + C312 `recoded`**, com marca la Taula 1 a D3/D4.
Un canvi només de format ("1" escrit com a text → 1) no és C312.

**Alternativa:** només C312, com marca la Taula 1 a D7. La taula no és
coherent entre versions (`docs/validacio_census_income.md`, secció 5.2).

**On:** `detectors/column_kind._recoding`.

### Els canvis només de format es reporten

**Ara:** es reporten amb el subtipus `representation`, en lloc d'amagar-los:
espais o majúscules en una categòrica (C312), coma decimal o notació
científica en una numèrica (C322), i el símbol que vol dir "absent", p.e.
`?` en lloc d'una cel·la buida (C510).

**Alternativa:** no reportar-los.

**On:** `report_representation` a `config.py` (per a C322 i C510; els de
C312 es reporten sempre).

### El text lliure

**Ara:** una columna de text amb molts valors diferents i llargs (descripcions,
comentaris) es tracta com a text lliure: se'n comparen les cel·les i els
buits, però no la distribució (C530) ni la correlació amb altres columnes
(C520), que amb tants valors diferents no tindrien sentit.

**Alternativa:** comparar-ne també la distribució.

**On:** `text_min_distinct_share` i `text_min_mean_length` a `config.py`;
s'aplica a `load._text_or_categorical`.

### Una fórmula no genera també un canvi de distribució

**Ara:** si els valors nous d'una columna s'expliquen a partir dels antics
amb una fórmula (C322: multiplicar per un factor, logaritme, min-max,
estandardització…) o amb soroll afegit, **no** s'hi afegeix C530: la
distribució canvia justament per aquesta fórmula.

**Alternativa:** reportar també C530. El text del paper (§4) diu que els
canvis elementals poden aparèixer junts, i cap cas de la Taula 1 ho resol.

**On:** `transformation_suppresses_c530` a `config.py`; s'aplica a
`detectors/data.detect_distribution`.

### C312 només en files aparellades

**Ara:** un canvi de valors d'una categòrica (C312) només surt de files
aparellades (o d'un canvi de format). Si una categoria apareix o desapareix
només perquè s'han afegit o eliminat files, el canvi és C421 o C422, no
C312.

**Alternativa:** comparar també els valors de tota la columna.

**On:** `detectors/column_kind.detect_values` (només compara files
aparellades).

### Els comptadors de posició no són dades

**Ara:** les columnes que són la posició de la fila (enters que creixen fila
a fila a les dues versions, com `index` o `episode_index` a LeRobot) no
serveixen per aparellar files ni entren a C520/C530. Si es renumeren
(perquè s'ha inserit una fila al mig), surten com a C322 `renumbered`. Es va
trobar a l'execució real, a `stlee601/cube_pick1`.

**Alternativa:** tractar-les com qualsevol columna numèrica.

**On:** `rows.is_sequence` i `rows._HashMatcher` (les deixa fora del hash).

### Les taules dels repositoris de vídeo

**Ara:** en un repositori de vídeo o d'imatge amb taules (p.e. LeRobot, amb
més vídeos que parquets), els fitxers tabulars que la media no fa servir es
resolen com a taules pròpies i es comparen. La regla estricta de `datasets`
(un sol format per repositori) els deixaria fora.

**Alternativa:** seguir `datasets` al peu de la lletra.

**On:** `units.resolve_units`.

---

## Altres preguntes d'etiquetatge

- **Real → enter arrodonint** (`3.7` → `4`): és C321 `real_to_integer`
  (canvi de tipus). Els valors també canvien lleugerament; per defecte no
  s'hi afegeix C322.
- **Files eliminades per un predicat que també tenien buits**: si les
  files eliminades són exactament les d'una categoria i, alhora, totes
  tenen algun buit, el motor diu `had_nulls` (es comprova abans que
  `predicate`). Totes dues descripcions són certes; quina s'ha de
  preferir?

## Pendent

- **Benchmark d'Explain-Da-V**: pendent de revisar-ne la llicència i el
  format; el mapatge dels seus tipus de canvi als nostres codis s'afegirà
  aquí abans de fer-lo servir.
