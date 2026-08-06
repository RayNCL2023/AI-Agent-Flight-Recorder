FROM python:3.12-slim AS runtime

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY sample_data ./sample_data

ENV DATABASE_URL=sqlite:////data/flight_recorder.db \
    FILE_READER_ROOT=/app/sample_data \
    HOST=0.0.0.0 \
    PORT=8000

VOLUME ["/data"]
EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
