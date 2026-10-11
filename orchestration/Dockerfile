# Airflow 3.3.2 + our pipeline in an ISOLATED virtualenv.
#
# Why a separate venv: Airflow pins hundreds of library versions (constraints file).
# Installing our requirements into Airflow's own environment can silently up/downgrade
# them and break the scheduler. Tasks call /home/airflow/pipeline-venv/bin/python,
# so Airflow and the pipeline never share packages. (Same idea as running each task
# in its own container with KubernetesPodOperator on Cloud Composer.)
FROM apache/airflow:3.3.2-python3.12

# Airflow-side extra: pytest for DAG integrity tests. Re-pinning airflow stops pip upgrading it.
RUN pip install --no-cache-dir "apache-airflow==3.3.2" "pytest>=8,<9"

COPY --chown=airflow:root requirements.txt /tmp/pipeline-requirements.txt
RUN python -m venv /home/airflow/pipeline-venv \
 && /home/airflow/pipeline-venv/bin/pip install --no-cache-dir -U pip \
 && /home/airflow/pipeline-venv/bin/pip install --no-cache-dir -r /tmp/pipeline-requirements.txt
