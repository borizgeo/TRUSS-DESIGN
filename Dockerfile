FROM python:3.10-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV HSS_TRUSS_HOST=0.0.0.0

WORKDIR /app

COPY requirements.txt ./
RUN python -m pip install --upgrade pip \
	&& python -m pip install --no-cache-dir -r requirements.txt

COPY . .

RUN adduser --disabled-password --gecos "" appuser \
	&& chown -R appuser /app
USER appuser

EXPOSE 8501

CMD ["python", "launch_web_server.py"]
