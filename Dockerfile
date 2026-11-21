FROM python:3.13-slim@sha256:e48f59cdba69a3cbd9ed2cf0f348d90d45a8d350d98134cf1070bc106ee9ed90
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY coverage.json fetch_source.py /app/
RUN python /app/fetch_source.py
COPY scheduler.py selector.py map_codec.py python_impact.py field_impact.py /app/
CMD ["python", "/app/selector.py"]
