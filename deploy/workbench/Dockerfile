FROM jupyter-test:latest AS python-environment
USER root
COPY python /opt/campus-python
COPY wheels /wheels
RUN /opt/campus-python/bin/python3 -m pip install --no-cache-dir --no-index --find-links=/wheels jupyterlab==4.2.5

FROM jupyter-test:latest
USER root
RUN sed -i 's|http://deb.debian.org/debian|https://mirrors.tuna.tsinghua.edu.cn/debian|g' /etc/apt/sources.list.d/debian.sources \
    && apt-get -o Acquire::ForceIPv4=true -o Acquire::http::Timeout=20 -o Acquire::Retries=1 update \
    && apt-get -o Acquire::ForceIPv4=true -o Acquire::http::Timeout=20 -o Acquire::Retries=1 install -y --no-install-recommends openssh-server ca-certificates curl git sudo \
    && rm -rf /var/lib/apt/lists/* /etc/ssh/ssh_host_* \
    && mkdir -p /run/sshd && passwd -d root
COPY --from=python-environment /opt/campus-python /opt/campus-python
ENV PATH="/opt/campus-python/bin:${PATH}"
COPY clean-public-image.sh /usr/local/share/campus-workbench/clean-public-image.sh
RUN sh /usr/local/share/campus-workbench/clean-public-image.sh
WORKDIR /workspace
