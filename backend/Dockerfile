FROM python:3.11-slim

WORKDIR /app

# 安装系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# 安装 Python 依赖（利用 Docker 层缓存，先拷 requirements 再拷代码）
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制应用代码
COPY . .

# 创建数据目录
RUN mkdir -p /data/chroma_db /data/company_docs

EXPOSE 8000

# 生产环境不加 --reload；开发模式由 docker-compose.yml 通过 command 覆盖
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
