FROM python:3.12-slim

WORKDIR /app

COPY ./app ./app
COPY ./config ./config
COPY ./ralph_task.md ./ralph_task.md
COPY ./.ralph ./.ralph

RUN pip install fastapi uvicorn[standard]

EXPOSE 8000

CMD ["uvicorn", "app.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
