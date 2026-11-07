FROM python:3.11-slim
WORKDIR /app
COPY dashboard/backend/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt
COPY . /app
ENV PYTHONPATH=/app:/app/dashboard/backend
WORKDIR /app/dashboard/backend
EXPOSE 8080
CMD ["python", "run_api.py"]
