# syntax=docker/dockerfile:1
#
# Imatge per executar el pipeline (notebooks/eligibility_scan.py i
# notebooks/validate_eligible.py) sense dependre de l'entorn Python de la
# màquina host. Build en dues fases: "builder" instal·la les dependències
# en un virtualenv aïllat; "runtime" copia només aquest venv + el codi a
# una imatge slim, sense eines de build ni caché de pip.

FROM python:3.12-slim AS builder

WORKDIR /build

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:${PATH}"

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt


FROM python:3.12-slim AS runtime

# Usuari sense privilegis: el procés no necessita root per llegir el codi
# ni per escriure a data/ (muntat com a volum amb permisos de l'usuari host).
RUN groupadd --gid 1000 app && useradd --uid 1000 --gid app --create-home app

COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app
COPY --chown=app:app notebooks/ ./notebooks/

RUN mkdir -p /app/data && chown app:app /app/data

USER app

VOLUME ["/app/data"]

# Sense arguments, eligibility_scan.py imprimeix l'ajuda i surt (0) --
# entrypoint segur per defecte, mai comença un escaneig llarg per accident.
ENTRYPOINT ["python", "notebooks/eligibility_scan.py"]
CMD []
