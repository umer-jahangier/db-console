FROM python:3.13-alpine

WORKDIR /app
COPY app.py .

USER 999:999
EXPOSE 8080
CMD ["python", "-u", "app.py"]
