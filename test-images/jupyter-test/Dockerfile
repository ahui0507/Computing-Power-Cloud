# 平台默认交互环境。GPU 驱动库由 NVIDIA Container Toolkit 注入。
FROM python:3.11-slim

ARG PIP_INDEX_URL=https://pypi.org/simple
RUN pip install --no-cache-dir --index-url "$PIP_INDEX_URL" \
    jupyterlab==4.2.5 jupyter-server==2.14.2

WORKDIR /workspace
ENV NVIDIA_DRIVER_CAPABILITIES=compute,utility
EXPOSE 8888

# 平台通过 Secret 注入每个实例的令牌；直接运行镜像时 Jupyter 自行生成令牌。
CMD ["jupyter-lab", "--ip=0.0.0.0", "--port=8888", "--no-browser", "--allow-root", "--ServerApp.root_dir=/workspace"]

