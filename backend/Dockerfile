FROM python:3.10-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DEFAULT_TIMEOUT=120 PIP_RETRIES=5
COPY requirements.txt ./
RUN --mount=type=cache,target=/root/.cache/pip python -m pip install -r requirements.txt
COPY app ./app
COPY data ./data
COPY run.py ./run.py
EXPOSE 8000
CMD ["python", "run.py"]
