FROM python:3.11-slim-bookworm

WORKDIR /app

# Install system dependencies manually (avoid playwright install-deps)
RUN apt-get update && apt-get install -y \
    libnss3 \
    libx11-xcb1 \
    libxcomposite1 \
    libxcursor1 \
    libxdamage1 \
    libxi6 \
    libxtst6 \
    libxrandr2 \
    libasound2 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libgtk-3-0 \
    libgbm1 \
    libxshmfence1 \
    libxfixes3 \
    libxrender1 \
    libxkbcommon0 \
    libpango-1.0-0 \
    libcairo2 \
    libgdk-pixbuf2.0-0 \
    libglib2.0-0 \
    libdbus-1-3 \
    libexpat1 \
    libfontconfig1 \
    libfreetype6 \
    libpng16-16 \
    libgssapi-krb5-2 \
    libkrb5-3 \
    libcom-err2 \
    libk5crypto3 \
    libzstd1 \
    liblzma5 \
    libbz2-1.0 \
    libffi8 \
    libpcre2-8-0 \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright but skip deps installation
RUN playwright install chromium

# Copy application
COPY . .

EXPOSE 8000

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]