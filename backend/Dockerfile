FROM python:3.11-slim

# Fonts only — fpdf2 is pure Python, no native PDF deps needed
RUN apt-get update && apt-get install -y --no-install-recommends \
    fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p documents

EXPOSE 8000

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
