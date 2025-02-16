# Используем официальный образ Python
FROM python:3.9-slim

# Устанавливаем рабочую директорию
WORKDIR /homework

# Копируем зависимости
COPY requirements.txt .

# Устанавливаем зависимости
RUN pip install --no-cache-dir -r requirements.txt

# Копируем исходный код приложения
COPY .. .

# Устанавливаем переменные окружения (если нужно)
ENV PYTHONUNBUFFERED=1

# Команда для запуска приложения
CMD ["python", "memc_load.py", "--pattern=/data/appsinstalled/*.tsv.gz", "--dry"]