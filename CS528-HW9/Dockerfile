FROM python:3.12-slim-bookworm
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY web_server.py browser-demo.html ./
ENV PYTHONUNBUFFERED=1 PORT=8080
USER 65532:65532
EXPOSE 8080
CMD ["python", "web_server.py"]
