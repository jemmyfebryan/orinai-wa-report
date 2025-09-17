FROM python:3.11.3-slim

ENV PYTHONUNBUFFERED=True
ENV APP_HOME=/app

WORKDIR $APP_HOME

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["python", "-m", "src.orin_wa_report.main"]
